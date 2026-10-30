from datetime import datetime, timezone


def utc_now() -> datetime:
    """Naive UTC timestamp (columns are NaiveDatetime)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
