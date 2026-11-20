"""The nine languages the chatbot can translate between, in any direction.

English, Swahili, Sheng, Arabic, French, Japanese, Spanish, Chinese (Simplified), German.
Pick any one as the source (or let Claude detect it) and any other as the target.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    name: str          # shown in menus
    native: str        # the language's own name
    prompt_name: str   # how we name it to Claude
    html_lang: str     # value for the HTML lang attribute (lets browsers choose fonts)
    rtl: bool = False  # written right to left?


LANGUAGES: dict[str, Language] = {l.code: l for l in [
    Language("en", "English", "English", "English", "en"),
    Language("sw", "Swahili", "Kiswahili", "Swahili (Kiswahili)", "sw"),
    Language("sheng", "Sheng", "Sheng", "Sheng (Nairobi street slang)", "sw"),
    Language("ar", "Arabic", "العربية", "Arabic", "ar", True),
    Language("fr", "French", "Français", "French", "fr"),
    Language("ja", "Japanese", "日本語", "Japanese", "ja"),
    Language("es", "Spanish", "Español", "Spanish", "es"),
    Language("zh", "Chinese (Simplified)", "简体中文", "Simplified Chinese", "zh-Hans"),
    Language("de", "German", "Deutsch", "German", "de"),
]}

_ALIASES = {
    "kiswahili": "sw", "swahili": "sw", "kiingereza": "en", "english": "en",
    "sheng": "sheng", "kenyan slang": "sheng", "slang": "sheng",
    "arabic": "ar", "french": "fr", "japanese": "ja", "spanish": "es",
    "chinese": "zh", "mandarin": "zh", "simplified chinese": "zh", "zh-cn": "zh", "zh-hans": "zh",
    "chinese (simplified)": "zh", "german": "de",
}


def resolve_language(arg: str | None) -> str | None:
    """'fr', 'French', 'kenyan slang' ... -> language code, or None if not understood."""
    if not arg:
        return None
    key = " ".join(str(arg).strip().lower().replace("_", "-").split())
    if key in LANGUAGES:
        return key
    return _ALIASES.get(key)


def resolve_source(arg: str | None) -> str | None:
    """Like resolve_language but also accepts 'auto' (detect the language)."""
    if arg is None or str(arg).strip().lower() in ("", "auto", "detect", "auto-detect"):
        return "auto"
    return resolve_language(arg)


def language_list() -> list[dict]:
    """The languages as plain dicts (for JSON and templates)."""
    return [{"code": l.code, "name": l.name, "native": l.native, "dir": "rtl" if l.rtl else "ltr",
             "html_lang": l.html_lang} for l in LANGUAGES.values()]
