"""Teacher — Runtime owns routing, the LLM adapter only produces content (Rule 7).

Offline (no key) uses StubTeacher, so these run with no network.
"""

import pytest
from fastapi.testclient import TestClient

from mentoros.api import app, get_store
from mentoros.assessment.question_bank import load_bank
from mentoros.events import EventStore
from mentoros.teacher import (
    MAX_RETRIES,
    StubTeacher,
    TeacherContext,
    load_persona,
    runtime_should_retry,
)

BANK = load_bank()


def test_persona_loads():
    p = load_persona()
    assert p["name"]
    assert isinstance(p["style"], list) and p["style"]
    assert any("never" in r.lower() for r in p["rules"])  # has guard-rails


# --- Runtime owns routing --------------------------------------------------- #
def test_runtime_retry_only_wrong_within_budget():
    assert runtime_should_retry(correct=True, attempt=1) is False     # never retry a correct answer
    assert runtime_should_retry(correct=False, attempt=1) is True     # first wrong -> retry
    assert runtime_should_retry(correct=False, attempt=MAX_RETRIES + 1) is False  # budget spent -> move on


# --- Adapter produces content (no routing) ---------------------------------- #
def test_stub_teacher_content():
    t = StubTeacher()
    wrong = t.teach(TeacherContext("Articles", "B1", 0.4, correct=False, question="...", choices=["a", "b"]))
    assert wrong.feedback and wrong.hint            # gives feedback + a hint, doesn't dump the answer
    right = t.teach(TeacherContext("Articles", "B1", 0.9, correct=True))
    assert right.feedback
    intro = t.teach(TeacherContext("Articles", "B1", 0.5, step_kind="explanation"))
    assert "Articles" in intro.feedback


# --- end-to-end via the lesson API ------------------------------------------ #
@pytest.fixture()
def client(tmp_path):
    store = EventStore(tmp_path / "log.jsonl")
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_lesson_answer_returns_teacher_and_runtime_decision(client):
    q = next(x for x in BANK if x.topic == "nouns_articles")
    wrong = (q.answer + 1) % len(q.choices)
    r = client.post("/lesson/answer", json={"question": q.id, "choice": wrong, "attempt": 1}).json()
    assert r["correct"] is False
    assert r["teacher"]["name"] and r["teacher"]["feedback"]   # the Teacher spoke
    assert r["should_retry"] is True                           # Runtime: first wrong -> retry

    r2 = client.post("/lesson/answer", json={"question": q.id, "choice": q.answer, "attempt": 2}).json()
    assert r2["correct"] is True
    assert r2["should_retry"] is False                         # correct -> advance


def test_lesson_explain_narrates_a_topic(client):
    r = client.post("/lesson/explain", json={"topic": "present_perfect"}).json()
    assert r["teacher"]["name"] and r["teacher"]["feedback"]


def test_lesson_explain_unknown_topic_404(client):
    assert client.post("/lesson/explain", json={"topic": "nope"}).status_code == 404