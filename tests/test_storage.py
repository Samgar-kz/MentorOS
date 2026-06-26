"""The file store and any DB backend share one append-only contract."""

from mentoros.events import EventStore
from mentoros.storage import EventStoreProtocol


def test_file_store_satisfies_protocol(tmp_path):
    # The default JSONL store conforms to the swappable storage contract, so a
    # PostgresEventStore (same methods) can replace it without changes upstream.
    assert isinstance(EventStore(tmp_path / "log.jsonl"), EventStoreProtocol)
