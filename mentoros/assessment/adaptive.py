"""Adaptive engine — one step of the diagnostic. Pure: compute knowledge, pick the
next question (or finish). The API layer records the answer event; everything here is
recomputed from the event log, so the same events always yield the same next step.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from mentoros.assessment.question_bank import Question, load_bank
from mentoros.assessment.selector import estimate_theta, level_for_theta, select_next, theta_se
from mentoros.assessment.session import asked_count_by_skill, asked_ids
from mentoros.assessment.stop import MAX_PER_SKILL, MIN_PER_SKILL, SE_STOP, should_stop
from mentoros.curriculum import CEFR_ORDER, Curriculum
from mentoros.events import Event
from mentoros.knowledge import build_knowledge, estimate_cefr


def bank_cap(bank: tuple[Question, ...], skill: str) -> int:
    """Highest CEFR rank the bank can actually test for a skill — the level ceiling we
    are allowed to report (no items above it = can't verify above it)."""
    ranks = [CEFR_ORDER[q.cefr] for q in bank if q.skill == skill and q.cefr in CEFR_ORDER]
    return max(ranks) if ranks else 5

# Order skills are assessed in (any skill not listed comes after, alphabetically).
_SKILL_ORDER = {"grammar": 0, "vocabulary": 1, "reading": 2, "listening": 3, "speaking": 4, "writing": 5}

# Day-1 onboarding stays short (~Grammar + Vocabulary, ~35-45 min); the other skills are
# woven into early lessons instead (continuous assessment, Rule 6) — so users start
# learning sooner rather than sitting through a 4-hour test.
ONBOARDING_SKILLS = ("grammar", "vocabulary")


def skills_in(bank: tuple[Question, ...]) -> list[str]:
    return sorted({q.skill for q in bank}, key=lambda s: (_SKILL_ORDER.get(s, 99), s))


@dataclass
class AssessmentStep:
    done: bool
    question: dict | None        # next question (public view, no answer key) or None
    asked_count: int
    skill: str | None            # which skill the current question belongs to
    levels: dict                 # per-skill CEFR estimate from each skill's staircase (θ)
    overall: str | None          # working level = floored mean θ across tested skills
    cefr: str | None             # confirmed level (mastered topics) — may lag `overall`
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
    # Onboarding measures only the short Day-1 skills; the rest come through lessons.
    skills = [s for s in skills_in(bank) if s in ONBOARDING_SKILLS]

    # Each skill is measured separately (its own staircase), capped at the bank's ceiling.
    thetas = {s: estimate_theta(events, bank, s) for s in skills}
    levels = {s: level_for_theta(thetas[s], bank_cap(bank, s)) for s in skills}

    # Adaptive stop: keep asking a skill until we're confident (θ standard error small) —
    # variable length, not a fixed count — bounded by MIN/MAX per skill as safety.
    nxt: Question | None = None
    current_skill: str | None = None
    for s in skills:
        asked_s = per_skill.get(s, 0)
        if asked_s >= MAX_PER_SKILL:
            continue
        if asked_s >= MIN_PER_SKILL and theta_se(events, bank, s, thetas[s]) < SE_STOP:
            continue  # confident enough about this skill's level
        cand = select_next(bank, knowledge, asked, thetas[s], s, review_topics)
        if cand is not None:
            nxt, current_skill = cand, s
            break

    done = should_stop(len(asked), nxt)
    overall = (
        level_for_theta(sum(thetas.values()) / len(thetas), max(bank_cap(bank, s) for s in skills))
        if skills else None
    )
    return AssessmentStep(
        done=done,
        question=None if done or nxt is None else nxt.public(),
        asked_count=len(asked),
        skill=current_skill,
        levels=levels,
        overall=overall,
        cefr=estimate_cefr(knowledge, curriculum),
        knowledge=[k.to_dict() for k in knowledge.values()],
    )
