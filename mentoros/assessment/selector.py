"""Selector — narrowing (CAT-lite). Pure, deterministic, still no item-level IRT.

Instead of spreading one question per topic, we estimate the student's ability θ on the
CEFR scale from their answers (an up/down staircase), then ask the most informative
unasked question NEAR θ, skipping topics we're already confident about. Early answers
move θ fast (placement); later answers hone in (narrowing), deepening the band's topics
until they lock. So a single run concentrates on the student's level and a level emerges.
"""

from __future__ import annotations

from mentoros.assessment.question_bank import Question
from mentoros.assessment.stop import CONFIDENCE_STOP
from mentoros.curriculum import CEFR_ORDER
from mentoros.events import GRAMMAR_QUESTION, Event
from mentoros.knowledge import TopicKnowledge

START_THETA = 2.0     # begin at B1 (rank 2) — the middle of the scale
NEAR_BAND = 1.0       # only ask questions within this many CEFR levels of θ
REVIEW_BONUS = 0.3

_RANK_TO_LEVEL = {v: k for k, v in CEFR_ORDER.items()}


def _rank(cefr: str) -> int:
    return CEFR_ORDER.get(cefr, 2)


def estimate_theta(
    events: list[Event], bank: tuple[Question, ...], skill: str | None = None
) -> float:
    """Ability on the CEFR scale (0=A1 .. 5=C2) from answered questions — an up/down
    staircase with a shrinking step, so it converges to the student's level. With a
    ``skill`` it estimates that skill alone (each skill is measured separately)."""
    by = {q.id: q for q in bank}
    theta = START_THETA
    i = 0
    for e in sorted(events, key=lambda e: (e.ts, e.id)):
        if e.type != GRAMMAR_QUESTION:
            continue
        q = by.get(e.payload.get("question"))
        if q is None or (skill is not None and q.skill != skill):
            continue
        step = max(0.4, 1.5 / (1 + 0.4 * i))
        theta += step if bool(e.payload.get("correct")) else -step
        theta = max(0.0, min(5.0, theta))
        i += 1
    return theta


def level_for_theta(theta: float) -> str:
    return _RANK_TO_LEVEL[max(0, min(5, round(theta)))]


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
    best: Question | None = None
    best_key = None
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
        score = -dist + uncertainty + review_priority
        seen = k.sample_size if k else 0
        key = (score, -seen, -q.difficulty, q.id)
        if best_key is None or key > best_key:
            best_key = key
            best = q
    return best
