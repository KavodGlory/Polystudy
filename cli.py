#!/usr/bin/env python3
"""Command-line chat.   Run:  python3 cli.py

Type any word or sentence in any of the nine languages and it is translated into the
current target language (/to fr). Use /file to translate a PDF, TXT or MD file.

All the logic lives in Session.handle(), which takes one line and returns the reply as a
string. That keeps the interactive loop tiny and makes the whole CLI easy to test.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from translator import (LANGS, LANGUAGES, Chatbot, ClaudeClient, DocumentError, Glossary, TranslationError,
                        TranslationService, UnmatchedLog, format_text, make_flashcard, make_question,
                        resolve_language, resolve_source)
from translator.gemini_api import GeminiClient
from translator.documents import output_stem, write_html, write_txt
from translator.unmatched import DEFAULT_LOG_PATH

HELP = """Type a word, sentence or paragraph in any language and I translate it.

Languages: """ + ", ".join(f"{l.code} ({l.name})" for l in LANGUAGES.values()) + """

Commands:
  /to fr            translate INTO this language (code or name, e.g. /to japanese, /to sheng)
  /from sw          the language you are typing (default: auto = detect it)
  /langs            show the current settings
  /file report.pdf  translate a PDF, TXT or MD file (saves .txt and .html next to it)
  /define asante    glossary card: meaning, translations and tip for a Kenyan word
  /list [category]  list the glossary (see /categories)
  /categories       show the glossary categories
  /quiz             multiple-choice quiz from the glossary (answer 1-4, q to stop)
  /flash            flashcards from the glossary (Enter to flip, q to stop)
  /unmatched        glossary words people asked for that are missing
  /help, /quit"""


class Session:
    """One chat session: remembers the language pair and any quiz in progress."""

    def __init__(self, bot: Chatbot, service: TranslationService | None = None, target: str = "fr",
                 rng: random.Random | None = None, progress_out=None):
        self.bot = bot
        self.service = service
        self.glossary = bot.glossary
        self.source = "auto"
        self.target = target
        self.rng = rng or random.Random()
        self.progress_out = progress_out        # e.g. a function that prints "3/10"
        self.done = False
        self._quiz = None
        self._flash = None
        self._score = [0, 0]

    # ------------------------------------------------------------ entry point
    def handle(self, line: str) -> str:
        line = line.strip()
        if self._quiz is not None:
            return self._quiz_answer(line)
        if self._flash is not None:
            return self._flash_next(line)
        if not line:
            return ""
        if line.startswith("/"):
            return self._command(line)
        return self._translate(line)

    # ------------------------------------------------------------ translating
    def _name(self, code: str) -> str:
        return LANGUAGES[code].name if code in LANGUAGES else "unknown language"

    def _translate(self, text: str) -> str:
        if self.service is None:
            reply = self.bot.respond(text)
            langs = list(LANGS) if self.target == "all" else [self.target]
            return format_text(reply, langs)
        try:
            r = self.service.translate_text(text, self.target, None if self.source == "auto" else self.source)
        except (ValueError, TranslationError) as exc:
            return str(exc)
        lines = [f"[{self._name(r.source)} -> {self._name(r.target)}]", r.text]
        lines += [f"(note: {n})" for n in r.notes]
        for t in r.tips:
            flag = "  [!] not yet checked by a native speaker" if t["needs_review"] else ""
            lines.append(f"(glossary: '{t['term']}' = {t['meaning']}. {t['note']}{flag})")
        return "\n".join(lines)

    def _file(self, arg: str) -> str:
        path = Path(arg.strip().strip("\"'")).expanduser()
        if not arg.strip():
            return "Use /file <path>, e.g. /file report.pdf"
        try:
            data = path.read_bytes()
        except OSError as exc:
            return f"Could not read the file: {exc.strerror or exc}"
        try:
            result = self.service.translate_document(
                data, path.name, self.target, None if self.source == "auto" else self.source, self.progress_out)
            stem = path.with_name(output_stem(path.name, self.target))
            txt, html_ = stem.with_suffix(stem.suffix + ".txt"), stem.with_suffix(stem.suffix + ".html")
            txt.write_bytes(write_txt(result.text))
            html_.write_bytes(write_html(result.text, self.target, stem.name))
        except (DocumentError, TranslationError) as exc:
            return str(exc)
        except OSError as exc:
            return f"Translated, but could not save the result: {exc.strerror or exc}"
        notes = "".join(f"\n(note: {n})" for n in result.notes)
        return (f"Translated {path.name} ({self._name(result.source)} -> {self._name(result.target)}, "
                f"{result.chunks} piece{'s' if result.chunks != 1 else ''}).\nSaved:\n  {txt}\n  {html_}{notes}")

    # --------------------------------------------------------------- commands
    def _command(self, line: str) -> str:
        cmd, _, arg = line.partition(" ")
        cmd = cmd.lower()
        if cmd in ("/quit", "/exit"):
            self.done = True
            return "Kwaheri!"
        if cmd == "/help":
            return HELP
        if cmd == "/langs":
            src = "auto-detect" if self.source == "auto" else self._name(self.source)
            target = "Arabic and all other languages" if self.target == "all" else self._name(self.target)
            return f"Translating from {src} into {target}."
        if cmd == "/lang" and self.service is None:
            arg = arg.strip().lower()
            if arg == "all":
                self.target = "all"
                return "OK, translating into all languages."
            code = resolve_language(arg)
            if not code or code not in LANGS:
                return "Use /lang with a language, or /lang all."
            self.target = code
            return f"OK, translating into {self._name(code)}."
        if cmd == "/to":
            code = resolve_language(arg)
            if not code:
                return "Unknown language. Try: " + ", ".join(LANGUAGES)
            self.target = code
            return f"OK, translating into {self._name(code)}."
        if cmd == "/from":
            code = resolve_source(arg)
            if not code:
                return "Unknown language. Try auto or: " + ", ".join(LANGUAGES)
            self.source = code
            return "OK, detecting the language automatically." if code == "auto" else f"OK, the original is {self._name(code)}."
        if cmd == "/file":
            return self._file(arg)
        if cmd == "/define":
            reply = self.bot.respond(arg)
            return format_text(reply, list(LANGS)) if arg.strip() else "Use /define <word>, e.g. /define asante"
        if cmd == "/categories":
            return ", ".join(self.glossary.categories())
        if cmd == "/list":
            return self._list(arg.strip().lower())
        if cmd == "/unmatched":
            return self._unmatched()
        if cmd == "/quiz":
            self._score = [0, 0]
            return "Quiz time! Answer with 1-4, or q to stop.\n\n" + self._next_question()
        if cmd == "/flash":
            return "Flashcards. Press Enter to flip a card, q to stop.\n\n" + self._next_card()
        return f"Unknown command {cmd}. Type /help."

    def _list(self, category: str) -> str:
        entries = [e for e in self.glossary.entries if not category or e["category"] == category]
        if not entries:
            return f"No category '{category}'. Try /categories."
        return "\n".join(
            f"- {e['aliases'][0]} ({e['category']}, {e['register']}): {e['meaning']}"
            + ("  [!]" if e["needs_review"] else "") for e in entries
        ) + "\n\n[!] = translation not yet checked by a native speaker"

    def _unmatched(self) -> str:
        log = self.bot.unmatched_log
        if log is None:
            return "Logging is switched off."
        common = log.most_common(10)
        if not common:
            return "Nothing logged yet."
        return "Glossary lookups with no answer (most asked first):\n" + "\n".join(f"  {n}x  {t}" for t, n in common)

    # ------------------------------------------------------------------- quiz
    def _glossary_lang(self) -> str:
        return self.target if self.target in LANGS else self.rng.choice(list(LANGS))

    def _next_question(self) -> str:
        self._quiz = make_question(self.glossary, self._glossary_lang(), self.rng)
        q = self._quiz
        opts = "\n".join(f"  {i}. {text}" for i, text in enumerate(q.options, 1))
        return f"What is '{q.term}' in {LANGS[q.lang]}?\n{opts}"

    def _quiz_answer(self, line: str) -> str:
        q = self._quiz
        if line.lower() in ("q", "/stop", "/quit"):
            self._quiz = None
            return f"Quiz over. Score: {self._score[0]}/{self._score[1]}."
        if not line.isdigit() or not 1 <= int(line) <= len(q.options):
            return f"Please answer with a number from 1 to {len(q.options)}, or q to stop."
        self._score[1] += 1
        if q.is_correct(int(line) - 1):
            self._score[0] += 1
            verdict = "Correct!"
        else:
            verdict = f"Not quite. The answer was: {q.options[q.answer_index]}"
        return f"{verdict}  ('{q.term}' = {q.meaning})\n\n" + self._next_question()

    # -------------------------------------------------------------- flashcards
    def _next_card(self) -> str:
        self._flash = make_flashcard(self.glossary, self.rng)
        return f"[ {self._flash['aliases'][0]} ]"

    def _flash_next(self, line: str) -> str:
        card = self._flash
        if line.lower() in ("q", "/stop", "/quit"):
            self._flash = None
            return "Flashcards stopped."
        langs = [self.target] if self.target in LANGS else list(LANGS)
        back = [f"  Meaning : {card['meaning']}"]
        back += [f"  {LANGS[c]:<20}: {card['translations'][c]}" for c in langs]
        if card["note"]:
            back.append(f"  Tip     : {card['note']}")
        return "\n".join(back) + "\n\n" + self._next_card()


# ---------------------------------------------------------------------- main
def _pick_client(use_ai: bool) -> "ClaudeClient | GeminiClient | None":
    """Return the best available AI client, or None for offline mode.

    Priority:
      1. GEMINI_API_KEY   → Google Gemini (free tier at aistudio.google.com)
      2. ANTHROPIC_API_KEY → Claude (paid, console.anthropic.com)
      3. None             → offline glossary-only mode
    """
    import os
    if not use_ai:
        return None
    if os.environ.get("GEMINI_API_KEY"):
        return GeminiClient()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ClaudeClient()
    return None


def build_session(use_ai: bool = True, log_path=DEFAULT_LOG_PATH) -> Session:
    glossary = Glossary.load()
    client = _pick_client(use_ai)
    service = TranslationService(glossary, client)
    bot = Chatbot(glossary, UnmatchedLog(log_path) if log_path else None)

    def progress(done: int, total: int) -> None:
        print(f"\r  translating piece {done}/{total}", end="", file=sys.stderr, flush=True)
        if done == total:
            print(file=sys.stderr)

    return Session(bot, service, progress_out=progress)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Karibu Translator: command-line chat")
    parser.add_argument("--no-ai", action="store_true", help="never call an AI API (glossary only)")
    parser.add_argument("--no-log", action="store_true", help="do not save unmatched glossary lookups")
    parser.add_argument("--log", default=str(DEFAULT_LOG_PATH), help="where to save unmatched lookups")
    args = parser.parse_args(argv)

    try:   # make Arabic / Japanese / Chinese print correctly on Windows terminals
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    session = build_session(not args.no_ai, None if args.no_log else args.log)
    import os
    if session.service.ai_available:
        if os.environ.get("GEMINI_API_KEY"):
            engine_name = "Gemini (Google)"
        else:
            engine_name = "Claude (Anthropic)"
        ai = f"on [{engine_name}]"
    else:
        ai = "OFF - set GEMINI_API_KEY (free) or ANTHROPIC_API_KEY to translate sentences and files"
    print(f"Karibu! Type anything to translate it into {LANGUAGES[session.target].name}. /help for commands.\n[AI translation: {ai}]\n")
    while not session.done:
        try:
            line = input("you> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        reply = session.handle(line)
        if reply:
            print(reply + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
