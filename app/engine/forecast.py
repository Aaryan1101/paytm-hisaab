"""14-day cash forecast: weekday-average inflow x festival multiplier, minus scheduled dues."""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import pstdev

from app.engine import festivals

DEFAULT_BUFFER = 10_000.0
HISTORY_WEEKS = 8


@dataclass(frozen=True)
class ForecastDay:
    day: date
    inflow: float
    outflow: float
    balance: float
    low: float
    high: float


@dataclass(frozen=True)
class Forecast:
    days: list[ForecastDay]
    buffer: float
    first_below_date: date | None  # first day the balance drops under the buffer
    shortfall_date: date | None    # day of the lowest balance, when that is under the buffer
    shortfall_amount: float        # buffer minus the lowest balance (0 if never below the buffer)


def _window(today: date, weeks: int) -> list[date]:
    return [today - timedelta(days=i) for i in range(weeks * 7)]


def weekday_means(history: dict[date, float], today: date, weeks: int = HISTORY_WEEKS) -> dict[int, float]:
    """Mean daily inflow by weekday over the window; days with no record count as zero."""
    sums, counts = [0.0] * 7, [0] * 7
    for d in _window(today, weeks):
        sums[d.weekday()] += history.get(d, 0.0)
        counts[d.weekday()] += 1
    return {wd: sums[wd] / counts[wd] for wd in range(7)}


def inflow_std(history: dict[date, float], today: date, weeks: int = HISTORY_WEEKS) -> float:
    return pstdev([history.get(d, 0.0) for d in _window(today, weeks)])


def build_forecast(
    today: date,
    opening_balance: float,
    daily_collections: dict[date, float],
    dues: list[tuple[date, float]],
    other_daily_spend: float = 0.0,
    days: int = 14,
    buffer: float = DEFAULT_BUFFER,
    multiplier: Callable[[date], float] = festivals.multiplier,
) -> Forecast:
    means = weekday_means(daily_collections, today)
    std = inflow_std(daily_collections, today)
    first_day = today + timedelta(days=1)
    outflow_by_day: dict[date, float] = {}
    for due_date, amount in dues:
        key = max(due_date, first_day)  # overdue or due-today bills hit on the first forecast day
        outflow_by_day[key] = outflow_by_day.get(key, 0.0) + amount

    out: list[ForecastDay] = []
    balance = opening_balance
    for i in range(days):
        d = first_day + timedelta(days=i)
        inflow = means[d.weekday()] * multiplier(d)
        outflow = outflow_by_day.get(d, 0.0) + other_daily_spend
        balance = balance + inflow - outflow
        out.append(ForecastDay(d, round(inflow, 2), round(outflow, 2), round(balance, 2),
                               round(balance - std, 2), round(balance + std, 2)))

    first_below = next((x for x in out if x.balance < buffer), None)
    lowest = min(out, key=lambda x: x.balance)
    short = lowest.balance < buffer
    return Forecast(
        days=out,
        buffer=buffer,
        first_below_date=first_below.day if first_below else None,
        shortfall_date=lowest.day if short else None,
        shortfall_amount=round(buffer - lowest.balance, 2) if short else 0.0,
    )
