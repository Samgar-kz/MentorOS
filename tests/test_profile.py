"""build_profile is a deterministic projection of the event log (Rules 1 & 3)."""

import json
import random

from mentoros.events import (
    SESSION_FINISHED,
    SESSION_STARTED,
    WORD_ADDED,
    WORD_ANSWERED,
    Event,
)
from mentoros.profile import build_profile, save_profile
from mentoros.review import MASTERED_BOX

NOW = 1_000_000.0


def ev(type, payload, ts):
    # Deterministic id so profile equality is exact across runs/orderings.
    return Event(type=type, payload=payload, ts=float(ts), id=f"{type}@{ts}")


def add(word, meaning="m", difficulty=1, ts=0):
    return ev(WORD_ADDED, {"word": word, "meaning": meaning, "difficulty": difficulty}, ts)


def ans(word, correct, ts):
    return ev(WORD_ANSWERED, {"word": word, "correct": correct, "latency_ms": 100}, ts)


def test_folds_answers_into_word_state():
    events = [add("maintain", "keep", 2, ts=1), ans("maintain", True, 2),
              ans("maintain", True, 3), ans("maintain", False, 4)]
    p = build_profile(events, now=NOW)
    w = {x.word: x for x in p.vocabulary}["maintain"]
    assert (w.answers, w.correct) == (3, 2)
    assert w.box == 0            # 0 ->(T)1 ->(T)2 ->(F)0
    assert w.meaning == "keep" and w.difficulty == 2


def test_box_sequence_is_order_dependent_but_replayed_in_ts_order():
    # 0 ->(T)1 ->(T)2 ->(F)0 ->(T)1
    events = [add("w", ts=1), ans("w", True, 2), ans("w", True, 3),
              ans("w", False, 4), ans("w", True, 5)]
    w = build_profile(events, now=NOW).vocabulary[0]
    assert w.box == 1
    assert (w.answers, w.correct) == (4, 3)


def test_profile_is_deterministic_regardless_of_input_order():
    events = [add("a", ts=1), add("b", ts=2), ans("a", True, 3),
              ans("b", False, 4), ans("a", True, 5),
              ev(SESSION_STARTED, {"session_id": "s1"}, 1),
              ev(SESSION_FINISHED, {"session_id": "s1", "duration_s": 600}, 6)]
    p1 = build_profile(events, now=NOW)
    shuffled = events[:]
    random.Random(42).shuffle(shuffled)
    p2 = build_profile(shuffled, now=NOW)
    assert p1 == p2  # Rule 1: state reconstructs from history, independent of order


def test_mastered_after_five_consecutive_correct():
    events = [add("solid", ts=0)] + [ans("solid", True, ts=i) for i in range(1, 6)]
    p = build_profile(events, now=NOW)
    w = p.vocabulary[0]
    assert w.box == MASTERED_BOX and w.mastered
    assert p.mastered_count == 1


def test_accuracy_and_counts():
    events = [add("a", ts=1), add("b", ts=2), ans("a", True, 3), ans("a", False, 4), ans("b", True, 5)]
    p = build_profile(events, now=NOW)
    assert p.word_count == 2
    assert p.total_answers == 3
    assert abs(p.accuracy - (2 / 3)) < 1e-9


def test_sessions_paired_by_id():
    events = [ev(SESSION_STARTED, {"session_id": "s1"}, 1),
              ev(SESSION_FINISHED, {"session_id": "s1", "duration_s": 1200}, 2)]
    p = build_profile(events, now=NOW)
    assert len(p.sessions) == 1
    assert p.sessions[0].session_id == "s1"
    assert p.sessions[0].duration_s == 1200.0


def test_answered_before_added_loses_no_fact():
    # An answer arriving before the word was formally added is still recorded.
    p = build_profile([ans("ghost", True, 1)], now=NOW)
    assert p.vocabulary[0].word == "ghost"
    assert p.total_answers == 1


def test_save_profile_is_regenerable_cache(tmp_path):
    p = build_profile([add("a", ts=1), ans("a", True, 2)], now=NOW)
    out = tmp_path / "p.json"
    save_profile(p, out)
    data = json.loads(out.read_text())
    assert data["word_count"] == 1 and data["total_answers"] == 1
