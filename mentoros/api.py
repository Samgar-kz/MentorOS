"""FastAPI layer over the deterministic core.

Thin by design: every endpoint either appends an event (the only writes) or returns
a freshly computed projection (review queue / profile). No state lives here — it is
all recomputed from the event log on every read, exactly like the CLI.

Run: ``uvicorn mentoros.api:app --reload`` (install with ``pip install 'mentoros[api]'``).
"""

from __future__ import annotations

import os
import uuid

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from mentoros.events import (
    SESSION_FINISHED,
    SESSION_STARTED,
    WORD_ADDED,
    WORD_ANSWERED,
    EventStore,
)
from mentoros.profile import build_profile
from mentoros.review import WordState, build_review_queue

app = FastAPI(title="MentorOS", version="0.1.0",
              description="AI tutor that never forgets — event-sourced learning engine.")

# Local dev tool: allow any origin so the browser is never the blocker, regardless
# of host/port the frontend is served from (localhost vs 127.0.0.1, any port).
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_store() -> EventStore:
    """Default store; overridable in tests via app.dependency_overrides."""
    return EventStore(os.environ.get("MENTOROS_STORE", "data/default.events.jsonl"))


def get_hyp_store() -> EventStore:
    """Layer B store — hypotheses live here and are NEVER read by build_profile."""
    base = os.environ.get("MENTOROS_STORE", "data/default.events.jsonl")
    hyp = base.replace(".events.jsonl", ".hypotheses.jsonl")
    return EventStore(hyp if hyp != base else base + ".hypotheses")


def get_tutor():
    """Real tutor when a key is configured, deterministic stub otherwise."""
    from mentoros.ai import OpenAITutor, StubTutor

    return OpenAITutor() if os.environ.get("OPENAI_API_KEY") else StubTutor()


# --- request bodies --------------------------------------------------------- #
class WordIn(BaseModel):
    word: str
    meaning: str = ""
    difficulty: int = 1


class AnswerIn(BaseModel):
    word: str
    correct: bool
    latency_ms: int = 0


class SessionFinishIn(BaseModel):
    session_id: str
    duration_s: float = 0.0


class EventIn(BaseModel):
    type: str
    payload: dict = {}


class ChatIn(BaseModel):
    message: str
    goal: str = "TOEFL 100"


# --- serialization ---------------------------------------------------------- #
def _word_dict(w: WordState) -> dict:
    return {
        "word": w.word, "meaning": w.meaning, "difficulty": w.difficulty,
        "box": w.box, "answers": w.answers, "correct": w.correct,
        "accuracy": w.accuracy, "mastered": w.mastered,
        "last_answered_ts": w.last_answered_ts, "next_due_ts": w.next_due_ts,
    }


# --- endpoints -------------------------------------------------------------- #
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "mentoros", "version": app.version}


@app.post("/words")
def add_word(body: WordIn, store: EventStore = Depends(get_store)) -> dict:
    e = store.record(WORD_ADDED, body.model_dump())
    return {"recorded": e.id, "word": body.word}


@app.post("/answers")
def record_answer(body: AnswerIn, store: EventStore = Depends(get_store)) -> dict:
    e = store.record(WORD_ANSWERED, body.model_dump())
    return {"recorded": e.id, "word": body.word, "correct": body.correct}


@app.get("/review")
def review(store: EventStore = Depends(get_store)) -> dict:
    profile = build_profile(store.read_all())
    queue = build_review_queue(profile.vocabulary, profile.generated_ts)
    return {"count": len(queue), "queue": [_word_dict(w) for w in queue]}


@app.get("/profile")
def profile(store: EventStore = Depends(get_store)) -> dict:
    p = build_profile(store.read_all())
    return {
        "generated_ts": p.generated_ts,
        "word_count": p.word_count,
        "mastered_count": p.mastered_count,
        "due_count": p.due_count,
        "total_answers": p.total_answers,
        "accuracy": p.accuracy,
        "vocabulary": [_word_dict(w) for w in p.vocabulary],
        "sessions": [vars(s) for s in p.sessions],
    }


@app.post("/sessions/start")
def session_start(store: EventStore = Depends(get_store)) -> dict:
    sid = uuid.uuid4().hex
    store.record(SESSION_STARTED, {"session_id": sid})
    return {"session_id": sid}


@app.post("/sessions/finish")
def session_finish(body: SessionFinishIn, store: EventStore = Depends(get_store)) -> dict:
    store.record(SESSION_FINISHED, body.model_dump())
    return {"session_id": body.session_id, "duration_s": body.duration_s}


@app.post("/events")
def add_event(body: EventIn, store: EventStore = Depends(get_store)) -> dict:
    """Append a deterministic event directly (the generic write path)."""
    e = store.record(body.type, body.payload)
    return {"recorded": e.id, "type": e.type}


@app.post("/chat")
def chat(
    body: ChatIn,
    store: EventStore = Depends(get_store),
    hyp_store: EventStore = Depends(get_hyp_store),
    tutor=Depends(get_tutor),
) -> dict:
    """One tutoring turn: build context from computed state, ask the tutor, then run
    its proposed events through the writeback engine — facts to the log, hypotheses
    to Layer B — and recompute the profile. The model never edits the truth."""
    from mentoros.ai import build_prompt, writeback

    profile = build_profile(store.read_all())
    queue = build_review_queue(profile.vocabulary, profile.generated_ts)
    result = tutor.respond(build_prompt(profile, queue, body.message, body.goal))

    facts, hypotheses = writeback(result.events)
    for f in facts:
        store.record(f["type"], f["payload"])           # objective -> Layer A
    for h in hypotheses:
        hyp_store.record(h.get("type", "hypothesis"), h.get("payload", h))  # guess -> Layer B

    return {
        "response": result.response,
        "tutor": getattr(tutor, "name", "?"),
        "recorded_facts": facts,
        "hypotheses": hypotheses,
    }
