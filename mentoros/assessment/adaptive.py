"""Adaptive engine — one step of the diagnostic. Pure: compute knowledge, pick the
next question (or finish). The API layer records the answer event; everything here is
recomputed from the event log, so the same events always yield the same next step.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from mentoros.assessment.question_bank import Question, load_bank
from mentoros.assessment.selector import select_next
from mentoros.assessment.session import asked_ids
from mentoros.assessment.stop import should_stop
from mentoros.curriculum import Curriculum
from mentoros.events import Event
from mentoros.knowledge import build_knowledge, estimate_cefr


@dataclass
class AssessmentStep:
    done: bool
    question: dict | None        # next question (public view, no answer key) or None
    asked_count: int
    cefr: str | None             # CEFR projection so far
    knowledge: list[dict]        # per-topic mastery/confidence snapshot

    def to_dict(self) -> dict:
        return asdict(self)


def next_step(
    events: list[Event],
    curriculum: Curriculum,
    bank: tuple[Question, ...] | None = None,
    review_topics: tuple[str, ...] = (),
) -> AssessmentStep:
    bank = bank if bank is not None else load_bank()
    knowledge = build_knowledge(events, curriculum)
    asked = asked_ids(events)
    nxt = select_next(bank, knowledge, asked, review_topics)
    done = should_stop(len(asked), nxt)
    return AssessmentStep(
        done=done,
        question=None if done or nxt is None else nxt.public(),
        asked_count=len(asked),
        cefr=estimate_cefr(knowledge, curriculum),
        knowledge=[k.to_dict() for k in knowledge.values()],
    )
