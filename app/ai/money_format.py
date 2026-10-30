"""Rupee formatting for screens (Indian digit grouping) and for speech (rounded, lakh/hazaar)."""


def inr(amount: float) -> str:
    n = int(round(abs(amount)))
    s = str(n)
    head, tail = s[:-3], s[-3:]
    if head:
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return f"{'-' if amount < 0 else ''}₹{s}"


def spoken(amount: float) -> str:
    """Rounded, speakable: 112400 -> '1 lakh 12 hazaar', 42300 -> '42 hazaar', 3250 -> '3 hazaar 3 sau'."""
    n = int(abs(amount) + 0.5)
    if n < 1_000:
        return str(n)
    n = int(n / (1_000 if n >= 10_000 else 100) + 0.5) * (1_000 if n >= 10_000 else 100)  # half-up, not banker's
    lakh, rest = divmod(n, 100_000)
    hazaar, rest = divmod(rest, 1_000)
    sau = rest // 100
    parts = []
    if lakh:
        parts.append(f"{lakh} lakh")
    if hazaar:
        parts.append(f"{hazaar} hazaar")
    if sau and not lakh:
        parts.append(f"{sau} sau")
    return " ".join(parts) or str(n)
