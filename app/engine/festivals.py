"""Small festival calendar: inflow multipliers applied on top of the weekday baseline."""
from datetime import date

FESTIVAL_WINDOWS: list[tuple[date, date, float]] = [
    (date(2026, 10, 12), date(2026, 10, 20), 1.3),  # Navratri / Dussehra
    (date(2026, 11, 2), date(2026, 11, 8), 1.6),    # Diwali week
]


def multiplier(d: date) -> float:
    for start, end, factor in FESTIVAL_WINDOWS:
        if start <= d <= end:
            return factor
    return 1.0
