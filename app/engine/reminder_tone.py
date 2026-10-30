"""Chooses the tone of a payment reminder from how overdue the bill is."""


def tone_for(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "friendly"
    if days_overdue <= 7:
        return "polite"
    if days_overdue <= 30:
        return "firm"
    return "final"
