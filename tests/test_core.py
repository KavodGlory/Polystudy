"""Tests for the matching engine: exact, phrase, fuzzy, reverse and no-match cases."""
import pytest

from translator import LANGS, Glossary, normalise, resolve_langs
from translator.core import validate_entries


@pytest.fixture(scope="module")
def g():
    return Glossary.load()


def ids(matches):
    return [m.entry["id"] for m in matches]


# ---------------------------------------------------------------- glossary data
def test_glossary_has_at_least_60_entries(g):
    assert len(g.entries) >= 60


def test_every_entry_has_all_six_translations(g):
    for e in g.entries:
        assert set(e["translations"]) == set(LANGS), e["id"]
        assert all(e["translations"][c].strip() for c in LANGS), e["id"]


def test_required_categories_are_covered(g):
    wanted = {"greetings", "politeness", "transport", "food", "money", "directions",
              "emergency", "campus", "sheng"}
    assert wanted <= set(g.categories())


def test_needs_review_is_a_bool_and_slang_is_flagged(g):
    for e in g.entries:
        assert isinstance(e["needs_review"], bool)
        if e["category"] == "sheng":
            assert e["needs_review"], f"Sheng entry {e['id']} should be reviewed by a native speaker"


def test_duplicate_alias_across_entries_is_rejected(g):
    a = dict(g.get("asante")); b = dict(g.get("karibu"))
    b["aliases"] = ["Asante!"]          # normalises to the same alias as entry "asante"
    with pytest.raises(ValueError, match="used by both"):
        validate_entries([a, b])


def test_missing_translation_is_rejected(g):
    bad = dict(g.get("asante")); bad["translations"] = {"fr": "Merci"}
    with pytest.raises(ValueError, match="no translation"):
        validate_entries([bad])


# --------------------------------------------------------------- normalisation
@pytest.mark.parametrize("raw, expected", [
    ("  Asante!!  ", "asante"),
    ("HABARI   YAKO?", "habari yako"),
    ("Où sont les toilettes ?", "ou sont les toilettes"),
    ("Salut, ça va ?", "salut ca va"),
    ("M-Pesa", "m pesa"),
    ("¿Cómo estás?", "como estas"),
])
def test_normalise(raw, expected):
    assert normalise(raw) == expected


def test_normalise_keeps_japanese_voiced_marks():
    assert normalise("ありがとうございます") == "ありがとうございます"
    assert normalise("ゆっくり、ゆっくり") == "ゆっくり ゆっくり"
    assert "が" in normalise("お腹がすいています")


# ---------------------------------------------------------------------- exact
def test_exact_match(g):
    m = g.find("asante")
    assert ids(m) == ["asante"] and m[0].kind == "exact"


def test_exact_match_ignores_case_and_punctuation(g):
    assert ids(g.find("ASANTE!!!")) == ["asante"]


def test_exact_match_on_alias(g):
    assert ids(g.find("niaje")) == ["mambo"]


# --------------------------------------------------------------------- phrase
def test_phrase_inside_sentence(g):
    m = g.find("excuse me, where is the toilet please")
    assert "choo" in ids(m) and m[0].kind == "phrase"


def test_phrase_longest_match_wins(g):
    # "pole pole" must not be split into two hits of "pole"
    m = g.find("pole pole my friend")
    assert ids(m) == ["pole_pole"]


def test_phrase_returns_multiple_entries_in_typed_order(g):
    m = g.find("asante sana, karibu")
    assert ids(m) == ["asante", "karibu"]


def test_naomba_maji_beats_naomba_and_maji(g):
    assert ids(g.find("naomba maji tafadhali")) == ["naomba_maji", "tafadhali"]


# ---------------------------------------------------------------------- fuzzy
def test_fuzzy_match_fixes_typos_and_is_labelled(g):
    m = g.find("asnte")
    assert ids(m) == ["asante"] and m[0].kind == "fuzzy"


def test_fuzzy_inside_sentence(g):
    m = g.find("kwaherri my friend")
    assert ids(m) == ["kwaheri"] and m[0].kind == "fuzzy"


def test_short_words_are_never_fuzzy_matched(g):
    assert g.find("poe") == []


# -------------------------------------------------------------------- no match
@pytest.mark.parametrize("text", ["", "   ", "!!!", "xyzabc", "quantum entanglement"])
def test_no_match(g, text):
    assert g.find(text) == []
    assert g.lookup(text) == ("none", [])


# -------------------------------------------------------------------- reverse
def test_reverse_exact_french(g):
    m = g.find_reverse("Merci beaucoup")
    assert ids(m) == ["asante"] and m[0].lang == "fr" and m[0].kind == "exact"


def test_reverse_ignores_accents(g):
    assert "choo" in ids(g.find_reverse("Ou sont les toilettes"))


def test_reverse_japanese_and_chinese(g):
    m = g.find_reverse("ありがとうございます")                        # a shortened form of the stored text...
    assert ids(m) == ["asante"] and m[0].kind == "fuzzy" and m[0].lang == "ja"
    assert "maji" in ids(g.find_reverse("水"))                          # ...and one-character words work
    assert "choo" in ids(g.find_reverse("洗手间在哪里"))


def test_reverse_arabic_ignores_punctuation(g):
    assert "choo" in ids(g.find_reverse("أين الحمّام؟"))


def test_reverse_uses_slash_alternatives(g):
    m = g.find_reverse("de acuerdo")
    assert ids(m) == ["sawa"] and m[0].lang == "es"


def test_reverse_fuzzy(g):
    m = g.find_reverse("Merci beaucop")
    assert ids(m) == ["asante"] and m[0].kind == "fuzzy"


# ---------------------------------------------------------------- lookup order
def test_lookup_direction(g):
    assert g.lookup("asante")[0] == "forward"
    assert g.lookup("Muchas gracias")[0] == "reverse"
    assert g.lookup("how much is this")[0] == "forward"
    assert g.lookup("asnte")[0] == "forward"


def test_exact_reverse_beats_fuzzy_forward(g):
    # Spanish "Hospital" is one letter away from the Swahili "hospitali".
    direction, m = g.lookup("Hospital")
    assert direction == "reverse" and m[0].kind == "exact"


# ---------------------------------------------------------------------- langs
@pytest.mark.parametrize("arg, expected", [
    ("fr", ["fr"]), ("French", ["fr"]), ("fr de", ["fr", "de"]), ("ja, zh", ["ja", "zh"]),
    ("all", list(LANGS)), ("chinese", ["zh"]),
])
def test_resolve_langs(arg, expected):
    assert resolve_langs(arg) == expected


@pytest.mark.parametrize("arg", ["", "klingon", "fr klingon"])
def test_resolve_langs_rejects_unknown(arg):
    assert resolve_langs(arg) is None


# ----------------------------------------------------------------- matches_in
def test_matches_in_finds_terms_but_never_guesses(g):
    assert ids(g.matches_in("mambo msee, naomba msaada")) == ["mambo", "msee", "msaada"]
    assert ids(g.matches_in("asante")) == ["asante"]
    assert g.matches_in("asnte") == []              # a typo is a guess, so no hint is produced
    assert g.matches_in("") == []
