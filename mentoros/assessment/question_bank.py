"""Question Bank — static, curated assessment items.

A question is an item with a known topic, CEFR and a single correct choice. Content
lives in ``data/assessment/`` as versioned JSON (easy to move to a separate content
repo later). ``difficulty`` is set by hand; ``discrimination``/``guess`` (IRT) come
later (Psychometrics v5) and are intentionally absent here.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# MENTOROS_DATA overrides the data root for non-editable installs.
_DATA = Path(os.environ.get("MENTOROS_DATA", Path(__file__).resolve().parent.parent.parent / "data"))
DEFAULT_DIR = _DATA / "assessment"   # Assessment Content: few, high-quality items (measuring)
LESSON_DIR = _DATA / "lessons"       # Lesson Content: many practice items (learning)


@dataclass(frozen=True)
class Question:
    id: str
    skill: str
    topic: str
    cefr: str
    difficulty: float
    question: str
    choices: tuple[str, ...]
    answer: int            # index into choices — server-side only, never sent to the client
    explanation: str
    script: str = ""       # spoken audio script (Listening); client speaks it, never shows it

    def public(self) -> dict:
        """What the client may see — never the answer key. Choices are shuffled
        deterministically (see ``display_form``) so the correct option isn't always first.
        For Listening, ``script`` is included so the browser can speak it (played, not shown)."""
        d = {
            "id": self.id,
            "skill": self.skill,
            "topic": self.topic,
            "cefr": self.cefr,
            "question": self.question,
            "choices": display_form(self)[0],
        }
        if self.script:
            d["script"] = self.script
        return d


def display_form(q: Question) -> tuple[list[str], int]:
    """Deterministically shuffle a question's choices (seeded by its id) and report where
    the correct answer landed. Same permutation every time, so the order is stable for the
    student and reproducible at grading — fixes "the answer is always option A"."""
    seed = int(hashlib.sha256(q.id.encode()).hexdigest(), 16) % (2**32)
    order = list(range(len(q.choices)))
    random.Random(seed).shuffle(order)
    return [q.choices[i] for i in order], order.index(q.answer)


def _validate(bank: tuple[Question, ...]) -> None:
    ids = [q.id for q in bank]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate question id in bank")
    for q in bank:
        if not (0 <= q.answer < len(q.choices)):
            raise ValueError(f"{q.id}: answer index {q.answer} out of range")
        if len(q.choices) < 2:
            raise ValueError(f"{q.id}: needs at least two choices")


def _read_file(p: Path) -> list[Question]:
    data = json.loads(p.read_text(encoding="utf-8"))
    return [
        Question(
            id=q["id"],
            skill=q.get("skill", "grammar"),
            topic=q["topic"],
            cefr=q["cefr"],
            difficulty=float(q.get("difficulty", 0.5)),
            question=q["question"],
            choices=tuple(q["choices"]),
            answer=int(q["answer"]),
            explanation=q.get("explanation", ""),
            script=q.get("script", ""),
        )
        for q in data["questions"]
    ]


@lru_cache(maxsize=None)
def load_bank(path: str | None = None) -> tuple[Question, ...]:
    """The **Assessment** bank — few, high-quality items used to *measure* (the adaptive
    test). With no path, merges every ``*.json`` under data/assessment/."""
    files = [Path(path)] if path else sorted(DEFAULT_DIR.glob("*.json"))
    bank = tuple(q for p in files for q in _read_file(p))
    _validate(bank)
    return bank


@lru_cache(maxsize=None)
def load_lesson_bank() -> tuple[Question, ...]:
    """The **Lesson** bank — many practice items used to *learn* (lessons), kept separate
    from the assessment bank. May be empty/thin; lessons fall back to the assessment bank
    for any topic the lesson bank doesn't cover yet."""
    if not LESSON_DIR.exists():
        return ()
    bank = tuple(q for p in sorted(LESSON_DIR.glob("*.json")) for q in _read_file(p))
    _validate(bank)
    return bank


def by_id(bank: tuple[Question, ...]) -> dict[str, Question]:
    return {q.id: q for q in bank}
