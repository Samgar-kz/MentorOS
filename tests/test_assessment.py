"""Assessment Prototype — adaptive diagnostic over the curated question bank.

Pure selection/stop logic plus an end-to-end API loop. No DB or network (temp store).
"""

import pytest
from fastapi.testclient import TestClient

from mentoros.api import app, get_store
from mentoros.assessment.adaptive import next_step
from mentoros.assessment.question_bank import by_id, load_bank
from mentoros.assessment.selector import estimate_theta, select_next
from mentoros.assessment.session import grade
from mentoros.curriculum import CEFR_ORDER, load_curriculum
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


# --- selector / stop (narrowing) ------------------------------------------- #
def test_selector_asks_near_theta():
    knowledge = build_knowledge([], CUR)
    q = select_next(BANK, knowledge, set(), theta=2.0)  # B1
    assert q is not None
    assert abs(CEFR_ORDER[q.cefr] - 2.0) <= 1.0  # within the band around B1


def test_selector_low_theta_picks_low_level():
    knowledge = build_knowledge([], CUR)
    q = select_next(BANK, knowledge, set(), theta=0.2)  # ~A1
    assert q is not None
    assert CEFR_ORDER[q.cefr] <= 1  # A1 or A2, never C1


def test_selector_returns_none_when_everything_asked():
    knowledge = build_knowledge([], CUR)
    asked = {q.id for q in BANK}
    assert select_next(BANK, knowledge, asked, theta=2.0) is None


def test_estimate_theta_moves_with_outcomes():
    b1 = [q for q in BANK if q.cefr == "B1"][:3]
    correct = [Event(GRAMMAR_QUESTION, {"topic": q.topic, "correct": True, "question": q.id}, float(i), f"c{i}") for i, q in enumerate(b1)]
    wrong = [Event(GRAMMAR_QUESTION, {"topic": q.topic, "correct": False, "question": q.id}, float(i), f"w{i}") for i, q in enumerate(b1)]
    assert estimate_theta(correct, BANK) > 2.0  # right answers push ability up
    assert estimate_theta(wrong, BANK) < 2.0    # wrong answers push it down


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


def test_day1_onboarding_is_grammar_and_vocab_only(client):
    answers = {q.id: q.answer for q in BANK}
    s = client.post("/assessment/start").json()
    skills_seen = set()
    seen = 0
    while not s["done"] and seen < 60:
        qid = s["question"]["id"]
        if s.get("skill"):
            skills_seen.add(s["skill"])
        r = client.post("/assessment/answer", json={"question": qid, "choice": answers[qid]}).json()
        assert r["correct"] is True
        s = {"done": r["done"], "question": r["question"], "skill": r.get("skill")}
        seen += 1
    assert s["done"] is True
    # Day-1 stays short: only Grammar + Vocabulary; Reading/Listening come via lessons.
    assert skills_seen == {"grammar", "vocabulary"}
    plan = client.get("/plan").json()
    assert plan["onboarded"] is True
    assert plan["cefr_level"] is not None  # all correct -> locks a level (placement on finish)


def test_wrong_answers_narrow_down_to_a1(client):
    s = client.post("/assessment/start").json()
    last = None
    seen = 0
    while not s["done"] and seen < 60:
        qid = s["question"]["id"]
        q = by_id(BANK)[qid]
        wrong = (q.answer + 1) % len(q.choices)
        last = client.post("/assessment/answer", json={"question": qid, "choice": wrong}).json()
        s = {"done": last["done"], "question": last["question"]}
        seen += 1
    assert s["done"] is True
    # Consistently wrong -> every skill's staircase floors at A1.
    assert all(lvl == "A1" for lvl in last["levels"].values())


def test_listening_questions_carry_a_script_but_never_the_answer():
    listening = [q for q in BANK if q.skill == "listening"]
    assert listening, "expected listening questions in the bank"
    for q in listening:
        assert q.script, f"{q.id} should have a spoken script"
        pub = q.public()
        assert pub.get("script") == q.script   # client needs it (TTS, path A)
        assert "answer" not in pub             # but never the answer key


def test_answer_to_unknown_question_is_404(client):
    assert client.post("/assessment/answer", json={"question": "nope", "choice": 0}).status_code == 404
