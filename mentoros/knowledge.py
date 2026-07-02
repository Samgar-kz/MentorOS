"""Knowledge Projection — the math model at the core of MentorOS (Rule 6).

For every topic we compute TWO numbers, never stored, always folded from events:

  - **mastery**    — how well the student knows it   (Beta-Binomial posterior mean)
  - **confidence** — how sure *we* are of that mastery (1 - width of the 90% credible interval)

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
# Forgetting curve: evidence loses half its weight every this many days without revisiting.
FORGET_HALF_LIFE_DAYS = 30.0
# A repeat answer to the SAME question is weak evidence (it measures memory of the item,
# not knowledge of the topic) — retries and re-runs of a small bank must not inflate mastery.
REPEAT_WEIGHT = 0.3

def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    maxit, eps, fpmin = 200, 1e-9, 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a,b) = P(Beta(a,b) <= x). Pure Python, no deps."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_bt = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log(1.0 - x)
    )
    bt = math.exp(ln_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _beta_quantile(p: float, a: float, b: float) -> float:
    """Inverse CDF of Beta(a,b) by bisection."""
    lo, hi = 0.0, 1.0
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        if betainc(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _mean_and_confidence(successes: float, failures: float) -> tuple[float, float]:
    """Posterior mean (mastery) and certainty = 1 − width of the 90% credible interval of
    Beta(α₀+s, β₀+f). An honest interval, not the old hand-tuned std ratio: narrow
    interval → high confidence, regardless of whether mastery is high or low."""
    a = PRIOR_ALPHA + successes
    b = PRIOR_BETA + failures
    mean = a / (a + b)
    if successes == 0 and failures == 0:
        return mean, 0.0  # no evidence -> no certainty
    width = _beta_quantile(0.95, a, b) - _beta_quantile(0.05, a, b)
    return mean, max(0.0, min(1.0, 1.0 - width))


@dataclass
class TopicKnowledge:
    topic: str
    skill: str              # grammar | vocabulary | reading | …
    mastery: float          # posterior mean P(correct)
    confidence: float       # 0 (no data) .. 1 (very sure)
    sample_size: int        # real answers (placement pseudo-observations excluded)
    correct: int
    last_seen: float | None
    known: bool             # mastery & confidence both over threshold

    def to_dict(self) -> dict:
        return asdict(self)


def build_knowledge(
    events: list[Event], curriculum: Curriculum, now: float | None = None
) -> dict[str, TopicKnowledge]:
    """Fold answers + placements into per-topic (mastery, confidence). Pure & deterministic.

    With ``now`` given, older evidence is down-weighted by a forgetting curve (half-life
    ``FORGET_HALF_LIFE_DAYS``): a topic answered correctly long ago but not revisited
    slowly reverts toward the prior — mastery fades and the topic resurfaces. With
    ``now=None`` there is no decay (core unit tests use the undecayed form)."""
    succ = {t.id: 0.0 for t in curriculum.topics}
    fail = {t.id: 0.0 for t in curriculum.topics}
    n = {t.id: 0 for t in curriculum.topics}
    correct = {t.id: 0 for t in curriculum.topics}
    last_seen: dict[str, float | None] = {t.id: None for t in curriculum.topics}
    half_life = FORGET_HALF_LIFE_DAYS * 86400.0

    seen_qids: set[str] = set()
    for e in sorted(events, key=lambda e: (e.ts, e.id)):
        w = 0.5 ** (max(0.0, now - e.ts) / half_life) if now is not None else 1.0
        if e.type == GRAMMAR_QUESTION:
            topic = e.payload.get("topic")
            if topic in succ:
                ok = bool(e.payload.get("correct", False))
                # Re-answering a known item (retry after a hint, re-running a small bank)
                # is weak evidence — down-weight it so mastery can't be farmed.
                qid = e.payload.get("question")
                rw = REPEAT_WEIGHT if (qid and qid in seen_qids) else 1.0
                if qid:
                    seen_qids.add(qid)
                succ[topic] += rw * w if ok else 0.0
                fail[topic] += 0.0 if ok else rw * w
                n[topic] += 1
                correct[topic] += int(ok)
                last_seen[topic] = e.ts
        elif e.type == PLACEMENT_PASSED:
            topic = e.payload.get("topic")
            if topic in succ:
                # Knowing a topic implies knowing its foundations. Placement is
                # IDEMPOTENT (max, not +=): many placed topics sharing a prerequisite
                # must not pile up pseudo-evidence that real answers can't overturn.
                for tid in curriculum.with_prerequisites(topic):
                    succ[tid] = max(succ[tid], PLACEMENT_PSEUDO * w)
                    if last_seen[tid] is None:
                        last_seen[tid] = e.ts

    out: dict[str, TopicKnowledge] = {}
    for t in curriculum.topics:
        mean, confidence = _mean_and_confidence(succ[t.id], fail[t.id])
        known = mean >= MASTERY_THRESHOLD and confidence >= CONFIDENCE_THRESHOLD
        out[t.id] = TopicKnowledge(
            topic=t.id,
            skill=t.skill,
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
    max_rank = max((t.level_rank for t in curriculum.topics), default=0)  # don't report above what exists
    best: str | None = None
    for level in sorted(CEFR_ORDER, key=lambda lv: CEFR_ORDER[lv]):
        if CEFR_ORDER[level] > max_rank:
            continue  # no topics at this level (e.g. no C2 content) -> never report it
        upto = [t for t in curriculum.topics if t.level_rank <= CEFR_ORDER[level]]
        if not upto:
            continue
        frac = sum(1 for t in upto if t.id in known_ids) / len(upto)
        if frac >= CEFR_REACHED_FRACTION:
            best = level
    return best
