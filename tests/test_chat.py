"""Chat layer — the AI proposes, the writeback engine decides (Rule 4).

No network: a FakeTutor / the StubTutor stand in for the LLM, so the fact-vs-
hypothesis routing is tested deterministically.
"""

import pytest
from fastapi.testclient import TestClient

from mentoros.ai import AIResult, StubTutor, build_prompt, writeback
from mentoros.api import app, get_hyp_store, get_store, get_tutor
from mentoros.events import EventStore
from mentoros.profile import build_profile
from mentoros.review import WordState


class FakeTutor:
    name = "fake"

    def __init__(self, result):
        self._result = result

    def respond(self, prompt):
        return self._result


@pytest.fixture()
def setup(tmp_path):
    store = EventStore(tmp_path / "log.jsonl")
    hyp = EventStore(tmp_path / "hyp.jsonl")

    def make(tutor):
        app.dependency_overrides[get_store] = lambda: store
        app.dependency_overrides[get_hyp_store] = lambda: hyp
        app.dependency_overrides[get_tutor] = lambda: tutor
        return TestClient(app)

    yield make, store, hyp
    app.dependency_overrides.clear()


# --- writeback (pure) ------------------------------------------------------- #

def test_writeback_splits_facts_from_hypotheses():
    facts, hyps = writeback([
        {"type": "grammar_question", "payload": {"topic": "inversion", "correct": True}},  # fact
        {"type": "hypothesis", "payload": {"note": "may struggle with inversion"}},        # hypothesis
        {"type": "word_answered", "payload": {"word": "x"}},                                 # no outcome -> hypothesis
        {"type": "unknown_thing", "payload": {}},                                           # unknown -> hypothesis
        {"type": "reading_finished", "payload": {"score": 7}},                               # objective event -> fact
    ])
    assert {f["type"] for f in facts} == {"grammar_question", "reading_finished"}
    assert len(hyps) == 3  # Rule 4: anything not a clear fact stays a hypothesis


def test_build_prompt_uses_computed_context():
    p = build_profile([])
    q = [WordState("maintain", "keep", 1, 0, 0, 0, None)]
    prompt = build_prompt(p, q, "I don't get inversion", goal="TOEFL 110")
    assert "TOEFL 110" in prompt
    assert "maintain" in prompt
    assert "I don't get inversion" in prompt


# --- /chat routing ---------------------------------------------------------- #

def test_chat_routes_fact_to_log_and_hypothesis_to_layer_b(setup):
    make, store, hyp = setup
    result = AIResult(
        response="Let's practice inversion.",
        events=[
            {"type": "grammar_question", "payload": {"topic": "inversion", "correct": True}},
            {"type": "hypothesis", "payload": {"note": "may struggle with inversion"}},
        ],
    )
    client = make(FakeTutor(result))

    r = client.post("/chat", json={"message": "I don't get inversion"}).json()
    assert r["response"] == "Let's practice inversion."
    # Rule 4 hardening: the MODEL judged correctness with no verifiable reference
    # (no bank question id + choice) — the claim is demoted to a hypothesis.
    assert r["recorded_facts"] == []
    assert len(r["hypotheses"]) == 2

    assert store.read_all() == []                # the deterministic log is untouched
    assert len(hyp.read_all()) == 2              # both live in Layer B


def test_chat_verifiable_fact_is_regraded_by_the_server(setup):
    from mentoros.assessment.question_bank import display_form, load_bank

    make, store, _ = setup
    q = load_bank()[0]
    correct_idx = display_form(q)[1]
    wrong = (correct_idx + 1) % len(q.choices)
    # The model LIES that the student was correct — but it references a bank item and
    # the student's choice, so the server re-grades and records the truth.
    result = AIResult("ok", [{
        "type": "grammar_question",
        "payload": {"topic": "whatever-the-model-says", "correct": True,
                    "question": q.id, "choice": wrong},
    }])
    client = make(FakeTutor(result))

    r = client.post("/chat", json={"message": "quiz me"}).json()
    assert len(r["recorded_facts"]) == 1
    fact = store.read_all()[0]
    assert fact.payload["correct"] is False      # the server's grade, not the model's claim
    assert fact.payload["topic"] == q.topic      # the bank's topic, not the model's claim
    assert fact.payload["verified"] is True


def test_chat_stub_tutor_records_nothing(setup):
    make, store, _ = setup
    client = make(StubTutor())
    r = client.post("/chat", json={"message": "hi"}).json()
    assert r["tutor"] == "stub"
    assert r["recorded_facts"] == [] and r["hypotheses"] == []
    assert store.read_all() == []  # the model changed no facts


def test_chat_model_claimed_word_answer_never_updates_profile(setup):
    # The model saying "the student answered 'maintain' correctly" is its own judgement —
    # unverifiable by the server, so it must NOT touch the profile (Rule 4).
    make, store, hyp = setup
    store.record("word_added", {"word": "maintain", "meaning": "keep", "difficulty": 1})
    result = AIResult("ok", [{"type": "word_answered", "payload": {"word": "maintain", "correct": True}}])
    client = make(FakeTutor(result))
    client.post("/chat", json={"message": "test me on maintain"})
    prof = build_profile(store.read_all())
    w = prof.vocabulary[0]
    assert w.word == "maintain" and w.answers == 0        # profile unchanged
    assert any(e.type == "word_answered" for e in hyp.read_all())  # claim parked in Layer B


# --- generic /events -------------------------------------------------------- #

def test_events_endpoint_appends(setup):
    make, store, _ = setup
    client = make(StubTutor())
    r = client.post("/events", json={"type": "reading_finished", "payload": {"score": 8}})
    assert r.status_code == 200
    assert [e.type for e in store.read_all()] == ["reading_finished"]
