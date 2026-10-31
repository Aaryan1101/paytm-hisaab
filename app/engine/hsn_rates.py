"""Allowed GST rates (percent) by HSN prefix for common FMCG goods, post GST 2.0.

Source: vendor summaries of the 22 Sep 2025 rate change (accountune.com, taxguru.in, busy.in),
not the CBIC notification. Verify on cbic.gov.in before relying on it. Each prefix allows a set
because loose/unbranded goods differ from packaged/branded ones, and where sources disagree
(detergent, chocolate) both candidate rates are allowed so we don't raise false alarms. Rows the source itself
marked 'confirm tariff item', the deferred 28% items and broad fruit/vegetable ranges are left out.
"""
from datetime import date

EFFECTIVE_FROM = date(2025, 9, 22)  # bills dated earlier were taxed under the old slabs

ALLOWED_RATES: dict[str, set[float]] = {
    # staples and fresh produce
    "1001": {0, 5},     # wheat: unbranded 0
    "1006": {0, 5},     # rice: loose 0, packaged 5
    "1101": {0, 5},     # atta, maida
    "0713": {0, 5},     # pulses and dal
    "0407": {0},        # eggs
    "2501": {0},        # salt
    "1701": {5},        # sugar
    "0902": {5},        # tea
    "0901": {5},        # coffee
    "0409": {5},        # honey (branded)
    # edible oils: the whole 1507-1516 range is 5%
    "1507": {5}, "1508": {5}, "1509": {5}, "1510": {5}, "1511": {5}, "1512": {5}, "1513": {5}, "1514": {5}, "1515": {5}, "1516": {5},
    # dairy
    "0401": {0},        # milk incl. UHT
    "0402": {5},        # condensed milk, flavoured milk drinks
    "0403": {0, 5},     # curd, yoghurt: loose 0, packaged 5
    "0405": {5},        # butter, ghee
    "0406": {0, 5},     # paneer: loose 0, packaged 5; packaged cheese 5
    # packaged food and snacks
    "1806": {5, 18},    # chocolate (sources disagree)
    "1905": {0, 5},     # biscuits 5; plain bread, roti, paratha 0
    "1902": {5},        # instant noodles, pasta
    "1904": {5},        # cornflakes, popcorn
    "2005": {5},        # potato chips
    "2106": {5, 18},    # namkeen / food preparations
    "2103": {5},        # ketchup, sauces
    "2007": {5},        # jam, jelly
    "1704": {5},        # sugar confectionery, candy
    "2105": {5},        # ice cream
    # drinks
    "2009": {5},        # fruit juices
    "2202": {40},       # carbonated and energy drinks (other 2202 drinks may differ)
    # personal care and household
    "3401": {5},        # soap
    "3304": {5, 18},    # skin care 5; non-basic cosmetics 18
    "3305": {5},        # shampoo, hair oil
    "3306": {5},        # toothpaste
    "9603": {5},        # toothbrush
    "3307": {5, 18},    # shaving cream 5; deodorant 18
    "3303": {18},       # perfume
    "3402": {5, 18},    # detergent (sources disagree)
    "9619": {0},        # sanitary napkins
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
