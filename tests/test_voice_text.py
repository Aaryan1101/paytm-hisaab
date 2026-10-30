import pytest

from app.ai.hindi_numbers import parse_amount
from app.ai.money_format import inr, spoken
from app.ai.speech_text import speakable


@pytest.mark.parametrize("text,expected", [
    ("Sharma ko paanch hazaar cash diye", 5000), ("Agarwal dairy ko teen hazaar cash diye", 3000),
    ("ek lakh baarah hazaar", 112000), ("do sau pachas", 250), ("5000", 5000), ("₹5,000 diye", 5000),
    ("3k", 3000), ("2.5 lakh", 250000), ("five thousand", 5000), ("dedh hazaar", 1500), ("dhai sau", 250),
    ("bees hazaar", 20000), ("hazaar", None), ("kuch nahi", None), ("Rs 750", 750),
])
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("amount,expected", [
    (0, "₹0"), (950, "₹950"), (1000, "₹1,000"), (42300, "₹42,300"), (112400, "₹1,12,400"), (5000000, "₹50,00,000"),
    (-1500, "-₹1,500"), (18640.4, "₹18,640"),
])
def test_inr(amount, expected):
    assert inr(amount) == expected


@pytest.mark.parametrize("amount,expected", [
    (112400, "1 lakh 12 hazaar"), (42300, "42 hazaar"), (38000, "38 hazaar"), (3250, "3 hazaar 3 sau"),
    (450, "450"), (250000, "2 lakh 50 hazaar"), (100000, "1 lakh"),
])
def test_spoken(amount, expected):
    assert spoken(amount) == expected


def test_speakable_strips_markup_and_emoji():
    assert speakable("*Bill padh liya* ✅ Sharma Traders ₹18,640") == "Bill padh liya Sharma Traders ₹18,640"


def test_speakable_limits_sentences():
    assert speakable("Ek. Do. Teen.") == "Ek. Do."


def test_speakable_drops_urls_and_bullets():
    assert speakable("• Pehla https://x.co/a dusra") == "Pehla dusra"


def test_speakable_caps_length():
    out = speakable("word " * 200)
    assert len(out) <= 262 and out.endswith(".")


def test_speakable_handles_devanagari_danda():
    assert speakable("यह पहला है। यह दूसरा है। यह तीसरा है।") == "यह पहला है। यह दूसरा है।"
