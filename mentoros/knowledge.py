"""Knowledge Projection — the math model at the core of MentorOS (Rule 6).

For every topic we compute TWO numbers, never stored, always folded from events:

  - **mastery**    — how well the student knows it   (Beta-Binomial posterior mean)
  - **confidence** — how sure *we* are of that mastery (1 - posterior_std / prior_std)

These are different on purpose. A couple of right answers give HIGH mastery but LOW
confidence (tiny sample). Many answers narrow the interval, so confidence rises —
whether the verdict is "knows it" or "doesn't". CEFR is then just
``estimate_cefr(knowledge)``: a projection of the knowledge graph, not a stored goal
(Rule 3). The model is subject-agnostic — swap TOEFL for GRE and only the graph changes.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from mentoros.curriculum import CEFR_ORDER, Curriculum
from mentoros.events import GRAMMAR_QUESTION, PLACEMENT_PASSED, Event

# Uniform prior: before any evidence, mastery is 0.5 and confidence is 0.
PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0
# A self-reported placement is moderate evidence — worth this many pseudo-correct
# answers. Real (wrong) answers can always override it, so placement is self-correcting.
PLACEMENT_PSEUDO = 6.0
# "Known" = mastery this high AND this much certainty. Both knobs are tunable.
MASTERY_THRESHOLD = 0.75
CONFIDENCE_THRESHOLD = 0.6
# A CEFR band counts as reached when this fraction of topics up to it are known.
CEFR_REACHED_FRACTION = 0.8

_PRIOR_STD = math.sqrt(
    (PRIOR_ALPHA * PRIOR_BETA)
    / ((PRIOR_ALPHA + PRIOR_BETA) ** 2 * (PRIOR_ALPHA + PRIOR_BETA + 1))
)


def _beta_stats(successes: float, failures: float) -> tuple[float, float]:
    """Posterior mean and standard deviation of Beta(α₀+s, β₀+f)."""
    a = PRIOR_ALPHA + successes
    b = PRIOR_BETA + failures
    mean = a / (a + b)
    std = math.sqrt((a * b) / ((a + b) ** 2 * (a + b + 1)))
    return mean, std


@dataclass
class TopicKnowledge:
    topic: str
    mastery: float          # posterior mean P(correct)
    confidence: float       # 0 (no data) .. 1 (very sure)
    sample_size: int        # real answers (placement pseudo-observations excluded)
    correct: int
    last_seen: float | None
    known: bool             # mastery & confidence both over threshold

    def to_dict(self) -> dict:
        return asdict(self)


def build_knowledge(
    events: list[Event], curriculum: Curriculum
) -> dict[str, TopicKnowledge]:
    """Fold answers + placements into per-topic (mastery, confidence). Pure & deterministic."""
    succ = {t.id: 0.0 for t in curriculum.topics}
    fail = {t.id: 0.0 for t in curriculum.topics}
    n = {t.id: 0 for t in curriculum.topics}
    correct = {t.id: 0 for t in curriculum.topics}
    last_seen: dict[str, float | None] = {t.id: None for t in curriculum.topics}

    for e in sorted(events, key=lambda e: (e.ts, e.id)):
        if e.type == GRAMMAR_QUESTION:
            topic = e.payload.get("topic")
            if topic in succ:
                ok = bool(e.payload.get("correct", False))
                succ[topic] += 1.0 if ok else 0.0
                fail[topic] += 0.0 if ok else 1.0
                n[topic] += 1
                correct[topic] += int(ok)
                last_seen[topic] = e.ts
        elif e.type == PLACEMENT_PASSED:
            topic = e.payload.get("topic")
            if topic in succ:
                # Knowing a topic implies knowing its foundations.
                for tid in curriculum.with_prerequisites(topic):
                    succ[tid] += PLACEMENT_PSEUDO
                    if last_seen[tid] is None:
                        last_seen[tid] = e.ts

    out: dict[str, TopicKnowledge] = {}
    for t in curriculum.topics:
        mean, std = _beta_stats(succ[t.id], fail[t.id])
        confidence = max(0.0, min(1.0, 1.0 - std / _PRIOR_STD))
        known = mean >= MASTERY_THRESHOLD and confidence >= CONFIDENCE_THRESHOLD
        out[t.id] = TopicKnowledge(
            topic=t.id,
            mastery=round(mean, 3),
            confidence=round(confidence, 3),
            sample_size=n[t.id],
            correct=correct[t.id],
            last_seen=last_seen[t.id],
            known=known,
        )
    return out


def estimate_cefr(
    knowledge: dict[str, TopicKnowledge], curriculum: Curriculum
) -> str | None:
    """The overall CEFR level — a *projection* of the knowledge graph, never stored.
    The highest band where enough topics up to it are known (or None if not even A1)."""
    known_ids = {k.topic for k in knowledge.values() if k.known}
    best: str | None = None
    for level in sorted(CEFR_ORDER, key=lambda lv: CEFR_ORDER[lv]):
        upto = [t for t in curriculum.topics if t.level_rank <= CEFR_ORDER[level]]
        if not upto:
            continue
        frac = sum(1 for t in upto if t.id in known_ids) / len(upto)
        if frac >= CEFR_REACHED_FRACTION:
            best = level
    return best
