"""Adaptive engine — one step of the diagnostic. Pure: compute knowledge, pick the
next question (or finish). The API layer records the answer event; everything here is
recomputed from the event log, so the same events always yield the same next step.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from mentoros.assessment.question_bank import Question, load_bank
from mentoros.assessment.selector import estimate_theta, level_for_theta, select_next
from mentoros.assessment.session import asked_count_by_skill, asked_ids
from mentoros.assessment.stop import MAX_PER_SKILL, should_stop
from mentoros.curriculum import Curriculum
from mentoros.events import Event
from mentoros.knowledge import build_knowledge, estimate_cefr

# Order skills are assessed in (any skill not listed comes after, alphabetically).
_SKILL_ORDER = {"grammar": 0, "vocabulary": 1, "reading": 2, "listening": 3, "speaking": 4, "writing": 5}


def skills_in(bank: tuple[Question, ...]) -> list[str]:
    return sorted({q.skill for q in bank}, key=lambda s: (_SKILL_ORDER.get(s, 99), s))


@dataclass
class AssessmentStep:
    done: bool
    question: dict | None        # next question (public view, no answer key) or None
    asked_count: int
    skill: str | None            # which skill the current question belongs to
    levels: dict                 # per-skill CEFR estimate from each skill's staircase (θ)
    cefr: str | None             # overall CEFR projection from mastered topics (may lag θ)
    knowledge: list[dict]        # per-topic mastery/confidence snapshot (carries skill)

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
    per_skill = asked_count_by_skill(events, bank)
    skills = skills_in(bank)

    # Each skill is measured separately (its own staircase).
    levels = {s: level_for_theta(estimate_theta(events, bank, s)) for s in skills}

    nxt: Question | None = None
    current_skill: str | None = None
    for s in skills:
        if per_skill.get(s, 0) >= MAX_PER_SKILL:
            continue
        cand = select_next(bank, knowledge, asked, estimate_theta(events, bank, s), s, review_topics)
        if cand is not None:
            nxt, current_skill = cand, s
            break

    done = should_stop(len(asked), nxt)
    return AssessmentStep(
        done=done,
        question=None if done or nxt is None else nxt.public(),
        asked_count=len(asked),
        skill=current_skill,
        levels=levels,
        cefr=estimate_cefr(knowledge, curriculum),
        knowledge=[k.to_dict() for k in knowledge.values()],
    )
