"""Selector — narrowing (CAT-lite). Pure, deterministic, still no item-level IRT.

Instead of spreading one question per topic, we estimate the student's ability θ on the
CEFR scale from their answers (an up/down staircase), then ask the most informative
unasked question NEAR θ, skipping topics we're already confident about. Early answers
move θ fast (placement); later answers hone in (narrowing), deepening the band's topics
until they lock. So a single run concentrates on the student's level and a level emerges.
"""

from __future__ import annotations

import math
import random

from mentoros.assessment.question_bank import Question
from mentoros.assessment.stop import CONFIDENCE_STOP
from mentoros.curriculum import CEFR_ORDER
from mentoros.events import GRAMMAR_QUESTION, Event
from mentoros.knowledge import TopicKnowledge

START_THETA = 2.0     # begin at B1 (rank 2) — the middle of the scale
NEAR_BAND = 1.0       # only ask questions within this many CEFR levels of θ
REVIEW_BONUS = 0.3
_ABILITY_STEP = 1.0   # base learning rate (in CEFR levels) for the θ update

_RANK_TO_LEVEL = {v: k for k, v in CEFR_ORDER.items()}


def _rank(cefr: str) -> int:
    return CEFR_ORDER.get(cefr, 2)


def estimate_theta(
    events: list[Event], bank: tuple[Question, ...], skill: str | None = None
) -> float:
    """Ability θ on the CEFR scale (0=A1 .. 5=C2), calibrated to item difficulty.

    Online Rasch/Elo update: for each answered item of difficulty d, the expected chance
    of a correct answer is ``p = 1/(1+exp(-(θ-d)))``; θ moves by ``k*(correct-p)`` with a
    step that shrinks as evidence accrues. So a *correct easy* item barely raises θ, a
    *correct hard* item raises it, and a *wrong easy* item drops it sharply — θ converges
    to the level where the student is ~50%, instead of shooting to the ceiling on a streak
    of easy wins. (The old blind ±step staircase overestimated level — see code review.)"""
    by = {q.id: q for q in bank}
    theta = START_THETA
    n = 0
    for e in sorted(events, key=lambda e: (e.ts, e.id)):
        if e.type != GRAMMAR_QUESTION:
            continue
        q = by.get(e.payload.get("question"))
        if q is None or (skill is not None and q.skill != skill):
            continue
        d = _rank(q.cefr)
        p = 1.0 / (1.0 + math.exp(-(theta - d)))           # expected P(correct) | ability vs difficulty
        observed = 1.0 if bool(e.payload.get("correct")) else 0.0
        k = max(0.3, _ABILITY_STEP / (1.0 + 0.3 * n))      # learning rate decays with evidence
        theta = max(0.0, min(5.0, theta + k * (observed - p)))
        n += 1
    return theta


def level_for_theta(theta: float, cap_rank: int = 5) -> str:
    """CEFR label for an ability estimate. FLOOR, not round: θ converges to the ~50%
    point which sits between the student's band and the next, so rounding inflated the
    label (a true-B2 with θ 3.55 was shown C1). Capped at what the bank can test."""
    return _RANK_TO_LEVEL[max(0, min(cap_rank, math.floor(theta)))]


def theta_se(events: list[Event], bank: tuple[Question, ...], skill: str, theta: float) -> float:
    """Standard error of the θ estimate (Rasch/Fisher information): SE = 1/sqrt(Σ p(1-p))
    over the answered items of this skill. Small SE = we're confident about the level, so
    the test can stop — this is what makes the length adaptive (stop when sure), not fixed."""
    by = {q.id: q for q in bank}
    info = 0.0
    for e in events:
        if e.type != GRAMMAR_QUESTION:
            continue
        q = by.get(e.payload.get("question"))
        if q is None or q.skill != skill:
            continue
        p = 1.0 / (1.0 + math.exp(-(theta - _rank(q.cefr))))
        info += p * (1.0 - p)
    return float("inf") if info <= 0.0 else 1.0 / math.sqrt(info)


def select_next(
    bank: tuple[Question, ...],
    knowledge: dict[str, TopicKnowledge],
    asked_ids: set[str],
    theta: float,
    skill: str | None = None,
    review_topics: tuple[str, ...] = (),
) -> Question | None:
    """The most informative unasked question near θ (within ``skill`` if given), or None
    once that band is settled."""
    review = set(review_topics)
    scored: list[tuple[float, Question]] = []
    for q in bank:
        if q.id in asked_ids:
            continue
        if skill is not None and q.skill != skill:
            continue
        k = knowledge.get(q.topic)
        if k and k.confidence >= CONFIDENCE_STOP:
            continue  # already sure about this topic
        dist = abs(_rank(q.cefr) - theta)
        if dist > NEAR_BAND:
            continue  # too far from the estimated level to be informative right now
        uncertainty = 1.0 - (k.confidence if k else 0.0)
        review_priority = REVIEW_BONUS if q.topic in review else 0.0
        scored.append((-dist + uncertainty + review_priority, q))
    if not scored:
        return None
    # Pick randomly among the near-best so two runs aren't identical (variety without
    # losing the "near the level" guarantee). Honesty is unaffected — items are curated.
    top = max(s for s, _ in scored)
    pool = [q for s, q in scored if s >= top - 0.15]
    return random.choice(pool)
