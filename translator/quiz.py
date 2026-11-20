"""Quiz and flashcards built from the glossary.

Multiple choice: "What is 'asante' in French?" with four French options.
Flashcard:       show the Swahili/Sheng term, then reveal meaning and translations.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .core import Glossary


@dataclass(frozen=True)
class QuizQuestion:
    entry_id: str
    term: str            # what the student is asked about, e.g. "asante"
    meaning: str         # shown after answering
    lang: str            # language code the options are written in
    options: list[str]
    answer_index: int

    def is_correct(self, index: int) -> bool:
        return index == self.answer_index


def make_question(glossary: Glossary, lang: str, rng: random.Random | None = None,
                  n_options: int = 4, category: str | None = None) -> QuizQuestion:
    """Pick a random entry and build a multiple-choice question about it."""
    rng = rng or random.Random()
    pool = [e for e in glossary.entries if category in (None, e["category"])]
    if not pool:
        raise ValueError(f"No entries in category {category!r}")
    entry = rng.choice(pool)
    correct = entry["translations"][lang]

    # distractors: other entries' translations, preferring the same category
    others = [e for e in glossary.entries if e["id"] != entry["id"]]
    rng.shuffle(others)
    others.sort(key=lambda e: e["category"] != entry["category"])   # same category first (stable)
    distractors: list[str] = []
    for e in others:
        text = e["translations"][lang]
        if text != correct and text not in distractors:
            distractors.append(text)
        if len(distractors) == n_options - 1:
            break
    if len(distractors) < n_options - 1:
        raise ValueError("Glossary is too small to build a quiz question")

    options = distractors + [correct]
    rng.shuffle(options)
    return QuizQuestion(entry["id"], entry["aliases"][0], entry["meaning"], lang,
                        options, options.index(correct))


def make_flashcard(glossary: Glossary, rng: random.Random | None = None,
                   category: str | None = None) -> dict:
    """Return a random glossary entry to use as a flashcard."""
    rng = rng or random.Random()
    pool = [e for e in glossary.entries if category in (None, e["category"])]
    if not pool:
        raise ValueError(f"No entries in category {category!r}")
    return rng.choice(pool)
