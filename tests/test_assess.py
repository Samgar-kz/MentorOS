"""assess() is a deterministic projection of answers, never a stored/AI-set level."""

from mentoros.assess import MIN_ANSWERS_PER_TIER, assess
from mentoros.events import WORD_ADDED, WORD_ANSWERED, Event
from mentoros.profile import build_profile

NOW = 1_000_000.0


def ev(type, payload, ts):
    return Event(type=type, payload=payload, ts=float(ts), id=f"{type}@{ts}-{payload.get('word')}")


def add(word, difficulty, ts=0):
    return ev(WORD_ADDED, {"word": word, "meaning": "m", "difficulty": difficulty}, ts)


def ans(word, correct, ts):
    return ev(WORD_ANSWERED, {"word": word, "correct": correct}, ts)


def test_no_answers_is_not_enough_data():
    profile = build_profile([add("a", 1), add("b", 2)], now=NOW)
    est = assess(profile)
    assert est.level == "Not enough data yet"
    assert est.confident is False
    assert est.answered_total == 0


def test_solid_core_tier_sets_level():
    events = []
    for n in range(MIN_ANSWERS_PER_TIER):
        w = f"core{n}"
        events += [add(w, 1), ans(w, True, ts=n + 1)]
    est = assess(build_profile(events, now=NOW))
    assert est.confident is True
    assert est.level == "Core"
    core = next(t for t in est.tiers if t.difficulty == 1)
    assert core.solid is True
    assert core.answered == MIN_ANSWERS_PER_TIER


def test_low_accuracy_does_not_lock_a_level():
    events = []
    for n in range(MIN_ANSWERS_PER_TIER):
        w = f"core{n}"
        # All wrong -> enough data, but accuracy below the bar.
        events += [add(w, 1), ans(w, False, ts=n + 1)]
    est = assess(build_profile(events, now=NOW))
    assert est.confident is True
    assert est.level == "Building"
    assert all(not t.solid for t in est.tiers)


def test_highest_solid_tier_wins():
    events = []
    for tier in (1, 2):
        for n in range(MIN_ANSWERS_PER_TIER):
            w = f"t{tier}_{n}"
            events += [add(w, tier), ans(w, True, ts=tier * 100 + n)]
    est = assess(build_profile(events, now=NOW))
    assert est.level == "Academic"  # tier 2 label, the highest solid one


def test_assess_is_pure_no_side_effects():
    profile = build_profile([add("a", 1), ans("a", True, ts=1)], now=NOW)
    assert assess(profile).to_dict() == assess(profile).to_dict()
