from app.engine import gstin


def test_known_valid_gstin():
    assert gstin.is_valid("27AAPFU0939F1ZV")


def test_corrupted_check_digit_rejected():
    assert not gstin.is_valid("27AAPFU0939F1ZX")


def test_bad_format_rejected():
    assert not gstin.is_valid("123")


def test_make_roundtrip():
    g = gstin.make("09", "ABCDE1234F")
    assert gstin.is_valid(g) and gstin.state_code(g) == "09"
