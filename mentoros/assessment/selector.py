"""Selector — choose the next question. Pure, deterministic, no IRT/θ.

Score = uncertainty (probe what we're unsure of) + coverage (touch every topic once
first) + review (small nudge for due topics). Pick the max; among ties, ask the easier,
less-seen question first. A topic we're already very confident about is dropped entirely
(per-topic stop, see stop.CONFIDENCE_STOP).
"""

from __future__ import annotations

from mentoros.assessment.question_bank import Question
from mentoros.assessment.stop import CONFIDENCE_STOP
from mentoros.knowledge import TopicKnowledge

COVERAGE_BONUS = 1.0     # strongly prefer a topic we haven't probed at all yet
REVIEW_BONUS = 0.3       # small nudge for topics that are due for review


def _score(q: Question, k: TopicKnowledge | None, review: set[str]) -> float:
    uncertainty = 1.0 - (k.confidence if k else 0.0)
    coverage = COVERAGE_BONUS if (k is None or k.sample_size == 0) else 0.0
    review_priority = REVIEW_BONUS if q.topic in review else 0.0
    return uncertainty + coverage + review_priority


def select_next(
    bank: tuple[Question, ...],
    knowledge: dict[str, TopicKnowledge],
    asked_ids: set[str],
    review_topics: tuple[str, ...] = (),
) -> Question | None:
    """The most informative unasked question, or None if nothing useful remains."""
    review = set(review_topics)
    best: Question | None = None
    best_key = None
    for q in bank:
        if q.id in asked_ids:
            continue
        k = knowledge.get(q.topic)
        if k and k.confidence >= CONFIDENCE_STOP:
            continue  # we're already sure about this topic — stop probing it
        score = _score(q, k, review)
        seen = k.sample_size if k else 0
        # Higher score first; then less-probed topic; then easier question; then id.
        key = (score, -seen, -q.difficulty, q.id)
        if best_key is None or key > best_key:
            best_key = key
            best = q
    return best
