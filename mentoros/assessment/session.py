"""Session helpers — the assessment 'session' is event-sourced.

Which questions were already asked is derived from the ``grammar_question`` events
(each carries the question id), so no separate session state is stored (Rule 3). The
only writes are the answer events themselves; everything else is recomputed.
"""

from __future__ import annotations

from mentoros.assessment.question_bank import Question
from mentoros.events import GRAMMAR_QUESTION, Event


def asked_ids(events: list[Event]) -> set[str]:
    """Question ids already answered, read straight from the event log."""
    return {
        e.payload["question"]
        for e in events
        if e.type == GRAMMAR_QUESTION and e.payload.get("question")
    }


def grade(question: Question, choice: int) -> bool:
    """Grade a chosen option against the answer key (server-side only)."""
    return choice == question.answer
