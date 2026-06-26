"""Seeding words is idempotent — re-running never duplicates events (Rule 2)."""

import json

from mentoros.cli import main
from mentoros.events import WORD_ADDED, EventStore
from mentoros.profile import build_profile


def test_seed_is_idempotent(tmp_path):
    store = tmp_path / "log.jsonl"
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([
        {"word": "alpha", "meaning": "first", "difficulty": 1},
        {"word": "beta", "meaning": "second", "difficulty": 2},
    ]))

    assert main(["--store", str(store), "seed", "--file", str(seed)]) == 0
    assert build_profile(EventStore(store).read_all()).word_count == 2

    # Second run adds nothing and appends no duplicate events.
    assert main(["--store", str(store), "seed", "--file", str(seed)]) == 0
    added = [e for e in EventStore(store).read_all() if e.type == WORD_ADDED]
    assert len(added) == 2


def test_shipped_toefl_seed_loads(tmp_path):
    # The committed academic word list parses and seeds cleanly.
    store = tmp_path / "log.jsonl"
    rc = main(["--store", str(store), "seed", "--file", "data/seed/toefl_academic.json"])
    assert rc == 0
    assert build_profile(EventStore(store).read_all()).word_count >= 100
