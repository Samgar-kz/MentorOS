"""Session helpers — the assessment 'session' is event-sourced.

Which questions were already asked is derived from the ``grammar_question`` events
(each carries the question id), so no separate session state is stored (Rule 3). The
only writes are the answer events themselves; everything else is recomputed.
"""

from __future__ import annotations

from mentoros.assessment.question_bank import Question, display_form
from mentoros.events import GRAMMAR_QUESTION, Event


def asked_ids(events: list[Event]) -> set[str]:
    """Question ids already answered, read straight from the event log."""
    return {
        e.payload["question"]
        for e in events
        if e.type == GRAMMAR_QUESTION and e.payload.get("question")
    }


def asked_count_by_skill(events: list[Event], bank: tuple[Question, ...]) -> dict[str, int]:
    """How many questions have been answered per skill (from the event log)."""
    by = {q.id: q for q in bank}
    counts: dict[str, int] = {}
    for qid in asked_ids(events):
        q = by.get(qid)
        if q is not None:
            counts[q.skill] = counts.get(q.skill, 0) + 1
    return counts


def grade(question: Question, choice: int) -> bool:
    """Grade a chosen option (an index into the *shuffled* choices the client saw) against
    the answer — using the same deterministic permutation as ``public()``."""
    return choice == display_form(question)[1]
