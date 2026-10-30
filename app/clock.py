from datetime import date, datetime

from app.config import settings


def today() -> date:
    """The app's notion of today; pinned in demo mode so seeded data stays consistent."""
    return settings.demo_today or date.today()


def now() -> datetime:
    """Naive 'now'; in demo mode the date is pinned and only the time of day is real."""
    real = datetime.now()
    return datetime.combine(today(), real.time())
