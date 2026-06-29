"""Lesson Engine v1 — a lesson is a computed projection (Rule 5), reusing the bank.

Doing the exercises produces grammar_question facts, so a lesson also updates Knowledge
(Rule 6). Tested as pure structure plus an end-to-end API run.
"""

import pytest
from fastapi.testclient import TestClient

from mentoros.api import app, get_store
from mentoros.assessment.question_bank import by_id, display_form, load_bank, load_lesson_bank
from mentoros.curriculum import load_curriculum
from mentoros.events import EventStore
from mentoros.knowledge import MASTERY_THRESHOLD, build_knowledge
from mentoros.lesson import build_lesson

BANK = load_bank()
LESSON_BANK = load_lesson_bank()
CUR = load_curriculum()
EXERCISE = {"guided", "independent", "quiz"}


# --- pure build_lesson ------------------------------------------------------ #
def test_lesson_shape_and_order():
    lesson = build_lesson("nouns_articles", build_knowledge([], CUR), BANK, CUR)
    kinds = [s.kind for s in lesson.steps]
    assert kinds[0] == "warm_up"
    assert kinds[1] == "explanation"
    assert kinds[-1] == "summary"
    assert lesson.target_mastery == MASTERY_THRESHOLD
    assert any(k in EXERCISE for k in kinds)


def test_lesson_exercises_come_from_the_topic_and_hide_the_answer():
    lesson = build_lesson("nouns_articles", build_knowledge([], CUR), BANK, CUR)
    ex = [s for s in lesson.steps if s.kind in EXERCISE]
    assert ex, "a lesson should contain exercises"
    for s in ex:
        assert "answer" not in s.question        # never leak the key
        qid = s.question["id"]
        assert by_id(BANK)[qid].topic == "nouns_articles"


def test_build_lesson_is_deterministic():
    k = build_knowledge([], CUR)
    a = build_lesson("present_perfect", k, BANK, CUR)
    b = build_lesson("present_perfect", k, BANK, CUR)
    assert a.to_dict() == b.to_dict()


def test_lesson_bank_is_separate_with_fallback():
    assert any(q.topic == "nouns_articles" for q in LESSON_BANK)  # practice content exists
    # a covered topic uses the Lesson bank (practice items), not the assessment items
    covered = build_lesson("nouns_articles", build_knowledge([], CUR), LESSON_BANK, CUR, fallback_bank=BANK)
    ex_ids = {s.question["id"] for s in covered.steps if s.kind in EXERCISE}
    assert ex_ids and all(i.startswith("lp_") for i in ex_ids)
    # an uncovered topic falls back to the assessment bank, so the lesson still has exercises
    fell_back = build_lesson("inversion", build_knowledge([], CUR), LESSON_BANK, CUR, fallback_bank=BANK)
    assert [s for s in fell_back.steps if s.kind in EXERCISE]


# --- end-to-end API --------------------------------------------------------- #
@pytest.fixture()
def client(tmp_path):
    store = EventStore(tmp_path / "log.jsonl")
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_lesson_start_returns_steps_without_answer_keys(client):
    d = client.post("/lesson/start", json={"topic": "nouns_articles"}).json()
    assert d["lesson"]["topic"] == "nouns_articles"
    for s in d["lesson"]["steps"]:
        if s["question"]:
            assert "answer" not in s["question"]


def test_lesson_run_feeds_knowledge_and_finishes(client):
    answers = {q.id: display_form(q)[1] for q in (LESSON_BANK + BANK)}  # shuffled-correct index
    lesson = client.post("/lesson/start", json={"topic": "nouns_articles"}).json()["lesson"]
    answered = 0
    for s in lesson["steps"]:
        if s["question"]:
            qid = s["question"]["id"]
            r = client.post("/lesson/answer", json={"question": qid, "choice": answers[qid]}).json()
            assert r["correct"] is True
            answered += 1
    fin = client.post("/lesson/finish", json={"topic": "nouns_articles"}).json()
    assert fin["knowledge"]["sample_size"] == answered          # lesson answers became facts
    assert fin["knowledge"]["mastery"] > 0.5                    # all correct -> mastery up


def test_lesson_start_without_topic_uses_the_planner(client):
    # Empty store -> planner focus is an A1 root, so a lesson is still produced.
    d = client.post("/lesson/start", json={}).json()
    assert d["lesson"] is not None
    assert d["lesson"]["level"] == "A1"


def test_lesson_answer_unknown_question_is_404(client):
    assert client.post("/lesson/answer", json={"question": "nope", "choice": 0}).status_code == 404
