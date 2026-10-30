"""Allowed GST rates (percent) by HSN prefix for common FMCG goods, post GST 2.0.

Source: vendor summaries of the 22 Sep 2025 rate change (accountune.com, taxguru.in, busy.in),
not the CBIC notification. Verify on cbic.gov.in before relying on it. Each prefix allows a set
because loose/unbranded goods differ from packaged/branded ones, and where sources disagree
(detergent, chocolate) both candidate rates are allowed so we don't raise false alarms.
"""
from datetime import date

EFFECTIVE_FROM = date(2025, 9, 22)  # bills dated earlier were taxed under the old slabs

ALLOWED_RATES: dict[str, set[float]] = {
    "1006": {0, 5},     # rice: loose 0, packaged 5
    "1101": {0, 5},     # atta
    "1701": {5},        # sugar
    "0902": {5},        # tea
    "0901": {5},        # coffee
    "1507": {5},        # soyabean oil
    "1512": {5},        # sunflower oil
    "1514": {5},        # mustard oil
    "0401": {0},        # milk incl. UHT
    "0405": {5},        # butter, ghee
    "0406": {0, 5},     # paneer: loose 0, packaged 5
    "3401": {5},        # soap
    "3304": {5},        # beauty / personal care
    "3305": {5},        # shampoo
    "3306": {5},        # toothpaste
    "3402": {5, 18},    # detergent (sources disagree)
    "1806": {5, 18},    # chocolate (sources disagree)
    "1905": {5},        # biscuits, bakery
    "2106": {5, 18},    # namkeen / food preparations
}


def allowed_rates(hsn: str | None) -> set[float] | None:
    """Return allowed rates for the HSN, or None if the code isn't in the table."""
    if not hsn:
        return None
    for length in (8, 6, 4):
        rates = ALLOWED_RATES.get(hsn[:length])
        if rates is not None:
            return rates
    return None
