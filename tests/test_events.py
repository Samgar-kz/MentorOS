"""Events are immutable facts in an append-only log (Rules 1 & 2)."""

import dataclasses

import pytest

from mentoros.events import WORD_ANSWERED, Event, EventStore


def test_event_is_immutable():
    e = Event.new(WORD_ANSWERED, {"word": "maintain", "correct": True})
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.type = "tampered"  # Rule 2: history never mutates


def test_json_roundtrip():
    e = Event.new(WORD_ANSWERED, {"word": "maintain", "correct": True, "latency_ms": 2100}, ts=123.0)
    assert Event.from_json(e.to_json()) == e


def test_store_is_append_only_and_reads_back(tmp_path):
    store = EventStore(tmp_path / "log.jsonl")
    a = store.record(WORD_ANSWERED, {"word": "a", "correct": True})
    b = store.record(WORD_ANSWERED, {"word": "b", "correct": False})

    assert store.read_all() == [a, b]
    # The API exposes no way to update or delete — append-only by construction.
    assert not hasattr(store, "update")
    assert not hasattr(store, "delete")


def test_read_missing_file_is_empty(tmp_path):
    assert EventStore(tmp_path / "nope.jsonl").read_all() == []


def test_record_returns_event_with_id_and_ts(tmp_path):
    e = EventStore(tmp_path / "log.jsonl").record(WORD_ANSWERED, {"word": "x", "correct": True})
    assert e.id and isinstance(e.ts, float)
