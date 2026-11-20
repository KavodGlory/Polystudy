"""Core of the chatbot: the glossary, text normalisation and the matching engine.

Nothing in this file talks to the terminal, the web or the internet, so the CLI,
the web app and the tests can all share it.

How a lookup works (see Glossary.lookup):
    1. normalise the text            "Asante!!"  -> "asante"
    2. exact match on an alias       "asante"    -> entry "asante"
    3. exact match on a translation  "Merci"     -> entry "asante" (reverse lookup)
    4. phrase match inside a longer sentence, longest alias first
    5. fuzzy match to forgive typos  "asnte"     -> "asante" (labelled "closest match")
"""
from __future__ import annotations

import difflib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# Target languages: code -> display name.
LANGS = {
    "ar": "Arabic",
    "fr": "French",
    "ja": "Japanese",
    "es": "Spanish",
    "zh": "Chinese (Simplified)",
    "de": "German",
}
LANG_ALIASES = {
    "arabic": "ar", "french": "fr", "japanese": "ja", "spanish": "es",
    "chinese": "zh", "mandarin": "zh", "german": "de",
}
RTL_LANGS = {"ar"}  # languages written right to left

DEFAULT_GLOSSARY_PATH = Path(__file__).resolve().parent.parent / "data" / "glossary.json"

FUZZY_CUTOFF = 0.82          # 0..1. Higher = stricter spelling tolerance.
REVERSE_FUZZY_CUTOFF = 0.85
MIN_FUZZY_LEN = 4            # never fuzzy-match very short words ("poa" vs "pole")

REQUIRED_KEYS = ("id", "category", "aliases", "source_language", "register",
                 "meaning", "note", "translations", "needs_review")


# ---------------------------------------------------------------- languages
def resolve_langs(arg: str) -> list[str] | None:
    """Turn user input such as 'fr', 'French', 'fr de' or 'all' into language codes.

    Returns None if any part is not understood.
    """
    arg = arg.strip().lower()
    if arg in ("all", "*"):
        return list(LANGS)
    codes: list[str] = []
    for part in re.split(r"[,\s]+", arg):
        if not part:
            continue
        code = part if part in LANGS else LANG_ALIASES.get(part)
        if code is None:
            return None
        if code not in codes:
            codes.append(code)
    return codes or None


