"""API tests — the FastAPI layer is a thin shell over the deterministic core.

Uses a temp file store via dependency override, so no DB or network is involved.
"""

import pytest
from fastapi.testclient import TestClient

from mentoros.api import app, get_store
from mentoros.events import EventStore


@pytest.fixture()
def client(tmp_path):
    store = EventStore(tmp_path / "log.jsonl")
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_daily_flow_add_review_answer_profile(client):
    assert client.post("/words", json={"word": "maintain", "meaning": "keep", "difficulty": 2}).status_code == 200
    client.post("/words", json={"word": "inevitable", "meaning": "certain"})

    # Both new words are due immediately.
    rv = client.get("/review").json()
    assert rv["count"] == 2
    assert {w["word"] for w in rv["queue"]} == {"maintain", "inevitable"}

    client.post("/answers", json={"word": "maintain", "correct": True, "latency_ms": 2100})

    prof = client.get("/profile").json()
    assert prof["word_count"] == 2
    assert prof["total_answers"] == 1
    assert prof["accuracy"] == 1.0
    # maintain answered correctly -> box 1 -> due in 1 day -> only 'inevitable' due now.
    assert prof["due_count"] == 1


def test_answers_are_append_only_facts(client):
    client.post("/words", json={"word": "w"})
    for correct in (True, True, False):
        client.post("/answers", json={"word": "w", "correct": correct})
    prof = client.get("/profile").json()
    w = prof["vocabulary"][0]
    assert (w["answers"], w["correct"]) == (3, 2)
    assert w["box"] == 0  # 0 ->T1 ->T2 ->F0


def test_sessions_start_and_finish(client):
    sid = client.post("/sessions/start").json()["session_id"]
    client.post("/sessions/finish", json={"session_id": sid, "duration_s": 600})
    prof = client.get("/profile").json()
    assert len(prof["sessions"]) == 1
    assert prof["sessions"][0]["duration_s"] == 600.0


def test_plan_starts_at_a1_then_placement_lifts_it(client):
    # Fresh: not onboarded yet; plan starts at the A1 roots, nothing mastered.
    plan = client.get("/plan").json()
    assert plan["onboarded"] is False
    assert plan["cefr_level"] is None
    assert plan["topics_mastered"] == 0
    assert "A1" in {f["level"] for f in plan["focus"]}  # the grammar foundation is in focus

    # Place the student at A1+A2: lower topics become known, focus moves up to B1.
    placed = client.post("/placement", json={"known_levels": ["A1", "A2"]}).json()
    assert len(placed["placed"]) > 0
    assert placed["level"] == "A2"

    plan2 = client.get("/plan").json()
    assert plan2["onboarded"] is True  # the level check is done -> plan unlocked
    assert plan2["cefr_level"] == "A2"
    assert plan2["topics_mastered"] == len(placed["placed"])
    assert all(f["level"] != "A1" for f in plan2["focus"])
