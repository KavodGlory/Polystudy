"""Formats glossary replies as text for the terminal."""
from __future__ import annotations

from .chatbot import Reply
from .core import LANGS, Match

NO_MATCH_MESSAGE = "That is not in the glossary. Try a shorter phrase, or type /list to see what is in it."


def _format_forward(m: Match, langs: list[str], query: str) -> list[str]:
    e = m.entry
    lines = [f"'{m.term}'  [{e['source_language']}, {e['register']}, {e['category']}]"]
    if m.kind == "fuzzy":
        lines.append(f"  (closest match to what you typed: '{query}')")
    lines.append(f"  Meaning : {e['meaning']}")
    for code in langs:
        lines.append(f"  {LANGS[code]:<20}: {e['translations'][code]}")
    return lines


def _format_reverse(m: Match, query: str) -> list[str]:
    e = m.entry
    lines = [f"'{query}' looks like {LANGS[m.lang]}."]
    if m.kind == "fuzzy":
        lines.append("  (closest match to what you typed)")
    lines.append(f"  Say     : {e['aliases'][0]}  [{e['source_language']}, {e['register']}]")
    lines.append(f"  Meaning : {e['meaning']}")
    return lines


def format_text(reply: Reply, langs: list[str]) -> str:
    """Human-readable glossary card for the command line."""
    if reply.status == "llm":
        return f"{reply.llm_text}\n\nAI-generated, NOT from the verified glossary. Double-check before relying on it."
    if reply.status == "none":
        return NO_MATCH_MESSAGE if reply.query else ""
    blocks = []
    for m in reply.matches:
        lines = (_format_reverse(m, reply.query) if reply.status == "reverse"
                 else _format_forward(m, langs, reply.query))
        e = m.entry
        if e["note"]:
            lines.append(f"  Tip     : {e['note']}")
        if e["needs_review"]:
            lines.append("  [!] Translation not yet checked by a native speaker.")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
