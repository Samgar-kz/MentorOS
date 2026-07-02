"""LLM-generated practice is hypothesis-grade (Rule 4): items and outcomes live in
Layer B and never touch the fact log. Offline (stub) it degrades gracefully."""

import pytest
from fastapi.testclient import TestClient

import mentoros.teacher as teacher_mod
from mentoros.api import app, get_hyp_store, get_store
from mentoros.events import EventStore
from mentoros.teacher import GeneratedExercise


class FakeTeacher:
    name = "fake"

    def teach(self, ctx):  # pragma: no cover - not used here
        raise AssertionError("not expected")

    def generate_exercise(self, ctx):
        return GeneratedExercise(
            question="Pick the article: ___ apple",
            choices=["a", "an", "the", "—"],
            answer=1,
            explanation="Vowel sound -> 'an'.",
        )


@pytest.fixture()
def stores(tmp_path):
    store = EventStore(tmp_path / "log.jsonl")
    hyp = EventStore(tmp_path / "hyp.jsonl")
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_hyp_store] = lambda: hyp
    yield store, hyp
    app.dependency_overrides.clear()


@pytest.fixture()
def client(stores):
    return TestClient(app)


def test_offline_stub_degrades_gracefully(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = client.post("/lesson/extra", json={"topic": "nouns_articles"}).json()
    assert r["exercise"] is None
    assert "message" in r


def test_generated_flow_lives_in_layer_b_only(client, stores, monkeypatch):
    store, hyp = stores
    monkeypatch.setattr(teacher_mod, "get_teacher", lambda: FakeTeacher())

    r = client.post("/lesson/extra", json={"topic": "nouns_articles"}).json()
    ex = r["exercise"]
    assert ex is not None
    assert "answer" not in ex                       # key never leaves the server
    assert set(ex["choices"]) == {"a", "an", "the", "—"}  # shuffled server-side

    # the generated item is stored in Layer B, and the FACT log is untouched
    assert any(e.type == "generated_exercise" for e in hyp.read_all())
    assert store.read_all() == []

    # grade via the stored (shuffled) key
    correct_idx = ex["choices"].index("an")
    g = client.post("/lesson/extra/answer", json={"id": ex["id"], "choice": correct_idx}).json()
    assert g["correct"] is True
    wrong = client.post("/lesson/extra/answer", json={"id": ex["id"], "choice": (correct_idx + 1) % 4}).json()
    assert wrong["correct"] is False

    # outcomes are hypotheses in Layer B; still zero facts
    outs = [e for e in hyp.read_all() if e.type == "hypothesis"]
    assert len(outs) == 2 and all(e.payload["kind"] == "generated_practice" for e in outs)
    assert store.read_all() == []


def test_unknown_topic_and_id_are_404(client, monkeypatch):
    monkeypatch.setattr(teacher_mod, "get_teacher", lambda: FakeTeacher())
    assert client.post("/lesson/extra", json={"topic": "nope"}).status_code == 404
    assert client.post("/lesson/extra/answer", json={"id": "nope", "choice": 0}).status_code == 404
