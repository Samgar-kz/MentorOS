"""Question Bank — static, curated assessment items.

A question is an item with a known topic, CEFR and a single correct choice. Content
lives in ``data/assessment/`` as versioned JSON (easy to move to a separate content
repo later). ``difficulty`` is set by hand; ``discrimination``/``guess`` (IRT) come
later (Psychometrics v5) and are intentionally absent here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "assessment" / "grammar.json"
)


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

    def public(self) -> dict:
        """What the client may see — never the answer key."""
        return {
            "id": self.id,
            "skill": self.skill,
            "topic": self.topic,
            "cefr": self.cefr,
            "question": self.question,
            "choices": list(self.choices),
        }


def _validate(bank: tuple[Question, ...]) -> None:
    ids = [q.id for q in bank]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate question id in bank")
    for q in bank:
        if not (0 <= q.answer < len(q.choices)):
            raise ValueError(f"{q.id}: answer index {q.answer} out of range")
        if len(q.choices) < 2:
            raise ValueError(f"{q.id}: needs at least two choices")


@lru_cache(maxsize=None)
def load_bank(path: str | None = None) -> tuple[Question, ...]:
    """Load and validate the question bank (cached — it is static content)."""
    p = Path(path) if path else DEFAULT_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    bank = tuple(
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
        )
        for q in data["questions"]
    )
    _validate(bank)
    return bank


def by_id(bank: tuple[Question, ...]) -> dict[str, Question]:
    return {q.id: q for q in bank}
