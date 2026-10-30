from app.engine.name_match import similarity


def test_generic_words_ignored():
    assert similarity("Sharma Traders", "Chauhan Traders") < 60


def test_typo_still_matches():
    assert similarity("Agarwal diary", "Agarwal Dairy") > 85


def test_generic_only_names_fall_back_to_full_text():
    assert similarity("General Store", "General Store") == 100


def test_alias_prefix_matches():
    assert similarity("sharma", "Sharma Traders") == 100
