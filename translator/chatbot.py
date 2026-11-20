"""Glossary lookup bot (the learning/definition side of the project).

Full translation of sentences and files lives in service.py. This class is the glossary-only
engine used for definitions ("/define asante"): it shows the meaning, all six translations and
the cultural tip, and it logs phrases the glossary could not answer so you can add them later.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .core import Glossary, Match
from .unmatched import UnmatchedLog


@dataclass
class Reply:
    """status: "forward" (Swahili/English/Sheng in), "reverse" (a target language in) or "none"."""
    status: str
    query: str
    matches: list[Match] = field(default_factory=list)
    llm_text: str | None = None


class Chatbot:
    def __init__(self, glossary: Glossary, llm_or_log=None, unmatched_log: UnmatchedLog | None = None):
        self.glossary = glossary
        if isinstance(llm_or_log, UnmatchedLog):
            self.llm = None
            self.unmatched_log = llm_or_log
        else:
            self.llm = llm_or_log
            self.unmatched_log = unmatched_log

    def respond(self, text: str, languages: list[str] | None = None) -> Reply:
        query = text.strip()
        if not query:
            return Reply("none", "")
        direction, matches = self.glossary.lookup(query)
        if matches:
            return Reply(direction, query, matches)
        if self.llm is not None and getattr(self.llm, "available", True):
            answer = self.llm.translate(query, languages)
            if answer:
                if self.unmatched_log is not None:
                    self.unmatched_log.add(query, answered_by_llm=True)
                return Reply("llm", query, llm_text=answer)
        if self.unmatched_log is not None:       # remember the gap so it can be added later
            self.unmatched_log.add(query)
        return Reply("none", query)
