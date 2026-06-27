"""Events — the only source of truth (Rules 1 & 2).

Everything MentorOS knows is derived from an append-only, immutable log of events.
Nothing here mutates or deletes history: the store exposes `append` and `read_all`
and deliberately nothing else. The profile, vocabulary mastery, review schedule —
all of it is *computed* from these events (see `profile.build_profile`), never
stored as a primary source (Rule 3).
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

# --- V1 event types --------------------------------------------------------- #
# Adding new types later is fine; changing what an existing type *means* is not
# (the whole history must stay replayable forever).
WORD_ADDED = "word_added"            # payload: {word, meaning, difficulty}
WORD_ANSWERED = "word_answered"      # payload: {word, correct: bool, latency_ms: int}
SESSION_STARTED = "session_started"  # payload: {session_id}
SESSION_FINISHED = "session_finished"  # payload: {session_id, duration_s}

V1_EVENT_TYPES = frozenset(
    {WORD_ADDED, WORD_ANSWERED, SESSION_STARTED, SESSION_FINISHED}
)

# --- V2 event types (Planner) ----------------------------------------------- #
GRAMMAR_QUESTION = "grammar_question"  # payload: {topic, correct: bool} — folds into topic mastery
PLACEMENT_PASSED = "placement_passed"  # payload: {topic, level} — diagnostic placement: a known topic
ASSESSMENT_COMPLETED = "assessment_completed"  # payload: {} — pure onboarding marker (no stored level)


@dataclass(frozen=True)
class Event:
    """One immutable fact. `frozen=True` enforces Rule 2 in the type system."""

    type: str
    payload: dict
    ts: float       # event time, unix epoch seconds
    id: str         # stable unique id (also the tiebreaker for deterministic replay)

    @staticmethod
    def new(type: str, payload: dict | None = None, ts: float | None = None) -> "Event":
        return Event(
            type=type,
            payload=dict(payload or {}),
            ts=time.time() if ts is None else ts,
            id=uuid.uuid4().hex,
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def from_json(line: str) -> "Event":
        d = json.loads(line)
        return Event(type=d["type"], payload=d["payload"], ts=d["ts"], id=d["id"])


class EventStore:
    """Append-only event log backed by JSONL (one event per line).

    Append-only by construction: there is no update or delete. To "change" state,
    you record another event.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, event: Event) -> Event:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(event.to_json() + "\n")
        return event

    def record(self, type: str, payload: dict | None = None, ts: float | None = None) -> Event:
        """Convenience: build an event and append it in one call."""
        return self.append(Event.new(type, payload, ts))

    def read_all(self) -> list[Event]:
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as f:
            return [Event.from_json(line) for line in f if line.strip()]
