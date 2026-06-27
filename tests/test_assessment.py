"""Assessment Prototype — adaptive diagnostic over the curated question bank.

Pure selection/stop logic plus an end-to-end API loop. No DB or network (temp store).
"""

import pytest
from fastapi.testclient import TestClient

from mentoros.api import app, get_store
from mentoros.assessment.adaptive import next_step
from mentoros.assessment.question_bank import by_id, load_bank
from mentoros.assessment.selector import select_next
from mentoros.assessment.session import grade
from mentoros.curriculum import load_curriculum
from mentoros.events import GRAMMAR_QUESTION, Event, EventStore
from mentoros.knowledge import build_knowledge

BANK = load_bank()
CUR = load_curriculum()


# --- question bank ---------------------------------------------------------- #
def test_bank_loads_and_is_well_formed():
    assert len(BANK) >= 100
    ids = [q.id for q in BANK]
    assert len(ids) == len(set(ids))
    for q in BANK:
        assert 0 <= q.answer < len(q.choices)


def test_every_bank_topic_exists_in_curriculum():
    for q in BANK:
        assert q.topic in CUR.by_id, f"{q.id} references unknown topic {q.topic}"


def test_bank_covers_every_curriculum_topic():
    covered = {q.topic for q in BANK}
    missing = [t.id for t in CUR.topics if t.id not in covered]
    assert not missing, f"no questions for topics: {missing}"


def test_public_view_never_leaks_the_answer():
    pub = BANK[0].public()
    assert "answer" not in pub and "explanation" not in pub
    assert "choices" in pub and "id" in pub


def test_grade():
    q = BANK[0]
    assert grade(q, q.answer) is True
    assert grade(q, (q.answer + 1) % len(q.choices)) is False


# --- selector / stop -------------------------------------------------------- #
def test_selector_returns_unasked_question_first():
    knowledge = build_knowledge([], CUR)
    q = select_next(BANK, knowledge, asked_ids=set())
    assert q is not None and q.id not in set()


def test_selector_skips_already_asked():
    knowledge = build_knowledge([], CUR)
    asked = {q.id for q in BANK[:-1]}  # all but the last
    q = select_next(BANK, knowledge, asked_ids=asked)
    assert q.id == BANK[-1].id


def test_selector_returns_none_when_everything_asked():
    knowledge = build_knowledge([], CUR)
    asked = {q.id for q in BANK}
    assert select_next(BANK, knowledge, asked_ids=asked) is None


# --- adaptive step ---------------------------------------------------------- #
def test_fresh_assessment_has_a_question():
    step = next_step([], CUR, BANK)
    assert step.done is False
    assert step.question is not None
    assert step.asked_count == 0


def test_assessment_finishes_when_bank_exhausted():
    events = [
        Event(GRAMMAR_QUESTION, {"topic": q.topic, "correct": True, "question": q.id}, float(i), f"e{i}")
        for i, q in enumerate(BANK)
    ]
    step = next_step(events, CUR, BANK)
    assert step.done is True
    assert step.asked_count == len(BANK)
    # Per-topic mastery rises for the tested topics (the prototype bank covers 4 of them).
    tested = {k["topic"]: k for k in step.knowledge}
    assert tested["nouns_articles"]["mastery"] > 0.7
    # CEFR may stay None: a 4-topic bank can't cover enough of the graph to lock a level.


# --- end-to-end API loop ---------------------------------------------------- #
@pytest.fixture()
def client(tmp_path):
    store = EventStore(tmp_path / "log.jsonl")
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_start_returns_a_question_without_the_answer_key(client):
    s = client.post("/assessment/start").json()
    assert s["done"] is False
    assert "answer" not in s["question"]
    assert s["question"]["choices"]


def test_full_adaptive_loop_grades_records_and_onboards(client):
    answers = {q.id: q.answer for q in BANK}
    s = client.post("/assessment/start").json()
    seen = 0
    while not s["done"] and seen < 30:
        qid = s["question"]["id"]
        r = client.post("/assessment/answer", json={"question": qid, "choice": answers[qid]}).json()
        assert r["correct"] is True
        s = {"done": r["done"], "question": r["question"]}
        seen += 1
    assert s["done"] is True
    assert seen == 20  # stops at the question cap, not after the whole (110-item) bank
    # Finishing the diagnostic satisfies onboarding (a computed fact).
    plan = client.get("/plan").json()
    assert plan["onboarded"] is True
    # Exactly 20 answers were recorded and fed the Knowledge Projection.
    k = {t["topic"]: t for t in client.get("/knowledge").json()["topics"]}
    assert sum(t["sample_size"] for t in k.values()) == 20


def test_answer_to_unknown_question_is_404(client):
    assert client.post("/assessment/answer", json={"question": "nope", "choice": 0}).status_code == 404
