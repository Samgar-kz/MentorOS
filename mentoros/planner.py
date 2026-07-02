"""Planner v2 — decide what to learn today. Pure functions, no stored plan (Rule 5).

The plan, the per-topic states and the next action are ALL recomputed from
``events + curriculum_graph`` every time, exactly like the review queue. Nothing here
is persisted, and the LLM is never consulted: the Teacher (``ai.py``) only *teaches*
the topic the planner has already chosen. The plan "adapts" not because we edit it,
but because it never existed as stored state.

    events ─► build_knowledge ─► states_from_knowledge ─┐
    events ─► build_profile ────────────────────────────┼─► build_plan ─► next_action ─► lesson
    graph  ─────────────────────────────────────────────┘
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field, replace

from mentoros.curriculum import CEFR_ORDER, Curriculum, load_curriculum
from mentoros.events import ASSESSMENT_COMPLETED, Event
from mentoros.knowledge import TopicKnowledge, build_knowledge, estimate_cefr
from mentoros.profile import Profile, build_profile
from mentoros.review import WordState, build_review_queue

FOCUS_LIMIT = 3         # how many next topics to surface as the focus list

STATUS_LOCKED = "locked"        # a prerequisite is not mastered yet
STATUS_AVAILABLE = "available"  # unlocked, not started
STATUS_LEARNING = "learning"    # unlocked, in progress, not mastered
STATUS_MASTERED = "mastered"
STATUS_FADING = "fading"        # mastered, but unrevisited so long it needs review

_LEARNABLE = (STATUS_LEARNING, STATUS_AVAILABLE)
_FOCUS_RANK = {STATUS_LEARNING: 0, STATUS_AVAILABLE: 1}


@dataclass
class TopicState:
    """Computed state of one curriculum topic — never stored. A thin view over the
    Knowledge Projection (mastery + confidence) plus its place in the graph."""

    id: str
    title: str
    level: str
    skill: str
    status: str
    mastery: float
    confidence: float
    sample_size: int
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
    cefr_level: str | None               # confirmed CEFR (projection of mastered topics)
    review_due: int
    review_words: list[str]
    focus: list[dict]                    # next learnable topics (TopicState dicts)
    next_action: dict
    topics_total: int
    topics_mastered: int
    topics_locked: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def is_onboarded(events: list[Event]) -> bool:
    """Whether the level check has been done — computed from events. Onboarding is a
    fact (``assessment_completed``), a pure marker; no level is stored anywhere. The
    actual level is always the CEFR *projection* of the knowledge model."""
    return any(e.type == ASSESSMENT_COMPLETED for e in events)


def states_from_knowledge(
    knowledge: dict[str, TopicKnowledge], curriculum: Curriculum
) -> dict[str, TopicState]:
    """Derive each topic's status from the Knowledge Projection + prerequisites:
    a topic is *mastered* when it is known (mastery & confidence high); otherwise it is
    *available*/*learning* once its prerequisites are known, else *locked*."""
    known = {tid: k.known for tid, k in knowledge.items()}
    states: dict[str, TopicState] = {}
    for topic in curriculum.topics:
        k = knowledge[topic.id]
        if k.known:
            status = STATUS_MASTERED
        elif all(known.get(r, False) for r in topic.requires):
            status = STATUS_LEARNING if k.sample_size > 0 else STATUS_AVAILABLE
        else:
            status = STATUS_LOCKED
        states[topic.id] = TopicState(
            id=topic.id,
            title=topic.title,
            level=topic.level,
            skill=topic.skill,
            status=status,
            mastery=k.mastery,
            confidence=k.confidence,
            sample_size=k.sample_size,
            requires=list(topic.requires),
        )
    return states


def build_topic_states(
    events: list[Event], curriculum: Curriculum, now: float | None = None
) -> dict[str, TopicState]:
    """Per-topic status, computed from the Knowledge Projection. Pure & deterministic.
    Passing ``now`` applies the forgetting curve (stale topics fade)."""
    return states_from_knowledge(build_knowledge(events, curriculum, now), curriculum)


_SKILL_PREF = {"grammar": 0, "vocabulary": 1, "reading": 2, "listening": 3}


def focus_topics(curriculum: Curriculum, states: dict[str, TopicState]) -> list[TopicState]:
    """The learnable frontier, interleaved across skills so practice stays balanced and
    Reading/Listening get woven into lessons (not buried behind all of Grammar). Within a
    skill: in-progress first, then newly-unlocked, by CEFR level then curriculum order.
    The least-practiced skill leads, so under-assessed skills surface soon."""
    learnable = [s for s in states.values() if s.status in _LEARNABLE]
    learnable.sort(
        key=lambda s: (_FOCUS_RANK[s.status], CEFR_ORDER.get(s.level, 99), curriculum.order[s.id])
    )

    by_skill: dict[str, list[TopicState]] = {}
    for s in learnable:
        by_skill.setdefault(s.skill, []).append(s)

    practice = {
        skill: sum(st.sample_size for st in states.values() if st.skill == skill)
        for skill in by_skill
    }
    skill_order = sorted(by_skill, key=lambda sk: (practice[sk], _SKILL_PREF.get(sk, 99), sk))

    # Round-robin: one topic from each skill per pass, least-practiced skill first.
    queues = [by_skill[sk] for sk in skill_order]
    out: list[TopicState] = []
    while any(queues):
        for q in queues:
            if q:
                out.append(q.pop(0))
    return out


def next_action(review_due: int, focus: list[TopicState]) -> Action:
    """The single most useful step right now: clear due reviews first (so knowledge
    doesn't decay), otherwise advance the next unlocked topic."""
    if review_due > 0:
        s = "s" if review_due != 1 else ""
        return Action("review", f"Review {review_due} due word{s}", count=review_due)
    if focus:
        top = focus[0]
        verb = (
            "Review" if top.status == STATUS_FADING
            else "Continue" if top.status == STATUS_LEARNING
            else "Start"
        )
        return Action("learn", f"{verb}: {top.title} ({top.level})", topic_id=top.id)
    return Action("done", "All caught up — add new words or material.")


def build_plan(
    curriculum: Curriculum,
    states: dict[str, TopicState],
    queue: list[WordState],
    now: float,
    onboarded: bool = False,
    cefr_level: str | None = None,
    fading: tuple[str, ...] = (),
) -> Plan:
    """Assemble today's plan from the computed pieces. Pure: no I/O, no stored state.
    ``fading`` topics (mastered but stale) lead the focus list — forgetting drives the
    QUEUE, never the student's rank."""
    focus = [replace(states[t], status=STATUS_FADING) for t in fading if t in states]
    focus += focus_topics(curriculum, states)
    action = next_action(len(queue), focus)
    return Plan(
        generated_ts=now,
        onboarded=onboarded,
        cefr_level=cefr_level,
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
    queue = build_review_queue(profile.vocabulary, now)
    # Rank, statuses and CEFR come from UNDECAYED knowledge — a break never demotes the
    # student. The forgetting curve only PRIORITIZES: topics whose fresh (decayed)
    # knowledge has faded are resurfaced for review at the head of the focus list.
    knowledge = build_knowledge(events, curriculum)
    decayed = build_knowledge(events, curriculum, now)
    states = states_from_knowledge(knowledge, curriculum)
    fading = tuple(tid for tid, k in knowledge.items() if k.known and not decayed[tid].known)
    onboarded = is_onboarded(events)
    cefr_level = estimate_cefr(knowledge, curriculum)  # CEFR is a projection, not stored
    return build_plan(curriculum, states, queue, now, onboarded, cefr_level, fading)
