"""The translation service: one place that turns (text or file, source, target) into a translation.

Order of preference
    1. Claude API  - any sentence, any of the 9 languages in either direction, plus files.
    2. Glossary    - offline fallback when there is no API key: single known words/phrases only.

The glossary is no longer the limit on what can be translated. It now has two smaller jobs:
    * hints   : verified Kenyan slang entries are shown to Claude so it gets Sheng right
    * tips    : short cultural notes shown next to a translation
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .core import LANGS as GLOSSARY_LANGS
from .core import Glossary
from .documents import (CHUNK_CHARS, SUPPORTED_EXTENSIONS, chunk_text, decode_text, extract_pdf_text)
from .errors import DocumentError, NoEngineError, TranslationError, TruncatedError
from .languages import LANGUAGES

_KNOWN_SOURCES = (None, "en", "sw", "sheng")      # sources for which glossary hints make sense
MAX_PDF_BYTES = 32 * 1024 * 1024                  # Claude's limit for a PDF sent directly
MAX_SCAN_PAGES = 100

SHENG_NOTE = ("Sheng is informal and changes by area and generation. Have a Kenyan speaker check "
              "important Sheng translations.")
OFFLINE_NOTE = ("AI translation is switched off (no ANTHROPIC_API_KEY), so this comes from the "
                "verified glossary only.")


@dataclass
class TranslationResult:
    text: str
    source: str               # language code of the original ("other" if unknown)
    target: str
    engine: str               # "claude" or "glossary"
    notes: list[str] = field(default_factory=list)
    tips: list[dict] = field(default_factory=list)


@dataclass
class PreparedDocument:
    """A file that has been read and split, ready to translate."""
    filename: str
    kind: str                 # "text", "pdf-text" or "pdf-scan"
    chunks: list[tuple[str, str]]
    characters: int
    pages: int | None = None
    pdf_bytes: bytes | None = None


@dataclass
class DocumentResult:
    text: str
    source: str
    target: str
    filename: str
    chunks: int
    characters: int
    notes: list[str] = field(default_factory=list)


def _entry_language(entry: dict) -> str:
    return {"Sheng": "sheng", "Kenyan English": "en"}.get(entry["source_language"], "sw")


class TranslationService:
    def __init__(self, glossary: Glossary, client=None, chunk_chars: int = CHUNK_CHARS,
                 max_text_chars: int | None = None, max_doc_chars: int | None = None):
        self.glossary = glossary
        self.client = client
        self.chunk_chars = chunk_chars
        self.max_text_chars = max_text_chars or int(os.environ.get("KARIBU_MAX_TEXT_CHARS", 20_000))
        self.max_doc_chars = max_doc_chars or int(os.environ.get("KARIBU_MAX_DOC_CHARS", 150_000))

    @property
    def ai_available(self) -> bool:
        return self.client is not None and self.client.available

    # ----------------------------------------------------------- validation
    @staticmethod
    def _check_languages(target: str, source: str | None) -> str | None:
        if target not in LANGUAGES:
            raise ValueError(f"Unknown target language: {target!r}")
        if source in (None, "auto"):
            return None
        if source not in LANGUAGES:
            raise ValueError(f"Unknown source language: {source!r}")
        return source

    # ------------------------------------------------------- glossary helpers
    def _hints(self, chunk: str, target: str, source: str | None) -> list[str]:
        """Verified Kenyan-slang entries found in this chunk, phrased for Claude."""
        if source not in _KNOWN_SOURCES:
            return []
        hints: list[str] = []
        for m in self.glossary.matches_in(chunk):
            e = m.entry
            if e["register"] != "slang" and e["source_language"] not in ("Sheng", "Kenyan English"):
                continue
            line = f'"{m.term}" ({e["source_language"]}): {e["meaning"]}'
            if target in GLOSSARY_LANGS:
                line += f'; verified {LANGUAGES[target].name}: {e["translations"][target]}'
            hints.append(line)
        return hints[:15]

    def _tips(self, text: str, source: str | None) -> list[dict]:
        """Short glossary notes to show beside a short input."""
        if source not in _KNOWN_SOURCES or len(text) > 200:
            return []
        return [{"term": m.entry["aliases"][0], "meaning": m.entry["meaning"], "note": m.entry["note"],
                 "source_language": m.entry["source_language"], "register": m.entry["register"],
                 "needs_review": m.entry["needs_review"]}
                for m in self.glossary.matches_in(text)][:5]

    @staticmethod
    def _notes(source: str, target: str) -> list[str]:
        return [SHENG_NOTE] if "sheng" in (source, target) else []

    # ------------------------------------------------------------ core loop
    def _translate_one(self, text: str, target: str, source: str | None, hints: list[str],
                       depth: int = 0) -> tuple[str, str]:
        """Translate one chunk. If Claude runs out of room, split the chunk and retry the halves."""
        try:
            return self.client.translate(text, target, source, hints)
        except TruncatedError:
            if depth >= 2 or len(text) < 400:
                raise
            halves = chunk_text(text, len(text) // 2 + 1)
            out, detected = "", "other"
            for part, sep in halves:
                translated, det = self._translate_one(part, target, source, hints, depth + 1)
                out += translated + sep
                if detected == "other":
                    detected = det
            return out.strip(), detected

    def _translate_chunks(self, chunks: list[tuple[str, str]], target: str, source: str | None,
                          progress=None) -> tuple[str, str]:
        detected: str | None = None
        parts: list[str] = []
        for i, (chunk, sep) in enumerate(chunks, 1):
            known = source or (detected if detected not in (None, "other") else None)
            translated, det = self._translate_one(chunk, target, known, self._hints(chunk, target, known))
            if not source and detected in (None, "other"):
                detected = det                       # remember the language from the first useful chunk
            parts.append(translated + sep)
            if progress:
                progress(i, len(chunks))
        return "".join(parts).strip(), source or detected or "other"

    # ----------------------------------------------------------------- text
    def translate_text(self, text: str, target: str, source: str | None = None) -> TranslationResult:
        """Translate a word, sentence or several paragraphs."""
        text = (text or "").strip()
        if not text:
            raise ValueError("Please type some text to translate.")
        source = self._check_languages(target, source)
        if len(text) > self.max_text_chars:
            raise ValueError(f"That is too long for the text box ({len(text):,} characters; limit "
                             f"{self.max_text_chars:,}). Upload it as a file instead.")
        tips = self._tips(text, source)
        if not self.ai_available:
            return self._offline(text, target, tips)
        translated, detected = self._translate_chunks(chunk_text(text, self.chunk_chars), target, source)
        return TranslationResult(translated, detected, target, "claude", self._notes(detected, target), tips)

    def _offline(self, text: str, target: str, tips: list[dict]) -> TranslationResult:
        """No API key: answer only if the whole input is a single glossary entry."""
        direction, matches = self.glossary.lookup(text)
        if len(matches) == 1 and matches[0].kind in ("exact", "fuzzy"):
            m = matches[0]
            e = m.entry
            if direction == "forward":
                if target in GLOSSARY_LANGS:
                    return TranslationResult(e["translations"][target], _entry_language(e), target, "glossary",
                                             [OFFLINE_NOTE], tips)
                if target == "en":
                    return TranslationResult(e["meaning"], _entry_language(e), target, "glossary",
                                             [OFFLINE_NOTE], tips)
            elif direction == "reverse" and target in ("sw", "en"):
                answer = e["aliases"][0] if target == "sw" else e["meaning"]
                return TranslationResult(answer, m.lang or "other", target, "glossary", [OFFLINE_NOTE], tips)
        raise NoEngineError(
            "Translating sentences and files needs an AI API key. "
            "Set GEMINI_API_KEY (free at aistudio.google.com) or ANTHROPIC_API_KEY and restart. "
            "Without a key only single words and phrases from the glossary work.")

    # ------------------------------------------------------------ documents
    def prepare_document(self, data: bytes, filename: str) -> PreparedDocument:
        """Read a file and split it into chunks. Raises DocumentError for unusable files."""
        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise DocumentError(f"Unsupported file type '{ext or filename}'. Use: {', '.join(SUPPORTED_EXTENSIONS)}")
        if not data:
            raise DocumentError("The file is empty.")

        pages = None
        if ext == ".pdf":
            text, pages = extract_pdf_text(data)
            if len(text.strip()) < 50 * max(pages, 1):          # almost no text: probably a scan
                if len(data) > MAX_PDF_BYTES:
                    raise DocumentError("This scanned PDF is over 32 MB, which is too large to read.")
                if pages > MAX_SCAN_PAGES:
                    raise DocumentError(f"Scanned PDFs are limited to {MAX_SCAN_PAGES} pages.")
                return PreparedDocument(filename, "pdf-scan", [], 0, pages, data)
            kind = "pdf-text"
        else:
            text, kind = decode_text(data), "text"

        text = text.strip()
        if not text:
            raise DocumentError("There is no text in this file.")
        if len(text) > self.max_doc_chars:
            raise DocumentError(f"This document is too long ({len(text):,} characters; limit "
                                f"{self.max_doc_chars:,}). Split it, or raise KARIBU_MAX_DOC_CHARS.")
        return PreparedDocument(filename, kind, chunk_text(text, self.chunk_chars), len(text), pages)

    def translate_prepared(self, doc: PreparedDocument, target: str, source: str | None = None,
                           progress=None) -> DocumentResult:
        """Translate a prepared file. `progress(done, total)` is called after each chunk."""
        source = self._check_languages(target, source)
        if not self.ai_available:
            raise NoEngineError("Translating files needs an AI API key. "
                                "Set GEMINI_API_KEY (free at aistudio.google.com) or ANTHROPIC_API_KEY and restart.")
        if doc.kind == "pdf-scan":
            if progress:
                progress(0, 1)
            try:
                text, detected = self.client.translate_pdf(doc.pdf_bytes, target, source)
            except TruncatedError as exc:
                raise TranslationError("This scanned PDF has too much text to translate in one go. "
                                       "Split it into smaller PDFs.") from exc
            if progress:
                progress(1, 1)
            return DocumentResult(text.strip(), source or detected, target, doc.filename, 1, len(text),
                                  self._notes(source or detected, target))
        text, detected = self._translate_chunks(doc.chunks, target, source, progress)
        return DocumentResult(text, detected, target, doc.filename, len(doc.chunks), doc.characters,
                              self._notes(detected, target))

    def translate_document(self, data: bytes, filename: str, target: str, source: str | None = None,
                           progress=None) -> DocumentResult:
        """Read, split and translate a file in one call."""
        return self.translate_prepared(self.prepare_document(data, filename), target, source, progress)
