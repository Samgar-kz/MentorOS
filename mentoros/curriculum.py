"""Curriculum graph — the static topic DAG the Planner walks (Planner v2).

This is the one genuinely new piece of *data* v2 needs: English topics from A1 to C1
and their prerequisites. It is static and versioned (like the vocabulary seed) — never
computed, never written at runtime. The planner reads it; it is the *map*, not the
*state*. What the student actually knows is still computed from events
(see ``planner.build_topic_states``). The graph never stores progress.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CEFR_ORDER = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5}

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "curriculum"


@dataclass(frozen=True)
class Topic:
    id: str
    title: str
    level: str                      # CEFR: A1..C2
    skill: str                      # "grammar" for now
    requires: tuple[str, ...]

    @property
    def level_rank(self) -> int:
        return CEFR_ORDER.get(self.level, 99)


class Curriculum:
    """A validated, acyclic graph of topics. Insertion order is the stable tiebreaker."""

    def __init__(self, topics: list[Topic]):
        self.topics = topics
        self.by_id = {t.id: t for t in topics}
        self.order = {t.id: i for i, t in enumerate(topics)}
        self._validate()

    def _validate(self) -> None:
        for t in self.topics:
            for r in t.requires:
                if r not in self.by_id:
                    raise ValueError(f"topic {t.id!r} requires unknown topic {r!r}")
        # Acyclicity via Kahn's algorithm (a cycle would make a topic unreachable).
        indeg = {t.id: len(set(t.requires)) for t in self.topics}
        dependents: dict[str, list[str]] = {t.id: [] for t in self.topics}
        for t in self.topics:
            for r in set(t.requires):
                dependents[r].append(t.id)
        ready = [tid for tid, d in indeg.items() if d == 0]
        seen = 0
        while ready:
            n = ready.pop()
            seen += 1
            for m in dependents[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
        if seen != len(self.topics):
            raise ValueError("curriculum graph has a cycle")

    def with_prerequisites(self, topic_id: str) -> set[str]:
        """A topic plus all of its transitive prerequisites. Knowing a topic implies
        knowing what it is built on — placement uses this to cover the foundations."""
        seen: set[str] = set()
        stack = [topic_id]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            t = self.by_id.get(n)
            if t:
                stack.extend(t.requires)
        return seen


@lru_cache(maxsize=None)
def load_curriculum(path: str | None = None) -> Curriculum:
    """Load and validate the curriculum graph (cached — it is static). With no path,
    merges every ``*.json`` under data/curriculum/ (grammar + vocabulary + reading + …),
    so adding a skill is just dropping in a content file."""
    files = [Path(path)] if path else sorted(DEFAULT_DIR.glob("*.json"))
    topics: list[Topic] = []
    for p in files:
        data = json.loads(p.read_text(encoding="utf-8"))
        for d in data["topics"]:
            topics.append(
                Topic(
                    id=d["id"],
                    title=d["title"],
                    level=d["level"],
                    skill=d.get("skill", "grammar"),
                    requires=tuple(d.get("requires", [])),
                )
            )
    return Curriculum(topics)
