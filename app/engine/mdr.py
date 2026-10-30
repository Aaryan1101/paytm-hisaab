"""UPI P2M merchant discount rate (from 15 Oct 2026): 0.4% above Rs 2,000, capped at Rs 300."""

MDR_RATE = 0.004
MDR_THRESHOLD = 2000.0
MDR_CAP = 300.0


def mdr_for(gross: float, exempt: bool = False) -> float:
    if exempt or gross <= MDR_THRESHOLD:
        return 0.0
    return round(min(gross * MDR_RATE, MDR_CAP), 2)


def net_of_mdr(gross: float, exempt: bool = False) -> float:
    return round(gross - mdr_for(gross, exempt), 2)