# ------------------------------------------------------------ normalisation
def _fold_accents(text: str) -> str:
    """Remove accents/diacritics from Latin and Arabic letters only.

    "ça va" -> "ca va". Japanese voiced marks (が, ぱ) are deliberately kept,
    because removing them would change the word.
    """
    out, last_base = [], ""
    for ch in unicodedata.normalize("NFD", text):
        if unicodedata.category(ch) == "Mn":
            code = ord(last_base) if last_base else 0
            if code and (code < 0x250 or 0x600 <= code <= 0x6FF):
                continue  # drop the accent
        else:
            last_base = ch
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def normalise(text: str) -> str:
    """Lowercase, fold accents, drop punctuation and collapse spaces."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace("’", "'").replace("‘", "'")
    text = _fold_accents(text)
    text = re.sub(r"[^\w\s']", " ", text)      # punctuation -> space (keeps apostrophes)
    text = re.sub(r"\s+", " ", text).strip(" '")
    return text


def _strip_parens(text: str) -> str:
    return re.sub(r"[(（][^)）]*[)）]", " ", text)


def _translation_variants(text: str) -> list[str]:
    """Searchable forms of one translation, for reverse lookup.

    "Vale / de acuerdo"      -> the whole string, "Vale", "de acuerdo"
    "Ugali (fester Maisbrei)" -> the whole string, "Ugali"
    """
    variants = [text]
    for part in re.split(r"\s*[/／]\s*", text):
        variants.append(part)
        variants.append(_strip_parens(part))
    variants.append(_strip_parens(text))
    return variants


def _usable(norm: str) -> bool:
    """Skip fragments like 'a' (from 'Bienvenido/a') but keep one-character CJK words like 水."""
    return len(norm) >= 2 or any(ord(c) > 0x2E80 for c in norm)


# ------------------------------------------------------------------ results
@dataclass(frozen=True)
class Match:
    """One glossary hit.

    entry : the glossary entry (a dict)
    term  : the normalised alias (forward) or translation (reverse) that matched
    kind  : "exact", "phrase" or "fuzzy"
    lang  : for reverse matches, the code of the language the user typed
    """
    entry: dict
    term: str
    kind: str
    lang: str | None = None


# ----------------------------------------------------------------- glossary
def validate_entries(entries: list[dict]) -> None:
    """Fail loudly on a malformed glossary instead of misbehaving later."""
    seen_ids: set[str] = set()
    alias_owner: dict[str, str] = {}
    for e in entries:
        missing = [k for k in REQUIRED_KEYS if k not in e]
        if missing:
            raise ValueError(f"Entry {e.get('id', '?')!r} is missing keys: {missing}")
        if e["id"] in seen_ids:
            raise ValueError(f"Duplicate entry id: {e['id']!r}")
        seen_ids.add(e["id"])
        if e["register"] not in ("standard", "slang"):
            raise ValueError(f"Entry {e['id']!r}: register must be 'standard' or 'slang'")
        absent = [c for c in LANGS if not str(e["translations"].get(c, "")).strip()]
        if absent:
            raise ValueError(f"Entry {e['id']!r} has no translation for: {absent}")
        if not e["aliases"]:
            raise ValueError(f"Entry {e['id']!r} has no aliases")
        for alias in e["aliases"]:
            norm = normalise(alias)
            if not norm:
                raise ValueError(f"Entry {e['id']!r} has an empty alias")
            owner = alias_owner.setdefault(norm, e["id"])
            if owner != e["id"]:
                raise ValueError(f"Alias {alias!r} is used by both {owner!r} and {e['id']!r}")


class Glossary:
    """The verified knowledge base plus fast lookup indexes."""

    def __init__(self, entries: list[dict]):
        validate_entries(entries)
        self.entries = entries
        self._by_id = {e["id"]: e for e in entries}

        # forward index: normalised Swahili/English/Sheng alias -> entry
        self._forward: dict[str, dict] = {}
        for e in entries:
            for alias in e["aliases"]:
                self._forward[normalise(alias)] = e
        # longest first, so "pole pole" is tried before "pole"
        self._forward_longest = sorted(self._forward, key=lambda t: (-len(t), t))
        self._forward_words = [t for t in self._forward if " " not in t]

        # reverse index: normalised translation -> [(entry, language code), ...]
        self._reverse: dict[str, list[tuple[dict, str]]] = {}
        for e in entries:
            for lang, text in e["translations"].items():
                for variant in _translation_variants(text):
                    norm = normalise(variant)
                    if norm and _usable(norm):
                        pairs = self._reverse.setdefault(norm, [])
                        if (e, lang) not in pairs:
                            pairs.append((e, lang))

    # -- loading ---------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path = DEFAULT_GLOSSARY_PATH) -> "Glossary":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    # -- simple accessors ------------------------------------------------
    def get(self, entry_id: str) -> dict:
        return self._by_id[entry_id]

    def categories(self) -> list[str]:
        return sorted({e["category"] for e in self.entries})

    # -- forward matching (Swahili / English / Sheng in) -----------------
    def _forward_exact(self, text: str) -> list[Match]:
        entry = self._forward.get(text)
        return [Match(entry, text, "exact")] if entry else []

    def _forward_phrases(self, text: str) -> list[Match]:
        padded = f" {text} "
        found: list[tuple[int, str]] = []
        for term in self._forward_longest:
            needle = f" {term} "
            pos = padded.find(needle)
            if pos != -1:
                found.append((pos, term))
                # blank out the hit (same length) so shorter aliases can't reuse it
                padded = padded.replace(needle, " " + "\x00" * len(term) + " ")
        found.sort()  # report in the order the words were typed
        matches, seen = [], set()
        for _, term in found:
            entry = self._forward[term]
            if entry["id"] not in seen:
                seen.add(entry["id"])
                matches.append(Match(entry, term, "phrase"))
        return matches

    def _forward_fuzzy(self, text: str) -> list[Match]:
        if len(text) >= MIN_FUZZY_LEN:
            close = difflib.get_close_matches(text, self._forward, n=1, cutoff=FUZZY_CUTOFF)
            if close:
                return [Match(self._forward[close[0]], close[0], "fuzzy")]
        # otherwise try each word of a sentence on its own
        matches, seen = [], set()
        for word in text.split():
            if len(word) < MIN_FUZZY_LEN:
                continue
            close = difflib.get_close_matches(word, self._forward_words, n=1, cutoff=FUZZY_CUTOFF)
            if close:
                entry = self._forward[close[0]]
                if entry["id"] not in seen:
                    seen.add(entry["id"])
                    matches.append(Match(entry, close[0], "fuzzy"))
        return matches

    # -- reverse matching (a target language in) -------------------------
    def _reverse_exact(self, text: str) -> list[Match]:
        matches, seen = [], set()
        for entry, lang in self._reverse.get(text, []):
            if entry["id"] not in seen:
                seen.add(entry["id"])
                matches.append(Match(entry, text, "exact", lang))
        return matches

    def _reverse_fuzzy(self, text: str) -> list[Match]:
        if len(text) < MIN_FUZZY_LEN + 1:
            return []
        close = difflib.get_close_matches(text, self._reverse, n=1, cutoff=REVERSE_FUZZY_CUTOFF)
        if not close:
            return []
        matches, seen = [], set()
        for entry, lang in self._reverse[close[0]]:
            if entry["id"] not in seen:
                seen.add(entry["id"])
                matches.append(Match(entry, close[0], "fuzzy", lang))
        return matches

    # -- public API ------------------------------------------------------
    def find(self, text: str) -> list[Match]:
        """Forward lookup only: exact, then phrase, then fuzzy."""
        text = normalise(text)
        if not text:
            return []
        return (self._forward_exact(text)
                or self._forward_phrases(text)
                or self._forward_fuzzy(text))

    def matches_in(self, text: str) -> list[Match]:
        """Glossary terms that appear in the text (exact or inside a sentence; never fuzzy guesses)."""
        text = normalise(text)
        if not text:
            return []
        return self._forward_exact(text) or self._forward_phrases(text)

    def find_reverse(self, text: str) -> list[Match]:
        """Reverse lookup only: the text is in French, Spanish, etc."""
        text = normalise(text)
        if not text:
            return []
        return self._reverse_exact(text) or self._reverse_fuzzy(text)

    def lookup(self, text: str) -> tuple[str, list[Match]]:
        """Best answer in both directions. Returns ("forward" | "reverse" | "none", matches).

        Exact hits in either direction beat fuzzy guesses, so typing the Spanish word
        "Hospital" is recognised as Spanish instead of being fuzzy-matched to "hospitali".
        """
        text = normalise(text)
        if not text:
            return "none", []
        for direction, finder in (
            ("forward", self._forward_exact),
            ("reverse", self._reverse_exact),
            ("forward", self._forward_phrases),
            ("forward", self._forward_fuzzy),
            ("reverse", self._reverse_fuzzy),
        ):
            matches = finder(text)
            if matches:
                return direction, matches
        return "none", []
