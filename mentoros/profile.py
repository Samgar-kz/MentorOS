"""build_profile — the heart of MentorOS (Rule 3: everything is computed).

The profile is a *projection* of the event log: replay every event in
deterministic order and fold it into the current learning state. The same events
always yield the same profile; the profile is never the source of truth and can be
thrown away and rebuilt at any time.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mentoros.events import (
    SESSION_FINISHED,
    SESSION_STARTED,
    WORD_ADDED,
    WORD_ANSWERED,
    Event,
)
from mentoros.review import WordState, build_review_queue


@dataclass
class SessionSummary:
    session_id: str
    started_ts: float
    duration_s: float | None  # None if the session was started but never finished


@dataclass
class Profile:
    generated_ts: float
    word_count: int
    mastered_count: int
    due_count: int
    total_answers: int
    accuracy: float                       # overall correct / answers
    vocabulary: list[WordState] = field(default_factory=list)
    sessions: list[SessionSummary] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def build_profile(events: list[Event], now: float | None = None) -> Profile:
    """Fold an event log into the current learning state. Pure & deterministic."""
    now = time.time() if now is None else now

    # Deterministic replay order: by event time, then id as a stable tiebreaker.
    ordered = sorted(events, key=lambda e: (e.ts, e.id))

    words: dict[str, WordState] = {}
    sessions: dict[str, SessionSummary] = {}

    for e in ordered:
        if e.type == WORD_ADDED:
            w = e.payload["word"]
            # First definition wins; re-adding the same word does not reset progress.
            if w not in words:
                words[w] = WordState(
                    word=w,
                    meaning=e.payload.get("meaning", ""),
                    difficulty=int(e.payload.get("difficulty", 1)),
                    box=0,
                    answers=0,
                    correct=0,
                    last_answered_ts=None,
                )

        elif e.type == WORD_ANSWERED:
            w = e.payload["word"]
            st = words.get(w)
            if st is None:
                # Answered before it was formally added — record it so no fact is lost.
                st = WordState(w, "", 1, 0, 0, 0, None)
                words[w] = st
            from mentoros.review import next_box  # local import avoids a cycle at top

            correct = bool(e.payload.get("correct", False))
            st.box = next_box(st.box, correct)
            st.answers += 1
            st.correct += int(correct)
            st.last_answered_ts = e.ts

        elif e.type == SESSION_STARTED:
            sid = e.payload.get("session_id", e.id)
            sessions.setdefault(sid, SessionSummary(sid, e.ts, None))

        elif e.type == SESSION_FINISHED:
            sid = e.payload.get("session_id", e.id)
            s = sessions.setdefault(sid, SessionSummary(sid, e.ts, None))
            s.duration_s = float(e.payload.get("duration_s", 0.0))
        # Unknown types (future V2/V3) are ignored by the V1 projection.

    vocab = list(words.values())
    total_answers = sum(w.answers for w in vocab)
    total_correct = sum(w.correct for w in vocab)

    return Profile(
        generated_ts=now,
        word_count=len(vocab),
        mastered_count=sum(1 for w in vocab if w.mastered),
        due_count=len(build_review_queue(vocab, now)),
        total_answers=total_answers,
        accuracy=(total_correct / total_answers) if total_answers else 0.0,
        vocabulary=sorted(vocab, key=lambda w: w.word),
        sessions=sorted(sessions.values(), key=lambda s: s.started_ts),
    )


def save_profile(profile: Profile, path: str | Path) -> None:
    """Persist the profile as a regenerable cache (NOT a source of truth)."""
    Path(path).write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
