from app.engine.name_match import similarity


def test_generic_words_ignored():
    assert similarity("Sharma Traders", "Chauhan Traders") < 60


def test_typo_still_matches():
    assert similarity("Agarwal diary", "Agarwal Dairy") > 85


def test_generic_only_names_fall_back_to_full_text():
    assert similarity("General Store", "General Store") == 100


def test_alias_prefix_matches():
    assert similarity("sharma", "Sharma Traders") == 100


from app.engine.name_match import same_party


def test_same_party_ignores_case_and_generic_words():
    assert same_party("SHARMA TRADERS", "Sharma Traders") and same_party("Sharma", "Sharma Traders & Co.")


def test_same_party_rejects_different_businesses():
    assert not same_party("Sharma Traders", "Sharma Textiles") and not same_party("Gupta Oil Mills", "Gupta Wholesale")


def test_same_party_forgives_a_typo_but_not_a_blank():
    assert same_party("Agarwal Dairy", "Agarwal Diary") and not same_party("", "Sharma")
