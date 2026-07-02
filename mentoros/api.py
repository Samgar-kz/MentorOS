"""FastAPI layer over the deterministic core.

Thin by design: every endpoint either appends an event (the only writes) or returns
a freshly computed projection (review queue / profile). No state lives here — it is
all recomputed from the event log on every read, exactly like the CLI.

Run: ``uvicorn mentoros.api:app --reload`` (install with ``pip install 'mentoros[api]'``).
"""

from __future__ import annotations

import os
import uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from mentoros.events import (
    ASSESSMENT_COMPLETED,
    GRAMMAR_QUESTION,
    LESSON_FINISHED,
    LESSON_STARTED,
    PLACEMENT_PASSED,
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


class TopicAnswerIn(BaseModel):
    topic: str
    correct: bool


class PlacementIn(BaseModel):
    known_levels: list[str] = []  # CEFR levels the student already knows, e.g. ["A1","A2","B1"]


class AssessmentAnswerIn(BaseModel):
    question: str
    choice: int
    latency: float = 0.0
    confidence: int | None = None  # optional self-rated confidence (1-5)


class LessonStartIn(BaseModel):
    topic: str | None = None  # if absent, the Planner picks today's focus topic


class LessonAnswerIn(BaseModel):
    question: str
    choice: int
    latency: float = 0.0
    attempt: int = 1  # which try this is (Runtime allows a limited number of retries)


class LessonExplainIn(BaseModel):
    topic: str


class LessonExtraIn(BaseModel):
    topic: str


class LessonExtraAnswerIn(BaseModel):
    id: str
    choice: int


class LessonFinishIn(BaseModel):
    topic: str


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


@app.get("/plan")
def plan(store: EventStore = Depends(get_store)) -> dict:
    """Today's plan — recomputed from events + the curriculum graph (Rule 5)."""
    from mentoros.planner import plan_today

    return plan_today(store.read_all()).to_dict()


@app.get("/topics")
def topics(store: EventStore = Depends(get_store)) -> dict:
    """Every curriculum topic with its computed status (locked/available/learning/mastered)."""
    from dataclasses import asdict

    from mentoros.curriculum import load_curriculum
    from mentoros.planner import build_topic_states

    states = build_topic_states(store.read_all(), load_curriculum())
    return {"topics": [asdict(s) for s in states.values()]}


@app.get("/knowledge")
def knowledge(store: EventStore = Depends(get_store)) -> dict:
    """The Knowledge Projection: per-topic mastery + confidence, and the CEFR it implies.
    All computed from events, never stored (Rule 3 / Rule 6)."""
    from mentoros.curriculum import load_curriculum
    from mentoros.knowledge import build_knowledge, estimate_cefr

    curriculum = load_curriculum()
    k = build_knowledge(store.read_all(), curriculum)
    return {"cefr": estimate_cefr(k, curriculum), "topics": [v.to_dict() for v in k.values()]}


@app.post("/topics/answer")
def topic_answer(body: TopicAnswerIn, store: EventStore = Depends(get_store)) -> dict:
    """Record a grammar-topic outcome — a fact (Rule 1), folded into topic mastery."""
    e = store.record(GRAMMAR_QUESTION, body.model_dump())
    return {"recorded": e.id, "topic": body.topic, "correct": body.correct}


@app.post("/assessment/start")
def assessment_start(store: EventStore = Depends(get_store)) -> dict:
    """Begin (or resume) the adaptive diagnostic — returns the next question to ask."""
    from mentoros.assessment.adaptive import next_step
    from mentoros.curriculum import load_curriculum

    return next_step(store.read_all(), load_curriculum()).to_dict()


@app.post("/assessment/answer")
def assessment_answer(body: AssessmentAnswerIn, store: EventStore = Depends(get_store)) -> dict:
    """Grade the answer server-side, record it as a fact, and return feedback + next step.
    Finishing the diagnostic also satisfies onboarding."""
    from mentoros.assessment.adaptive import next_step
    from mentoros.assessment.question_bank import by_id, display_form, load_bank
    from mentoros.assessment.session import grade
    from mentoros.curriculum import load_curriculum

    bank = load_bank()
    q = by_id(bank).get(body.question)
    if q is None:
        raise HTTPException(status_code=404, detail="unknown question")

    correct = grade(q, body.choice)
    payload = {"topic": q.topic, "correct": correct, "question": q.id, "latency": body.latency}
    if body.confidence is not None:
        payload["confidence"] = body.confidence
    store.record(GRAMMAR_QUESTION, payload)

    events = store.read_all()
    curriculum = load_curriculum()
    step = next_step(events, curriculum, bank)
    if step.done and not any(e.type == ASSESSMENT_COMPLETED for e in events):
        from mentoros.assessment.adaptive import ONBOARDING_SKILLS, bank_cap, skills_in
        from mentoros.assessment.selector import estimate_theta

        # Tested skills are placed at their own level. Skills NOT tested in onboarding
        # (Reading/Listening) get a prior = the overall tested level, so a C1 student isn't
        # dropped into A2 lessons; real lesson answers correct it later (Rule 6). The bank
        # ceiling cap keeps each skill's top topic available (still assessed via lessons).
        tested = [s for s in skills_in(bank) if s in ONBOARDING_SKILLS]
        # floor (like the label): the confirmed level must never exceed the working one
        targets = {s: min(int(estimate_theta(events, bank, s)), bank_cap(bank, s)) for s in tested}
        overall = round(sum(targets.values()) / len(targets)) if targets else 0
        for t in curriculum.topics:
            target = min(targets.get(t.skill, overall), bank_cap(bank, t.skill))
            if t.level_rank < target:
                store.record(PLACEMENT_PASSED, {"topic": t.id})
        store.record(ASSESSMENT_COMPLETED, {})
        step = next_step(store.read_all(), curriculum, bank)  # reflect placement → real overall CEFR

    return {"correct": correct, "answer": display_form(q)[1], "explanation": q.explanation, **step.to_dict()}


@app.post("/lesson/start")
def lesson_start(body: LessonStartIn, store: EventStore = Depends(get_store)) -> dict:
    """Begin a lesson on a topic (Planner's focus if none given). Returns the computed
    lesson; records lesson_started. The lesson itself is never stored (Rule 5)."""
    from mentoros.curriculum import load_curriculum
    from mentoros.knowledge import build_knowledge
    from mentoros.lesson import build_lesson
    from mentoros.assessment.question_bank import load_bank, load_lesson_bank
    from mentoros.planner import plan_today

    events = store.read_all()
    curriculum = load_curriculum()
    topic = body.topic
    if topic is None:
        focus = plan_today(events).focus
        topic = focus[0]["id"] if focus else None
    if topic is None or topic not in curriculum.by_id:
        return {"lesson": None, "message": "Nothing to learn right now."}

    store.record(LESSON_STARTED, {"topic": topic})
    lesson = build_lesson(
        topic, build_knowledge(events, curriculum),
        load_lesson_bank(), curriculum, fallback_bank=load_bank(),  # practice bank, then assessment
    )
    return {"lesson": lesson.to_dict()}


def _weak_areas(knowledge, curriculum, skill: str, limit: int = 3) -> list[str]:
    """Titles of started-but-not-known topics in a skill — context for the Teacher."""
    return [
        curriculum.by_id[tid].title
        for tid, kn in knowledge.items()
        if kn.skill == skill and not kn.known and kn.sample_size > 0
    ][:limit]


@app.post("/lesson/answer")
def lesson_answer(body: LessonAnswerIn, store: EventStore = Depends(get_store)) -> dict:
    """Grade a lesson exercise server-side, record it as a fact (feeds Knowledge), then
    let the Teacher (LLM adapter) give feedback. The Runtime — not the model — decides
    whether to retry."""
    from mentoros.assessment.question_bank import by_id, display_form, load_bank, load_lesson_bank
    from mentoros.assessment.session import grade
    from mentoros.curriculum import load_curriculum
    from mentoros.knowledge import build_knowledge
    from mentoros.teacher import TeacherContext, get_teacher, load_persona, runtime_should_retry

    # The question may come from the Lesson bank (practice) or the Assessment bank (fallback).
    q = by_id(load_lesson_bank()).get(body.question) or by_id(load_bank()).get(body.question)
    if q is None:
        raise HTTPException(status_code=404, detail="unknown question")
    correct = grade(q, body.choice)
    store.record(
        GRAMMAR_QUESTION,
        {"topic": q.topic, "correct": correct, "question": q.id, "latency": body.latency,
         "attempt": body.attempt, "source": "lesson"},
    )

    curriculum = load_curriculum()
    knowledge = build_knowledge(store.read_all(), curriculum)
    topic = curriculum.by_id[q.topic]
    k = knowledge.get(q.topic)
    shown, answer_idx = display_form(q)  # the (shuffled) options the student actually saw
    ctx = TeacherContext(
        topic_title=topic.title, level=topic.level, mastery=(k.mastery if k else 0.5),
        weak_areas=_weak_areas(knowledge, curriculum, topic.skill), step_kind="guided",
        question=q.question, choices=shown,
        student_answer=shown[body.choice] if 0 <= body.choice < len(shown) else None,
        correct=correct,
    )
    t = get_teacher().teach(ctx)
    return {
        "correct": correct, "answer": answer_idx, "explanation": q.explanation,
        "teacher": {"name": load_persona()["name"], "feedback": t.feedback, "hint": t.hint, "encouragement": t.encouragement},
        "should_retry": runtime_should_retry(correct, body.attempt),  # Runtime decides, not the model
    }


@app.post("/lesson/explain")
def lesson_explain(body: LessonExplainIn, store: EventStore = Depends(get_store)) -> dict:
    """The Teacher narrates the explanation step for a topic (LLM adapter; offline stub
    otherwise). Pure content — no routing."""
    from mentoros.curriculum import load_curriculum
    from mentoros.knowledge import build_knowledge
    from mentoros.teacher import TeacherContext, get_teacher, load_persona

    curriculum = load_curriculum()
    if body.topic not in curriculum.by_id:
        raise HTTPException(status_code=404, detail="unknown topic")
    knowledge = build_knowledge(store.read_all(), curriculum)
    topic = curriculum.by_id[body.topic]
    k = knowledge.get(body.topic)
    ctx = TeacherContext(
        topic_title=topic.title, level=topic.level, mastery=(k.mastery if k else 0.5),
        weak_areas=_weak_areas(knowledge, curriculum, topic.skill), step_kind="explanation",
    )
    t = get_teacher().teach(ctx)
    return {"teacher": {"name": load_persona()["name"], "feedback": t.feedback, "hint": t.hint, "encouragement": t.encouragement}}


@app.post("/lesson/extra")
def lesson_extra(
    body: LessonExtraIn,
    store: EventStore = Depends(get_store),
    hyp_store: EventStore = Depends(get_hyp_store),
) -> dict:
    """LLM-generated extra practice. The model AUTHORS the item, so it is hypothesis-grade
    content (Rule 4): the exercise and its outcomes live in Layer B and never become
    grammar_question facts — variety for practice, not measurement."""
    import random as _random

    from mentoros.curriculum import load_curriculum
    from mentoros.knowledge import build_knowledge
    from mentoros.teacher import TeacherContext, get_teacher

    curriculum = load_curriculum()
    if body.topic not in curriculum.by_id:
        raise HTTPException(status_code=404, detail="unknown topic")
    knowledge = build_knowledge(store.read_all(), curriculum)
    topic = curriculum.by_id[body.topic]
    k = knowledge.get(body.topic)
    ex = get_teacher().generate_exercise(
        TeacherContext(
            topic_title=topic.title, level=topic.level, mastery=(k.mastery if k else 0.5),
            weak_areas=_weak_areas(knowledge, curriculum, topic.skill), step_kind="independent",
        )
    )
    if ex is None:
        return {"exercise": None, "message": "AI practice needs OPENAI_API_KEY (offline stub can't generate)."}

    # Shuffle server-side so the model's answer position carries no signal.
    order = list(range(len(ex.choices)))
    _random.shuffle(order)
    choices = [ex.choices[i] for i in order]
    answer = order.index(ex.answer)
    e = hyp_store.record(
        "generated_exercise",
        {"topic": body.topic, "question": ex.question, "choices": choices,
         "answer": answer, "explanation": ex.explanation},
    )
    return {"exercise": {"id": e.id, "topic": body.topic, "question": ex.question, "choices": choices}}


@app.post("/lesson/extra/answer")
def lesson_extra_answer(
    body: LessonExtraAnswerIn, hyp_store: EventStore = Depends(get_hyp_store)
) -> dict:
    """Grade a generated exercise (server-side, from Layer B) and record the outcome as a
    hypothesis — it never enters the fact log."""
    item = next(
        (e for e in hyp_store.read_all() if e.type == "generated_exercise" and e.id == body.id),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="unknown exercise")
    correct = body.choice == item.payload["answer"]
    hyp_store.record(
        "hypothesis",
        {"kind": "generated_practice", "topic": item.payload["topic"],
         "exercise": body.id, "correct": correct},
    )
    return {"correct": correct, "answer": item.payload["answer"],
            "explanation": item.payload.get("explanation", "")}


@app.post("/lesson/finish")
def lesson_finish(body: LessonFinishIn, store: EventStore = Depends(get_store)) -> dict:
    """Mark the lesson finished and return the topic's updated knowledge (the payoff:
    you see mastery/confidence change)."""
    from mentoros.curriculum import load_curriculum
    from mentoros.knowledge import build_knowledge

    store.record(LESSON_FINISHED, {"topic": body.topic})
    curriculum = load_curriculum()
    k = build_knowledge(store.read_all(), curriculum).get(body.topic)
    return {"topic": body.topic, "knowledge": k.to_dict() if k else None}


@app.post("/placement")
def placement(body: PlacementIn, store: EventStore = Depends(get_store)) -> dict:
    """Place the student by level: every topic in a known level (and its foundations)
    becomes mastered via placement facts — so the plan starts where they already are,
    not at A1. Recomputed like everything else; a later wrong answer can resurface a
    placed topic (Rule 5)."""
    from mentoros.curriculum import load_curriculum
    from mentoros.knowledge import build_knowledge, estimate_cefr

    known = set(body.known_levels)
    curriculum = load_curriculum()
    passed = [t for t in curriculum.topics if t.level in known]
    for t in passed:
        store.record(PLACEMENT_PASSED, {"topic": t.id})  # input: a known topic (no stored level)

    # The level check is complete — a pure onboarding marker; no level is stored.
    store.record(ASSESSMENT_COMPLETED, {})

    # The level shown back is a *projection* of the resulting knowledge (Knowledge -> CEFR).
    cefr = estimate_cefr(build_knowledge(store.read_all(), curriculum), curriculum)
    return {"known_levels": sorted(known), "placed": [t.id for t in passed], "level": cefr or "A1"}


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
    from mentoros.planner import plan_today

    events = store.read_all()
    profile = build_profile(events)
    queue = build_review_queue(profile.vocabulary, profile.generated_ts)
    focus = plan_today(events).focus  # the Planner chooses the topic; the model just teaches it
    result = tutor.respond(
        build_prompt(profile, queue, body.message, body.goal, focus_topic=focus[0] if focus else None)
    )

    facts, hypotheses = writeback(result.events)

    # Rule 4 hardening: in free chat the MODEL judges correctness, so a proposed "fact"
    # enters the log only if the server can re-grade it itself — a bank question id plus
    # the student's choice. The server's grade overrides whatever the model claimed;
    # everything else stays a hypothesis, however confident the model sounded.
    from mentoros.assessment.question_bank import by_id, load_bank
    from mentoros.assessment.session import grade

    bankmap = by_id(load_bank())
    verified: list[dict] = []
    for f in facts:
        p = dict(f.get("payload", {}))
        q = bankmap.get(p.get("question"))
        if f["type"] == GRAMMAR_QUESTION and q is not None and isinstance(p.get("choice"), int):
            p["topic"] = q.topic                 # the bank, not the model, says what was tested
            p["correct"] = grade(q, p["choice"])  # the server, not the model, grades it
            p["verified"] = True
            verified.append({"type": f["type"], "payload": p})
        else:
            hypotheses.append(f)

    for f in verified:
        store.record(f["type"], f["payload"])           # server-verified -> Layer A
    for h in hypotheses:
        hyp_store.record(h.get("type", "hypothesis"), h.get("payload", h))  # guess -> Layer B

    return {
        "response": result.response,
        "tutor": getattr(tutor, "name", "?"),
        "recorded_facts": verified,
        "hypotheses": hypotheses,
    }
