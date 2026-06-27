"""Planner v2 — decide what to learn today. Pure functions, no stored plan (Rule 5).

The plan, the per-topic states and the next action are ALL recomputed from
``events + curriculum_graph`` every time, exactly like the review queue. Nothing here
is persisted, and the LLM is never consulted: the Teacher (``ai.py``) only *teaches*
the topic the planner has already chosen. The plan "adapts" not because we edit it,
but because it never existed as stored state.

    events ─► build_topic_states ─┐
    events ─► build_profile ──────┼─► build_plan ─► next_action ─► Today's lesson
    graph  ───────────────────────┘
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from mentoros.assess import LevelEstimate, assess
from mentoros.curriculum import CEFR_ORDER, Curriculum, load_curriculum
from mentoros.events import (
    ASSESSMENT_COMPLETED,
    GRAMMAR_QUESTION,
    PLACEMENT_PASSED,
    Event,
)
from mentoros.profile import Profile, build_profile
from mentoros.review import WordState, build_review_queue, next_box

MASTERED_TOPIC_BOX = 3  # consecutive correct answers that "master" a grammar topic
FOCUS_LIMIT = 3         # how many next topics to surface as the focus list

STATUS_LOCKED = "locked"        # a prerequisite is not mastered yet
STATUS_AVAILABLE = "available"  # unlocked, not started
STATUS_LEARNING = "learning"    # unlocked, in progress, not mastered
STATUS_MASTERED = "mastered"

_LEARNABLE = (STATUS_LEARNING, STATUS_AVAILABLE)
_FOCUS_RANK = {STATUS_LEARNING: 0, STATUS_AVAILABLE: 1}


@dataclass
class TopicState:
    """Computed state of one curriculum topic — never stored (folded from events)."""

    id: str
    title: str
    level: str
    status: str
    box: int
    answers: int
    correct: int
    accuracy: float
    requires: list[str]


@dataclass
class Action:
    kind: str                  # "review" | "learn" | "done"
    detail: str
    topic_id: str | None = None
    count: int = 0


@dataclass
class Plan:
    generated_ts: float
    onboarded: bool                      # has the student completed the level check?
    cefr_level: str | None               # CEFR level from the latest assessment (or None)
    level: dict                          # assess().to_dict() (vocabulary)
    review_due: int
    review_words: list[str]
    focus: list[dict]                    # next learnable topics (TopicState dicts)
    next_action: dict
    topics_total: int
    topics_mastered: int
    topics_locked: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def onboarding_state(events: list[Event]) -> tuple[bool, str | None]:
    """Whether the level check is done, and the level it found — computed from events.
    Onboarding is itself a fact (``assessment_completed``), not a stored flag (Rule 1)."""
    completed = [e for e in events if e.type == ASSESSMENT_COMPLETED]
    if not completed:
        return False, None
    last = max(completed, key=lambda e: (e.ts, e.id))
    return True, last.payload.get("level")


def build_topic_states(
    events: list[Event], curriculum: Curriculum, now: float | None = None
) -> dict[str, TopicState]:
    """Fold ``grammar_question`` events into per-topic Leitner state, then derive
    locked/available/learning/mastered from prerequisite mastery. Pure & deterministic."""
    tally = {t.id: {"box": 0, "answers": 0, "correct": 0} for t in curriculum.topics}
    # Replay in time order: a real answer moves the Leitner box; a placement marks a
    # known topic (and its foundations) as mastered. Order matters — a later wrong
    # answer on a placed topic resets its box, so placement is self-correcting.
    for e in sorted(events, key=lambda e: (e.ts, e.id)):
        if e.type == GRAMMAR_QUESTION:
            topic = e.payload.get("topic")
            if topic in tally:
                correct = bool(e.payload.get("correct", False))
                t = tally[topic]
                t["box"] = next_box(t["box"], correct)
                t["answers"] += 1
                t["correct"] += int(correct)
        elif e.type == PLACEMENT_PASSED:
            topic = e.payload.get("topic")
            if topic in tally:
                for tid in curriculum.with_prerequisites(topic):
                    tally[tid]["box"] = MASTERED_TOPIC_BOX  # placement: foundations covered

    mastered = {tid: tally[tid]["box"] >= MASTERED_TOPIC_BOX for tid in tally}

    states: dict[str, TopicState] = {}
    for topic in curriculum.topics:
        t = tally[topic.id]
        if mastered[topic.id]:
            status = STATUS_MASTERED
        elif all(mastered.get(r, False) for r in topic.requires):
            status = STATUS_LEARNING if t["answers"] > 0 else STATUS_AVAILABLE
        else:
            status = STATUS_LOCKED
        states[topic.id] = TopicState(
            id=topic.id,
            title=topic.title,
            level=topic.level,
            status=status,
            box=t["box"],
            answers=t["answers"],
            correct=t["correct"],
            accuracy=(t["correct"] / t["answers"]) if t["answers"] else 0.0,
            requires=list(topic.requires),
        )
    return states


def focus_topics(curriculum: Curriculum, states: dict[str, TopicState]) -> list[TopicState]:
    """The learnable frontier: in-progress topics first, then newly-unlocked ones,
    each ordered by CEFR level then curriculum order."""
    learnable = [s for s in states.values() if s.status in _LEARNABLE]
    learnable.sort(
        key=lambda s: (_FOCUS_RANK[s.status], CEFR_ORDER.get(s.level, 99), curriculum.order[s.id])
    )
    return learnable


def next_action(review_due: int, focus: list[TopicState]) -> Action:
    """The single most useful step right now: clear due reviews first (so knowledge
    doesn't decay), otherwise advance the next unlocked topic."""
    if review_due > 0:
        s = "s" if review_due != 1 else ""
        return Action("review", f"Review {review_due} due word{s}", count=review_due)
    if focus:
        top = focus[0]
        verb = "Continue" if top.status == STATUS_LEARNING else "Start"
        return Action("learn", f"{verb}: {top.title} ({top.level})", topic_id=top.id)
    return Action("done", "All caught up — add new words or material.")


def build_plan(
    curriculum: Curriculum,
    states: dict[str, TopicState],
    queue: list[WordState],
    level: LevelEstimate,
    now: float,
    onboarded: bool = False,
    cefr_level: str | None = None,
) -> Plan:
    """Assemble today's plan from the computed pieces. Pure: no I/O, no stored state."""
    focus = focus_topics(curriculum, states)
    action = next_action(len(queue), focus)
    return Plan(
        generated_ts=now,
        onboarded=onboarded,
        cefr_level=cefr_level,
        level=level.to_dict(),
        review_due=len(queue),
        review_words=[w.word for w in queue[:8]],
        focus=[asdict(s) for s in focus[:FOCUS_LIMIT]],
        next_action=asdict(action),
        topics_total=len(curriculum.topics),
        topics_mastered=sum(1 for s in states.values() if s.status == STATUS_MASTERED),
        topics_locked=sum(1 for s in states.values() if s.status == STATUS_LOCKED),
    )


def plan_today(
    events: list[Event], curriculum: Curriculum | None = None, now: float | None = None
) -> Plan:
    """Orchestrator: everything the daily plan needs, recomputed from the event log."""
    now = time.time() if now is None else now
    curriculum = curriculum or load_curriculum()
    profile = build_profile(events, now=now)
    level = assess(profile)
    queue = build_review_queue(profile.vocabulary, now)
    states = build_topic_states(events, curriculum, now)
    onboarded, cefr_level = onboarding_state(events)
    return build_plan(curriculum, states, queue, level, now, onboarded, cefr_level)
