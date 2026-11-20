"""Saves phrases the glossary could not answer, so you can review them and grow the glossary.

The log is a JSON Lines file: one JSON object per line, easy to open, grep or load into a
spreadsheet. Example line:
    {"time": "2026-11-09T10:15:00+00:00", "text": "nimechoka", "answered_by_llm": false}
"""
from __future__ import annotations

import json
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "unmatched.jsonl"
MAX_TEXT_LENGTH = 500


class UnmatchedLog:
    def __init__(self, path: str | Path = DEFAULT_LOG_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()   # the web server can handle two requests at once

    def add(self, text: str, answered_by_llm: bool = False) -> None:
        record = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "text": text[:MAX_TEXT_LENGTH],
            "answered_by_llm": answered_by_llm,
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def most_common(self, n: int = 20) -> list[tuple[str, int]]:
        """The phrases people ask for most often that you do not cover yet."""
        counts = Counter(r["text"].strip().lower() for r in self.read())
        return counts.most_common(n)
