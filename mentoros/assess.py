"""assess — a level estimate computed from answer history (Rule 5: computed, not stored).

This is the smallest honest slice of the future Planner v2 ``assess(events)``. It does
NOT let the model declare a level (Rule 4): the level is a pure projection of the words
the student has actually answered, grouped by difficulty. Like the review queue, it is
recomputed on every read and never persisted.

The seed list is "TOEFL academic", so a word's ``difficulty`` is a proxy for how
rare/academic it is — not a certified CEFR test. The UI says so; we report what the
answers actually show, never a number "from the model's head" (Rule 1).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from mentoros.profile import Profile

# Difficulty tier -> human label (ascending difficulty).
TIER_LABELS = {1: "Core", 2: "Academic", 3: "Advanced"}
MIN_ANSWERS_PER_TIER = 5  # distinct words answered before a tier is judged at all
PASS_ACCURACY = 0.7       # accuracy needed to count a tier as "solid"


@dataclass
class TierResult:
    difficulty: int
    label: str
    answered: int          # distinct words answered at this tier
    accuracy: float        # correct / total answers at this tier
    solid: bool            # enough data AND accuracy >= PASS_ACCURACY


@dataclass
class LevelEstimate:
    level: str                                  # highest solid tier, or a data note
    confident: bool                             # at least one tier has enough answers
    answered_total: int                         # distinct words answered overall
    note: str
    tiers: list[TierResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def assess(profile: Profile) -> LevelEstimate:
    """Estimate the student's vocabulary level from their answer history. Pure."""
    tiers: list[TierResult] = []
    for difficulty in sorted(TIER_LABELS):
        tier_words = [w for w in profile.vocabulary if w.difficulty == difficulty]
        answered_words = [w for w in tier_words if w.answers > 0]
        total = sum(w.answers for w in answered_words)
        correct = sum(w.correct for w in answered_words)
        accuracy = (correct / total) if total else 0.0
        tiers.append(
            TierResult(
                difficulty=difficulty,
                label=TIER_LABELS[difficulty],
                answered=len(answered_words),
                accuracy=accuracy,
                solid=len(answered_words) >= MIN_ANSWERS_PER_TIER and accuracy >= PASS_ACCURACY,
            )
        )

    answered_total = sum(t.answered for t in tiers)
    confident = any(t.answered >= MIN_ANSWERS_PER_TIER for t in tiers)
    solid_tiers = [t for t in tiers if t.solid]

    if answered_total == 0:
        level, note = "Not enough data yet", "Answer some words to estimate your level."
    elif not confident:
        level = "Just starting"
        note = f"Answer at least {MIN_ANSWERS_PER_TIER} words in a tier to confirm a level."
    elif solid_tiers:
        top = solid_tiers[-1]
        level = top.label
        nxt = next((t for t in tiers if t.difficulty > top.difficulty), None)
        note = (
            f"Solid on {top.label} words."
            + (f" Practice {nxt.label} words to go higher." if nxt else " Top tier reached.")
        )
    else:
        # Has enough data somewhere, but nothing crossed the accuracy bar yet.
        level = "Building"
        note = f"Keep practicing — reach {int(PASS_ACCURACY * 100)}% in a tier to lock a level."

    return LevelEstimate(
        level=level,
        confident=confident,
        answered_total=answered_total,
        note=note,
        tiers=tiers,
    )
