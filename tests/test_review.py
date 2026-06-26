"""Spaced-repetition scheduling is a pure function of answer history (Rule 3)."""

from mentoros.review import (
    BOX_INTERVALS_DAYS,
    DAY_SECONDS,
    MASTERED_BOX,
    WordState,
    build_review_queue,
    interval_seconds,
    next_box,
)


def _w(word, box=0, answers=0, correct=0, last=None, difficulty=1, meaning="m"):
    return WordState(word, meaning, difficulty, box, answers, correct, last)


def test_next_box_promotes_on_correct_and_resets_on_wrong():
    assert next_box(0, True) == 1
    assert next_box(2, True) == 3
    assert next_box(3, False) == 0
    assert next_box(MASTERED_BOX, True) == MASTERED_BOX  # capped at the top


def test_interval_matches_box_table():
    assert interval_seconds(0) == 0
    assert interval_seconds(1) == 1 * DAY_SECONDS
    assert interval_seconds(MASTERED_BOX) == BOX_INTERVALS_DAYS[-1] * DAY_SECONDS


def test_never_answered_is_due_now():
    w = _w("new")
    assert w.next_due_ts == 0.0
    assert w.is_due(now=10.0)


def test_due_after_interval_elapses():
    w = _w("maintain", box=1, last=1000.0)  # box 1 -> due 1 day later
    assert not w.is_due(now=1000.0 + DAY_SECONDS - 1)
    assert w.is_due(now=1000.0 + DAY_SECONDS)


def test_mastered_and_accuracy():
    assert _w("done", box=MASTERED_BOX).mastered
    assert not _w("wip", box=2).mastered
    assert _w("x", answers=4, correct=3).accuracy == 0.75
    assert _w("y").accuracy == 0.0


def test_queue_excludes_mastered_by_default_and_orders_by_overdue():
    now = 10 * DAY_SECONDS
    due_old = _w("old", box=1, last=now - 5 * DAY_SECONDS)   # very overdue
    due_new = _w("new")                                       # due now (ts 0)
    not_due = _w("fresh", box=2, last=now)                    # just answered
    mastered = _w("mast", box=MASTERED_BOX, last=now - 31 * DAY_SECONDS)  # due but mastered

    q = build_review_queue([due_old, not_due, mastered, due_new], now)
    names = [w.word for w in q]
    assert "fresh" not in names      # not due
    assert "mast" not in names       # mastered excluded by default
    assert names == ["new", "old"]   # most overdue first (new due since ts 0)

    assert any(w.word == "mast" for w in build_review_queue([mastered], now, include_mastered=True))
