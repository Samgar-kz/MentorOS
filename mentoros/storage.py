"""Storage backends for the event log — all append-only (Rule 2).

`EventStore` (file/JSONL, in events.py) is the default and the one used in tests.
This module adds the swappable contract and a PostgreSQL backend so the same event
log can move to a database without changing anything above it. Both backends expose
only append / record / read_all — no update or delete.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from mentoros.events import Event


@runtime_checkable
class EventStoreProtocol(Protocol):
    """The append-only contract every backend satisfies (file store included)."""

    def append(self, event: Event) -> Event: ...
    def record(self, type: str, payload: dict | None = None, ts: float | None = None) -> Event: ...
    def read_all(self) -> list[Event]: ...


class PostgresEventStore:
    """Append-only event log in PostgreSQL — same contract as the file store.

    Schema (created on first use):

        CREATE TABLE events (
            id      TEXT PRIMARY KEY,
            type    TEXT NOT NULL,
            ts      DOUBLE PRECISION NOT NULL,
            payload JSONB NOT NULL
        );

    Requires psycopg: ``pip install 'mentoros[postgres]'``. Append-only by design —
    inserts use ON CONFLICT DO NOTHING and there is no update/delete path.
    """

    def __init__(self, dsn: str, table: str = "events", ensure_schema: bool = True):
        self.dsn = dsn
        self.table = table
        if ensure_schema:
            self._ensure_schema()

    def _connect(self):
        import psycopg  # lazy: keeps psycopg optional

        return psycopg.connect(self.dsn)

    def _ensure_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {self.table} ("
                "id TEXT PRIMARY KEY, type TEXT NOT NULL, "
                "ts DOUBLE PRECISION NOT NULL, payload JSONB NOT NULL)"
            )
            conn.commit()

    def append(self, event: Event) -> Event:
        import json

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {self.table} (id, type, ts, payload) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (event.id, event.type, event.ts, json.dumps(event.payload)),
            )
            conn.commit()
        return event

    def record(self, type: str, payload: dict | None = None, ts: float | None = None) -> Event:
        return self.append(Event.new(type, payload, ts))

    def read_all(self) -> list[Event]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT type, payload, ts, id FROM {self.table} ORDER BY ts, id")
            rows = cur.fetchall()
        return [Event(type=t, payload=p, ts=ts, id=i) for (t, p, ts, i) in rows]
