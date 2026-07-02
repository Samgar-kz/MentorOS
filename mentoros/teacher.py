"""Teacher — the last mile, split into a Runtime (decides) and an LLM Adapter (teaches).

Three responsibilities, kept separate on purpose (Rule 7):

- **Lesson Engine** (``lesson.py``) — deterministic: the steps and exercises.
- **Teacher Runtime** (here, ``runtime_should_retry`` + callers) — owns ALL routing:
  retry vs advance, when to stop. The LLM never routes.
- **LLM Adapter** (``TeacherAdapter``) — turns a context into *content* under a strict
  contract: feedback / hint / encouragement. It knows nothing about MentorOS and makes
  no decisions about what to study next.

Swap OpenAI for Claude/local by writing another ``TeacherAdapter`` — the Runtime is
untouched. A static **Persona** (``data/teacher/persona.json``) gives one teaching style.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Protocol, runtime_checkable

_PERSONA_PATH = (
    Path(os.environ.get("MENTOROS_DATA", Path(__file__).resolve().parent.parent / "data"))
    / "teacher" / "persona.json"
)

MAX_RETRIES = 1  # Runtime rule: at most one retry per exercise, then move on


@lru_cache(maxsize=None)
def load_persona(path: str | None = None) -> dict:
    return json.loads((Path(path) if path else _PERSONA_PATH).read_text(encoding="utf-8"))


# --- Teacher Runtime (routing — never the LLM) ------------------------------ #
def runtime_should_retry(correct: bool, attempt: int) -> bool:
    """Authoritative routing decision: retry only a wrong answer, and only within the
    retry budget. The LLM may *suggest* a retry, but this is what the system obeys."""
    return (not correct) and (attempt <= MAX_RETRIES)


# --- Teacher Contract ------------------------------------------------------- #
@dataclass
class TeacherContext:
    topic_title: str
    level: str
    mastery: float
    weak_areas: list[str] = field(default_factory=list)
    step_kind: str = "explanation"      # explanation | guided | independent | quiz
    question: str = ""
    choices: list[str] = field(default_factory=list)
    student_answer: str | None = None
    correct: bool | None = None


@dataclass
class TeacherResponse:
    feedback: str
    hint: str = ""
    encouragement: str = ""
    should_retry: bool = False           # a SUGGESTION; the Runtime decides for real

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GeneratedExercise:
    """One LLM-authored practice item. Because the *model* claims the answer key, this is
    hypothesis-grade content (Rule 4): it lives in Layer B and its outcomes never become
    ``grammar_question`` facts — generated practice adds variety, not measurement."""

    question: str
    choices: list[str]
    answer: int
    explanation: str = ""


@runtime_checkable
class TeacherAdapter(Protocol):
    name: str

    def teach(self, ctx: TeacherContext) -> TeacherResponse: ...

    def generate_exercise(self, ctx: TeacherContext) -> GeneratedExercise | None: ...


# --- Adapters --------------------------------------------------------------- #
class StubTeacher:
    """Deterministic, offline teacher — the default with no OPENAI_API_KEY. Keeps the
    lesson alive without a network call (and used in tests)."""

    name = "stub"

    def teach(self, ctx: TeacherContext) -> TeacherResponse:
        if ctx.correct is True:
            return TeacherResponse("Correct — nicely done.", encouragement="Keep it up!")
        if ctx.correct is False:
            return TeacherResponse(
                "Not quite.",
                hint="Look closely at the form here.",
                encouragement="You're close — give it one more try.",
                should_retry=True,
            )
        # explanation step (no answer yet)
        return TeacherResponse(f"Let's work on {ctx.topic_title}. Read the example, then try a question.")

    def generate_exercise(self, ctx: TeacherContext) -> GeneratedExercise | None:
        return None  # offline: no generation — lessons keep using the curated banks


def _persona_system() -> str:
    p = load_persona()
    return (
        f"You are {p['name']}, a language teacher. Style: {', '.join(p['style'])}.\n"
        + "\n".join(f"- {r}" for r in p["rules"])
        + '\n\nReturn ONLY JSON: {"feedback": "...", "hint": "...", "encouragement": "...", '
        '"should_retry": true|false}. You teach the CURRENT step only; you never decide '
        "what to study next or end the lesson."
    )


class OpenAITeacher:
    """OpenAI-backed teacher under the strict Teacher Contract. Produces content only;
    routing fields are ignored by the Runtime. Requires ``mentoros[ai]`` + a key."""

    name = "openai"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("MENTOROS_MODEL", "gpt-4o-mini")

    def teach(self, ctx: TeacherContext) -> TeacherResponse:
        from openai import OpenAI  # lazy

        weak = ", ".join(ctx.weak_areas) or "none noted"
        outcome = (
            "no answer yet"
            if ctx.correct is None
            else ("answered CORRECTLY" if ctx.correct else "answered INCORRECTLY")
        )
        user = (
            f"Topic: {ctx.topic_title} ({ctx.level}). Student mastery: {ctx.mastery:.2f}. "
            f"Weak areas: {weak}.\nCurrent step: {ctx.step_kind}.\n"
            f"Question: {ctx.question or '(none)'}\nChoices: {ctx.choices}\n"
            f"Student answer: {ctx.student_answer or '(none)'} ({outcome})."
        )
        client = OpenAI()
        completion = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": _persona_system()}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
        )
        raw = completion.choices[0].message.content or "{}"
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            return TeacherResponse(feedback=raw)
        # Content only — any routing the model suggests is advisory (Runtime decides).
        return TeacherResponse(
            feedback=str(d.get("feedback", "")),
            hint=str(d.get("hint", "")),
            encouragement=str(d.get("encouragement", "")),
            should_retry=bool(d.get("should_retry", False)),
        )

    def generate_exercise(self, ctx: TeacherContext) -> GeneratedExercise | None:
        """Author ONE fresh multiple-choice practice item for the current topic. Fails
        soft (None) on any malformed output — the lesson then just uses the banks."""
        from openai import OpenAI  # lazy

        weak = ", ".join(ctx.weak_areas) or "none noted"
        user = (
            f"Create ONE new multiple-choice practice exercise for the topic "
            f"'{ctx.topic_title}' at CEFR level {ctx.level}. Student mastery: {ctx.mastery:.2f}; "
            f"weak areas: {weak}. It must NOT repeat a textbook classic verbatim.\n"
            'Return ONLY JSON: {"question": "...", "choices": ["...", "...", "...", "..."], '
            '"answer": <index of the correct choice>, "explanation": "..."} — exactly one '
            "correct choice, plausible distractors, one sentence of explanation."
        )
        client = OpenAI()
        completion = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": _persona_system()}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
        )
        try:
            d = json.loads(completion.choices[0].message.content or "{}")
            choices = [str(c) for c in d["choices"]]
            answer = int(d["answer"])
            if len(choices) < 2 or not (0 <= answer < len(choices)) or not d.get("question"):
                return None
            return GeneratedExercise(
                question=str(d["question"]),
                choices=choices,
                answer=answer,
                explanation=str(d.get("explanation", "")),
            )
        except (KeyError, ValueError, TypeError, json.JSONDecodeError):
            return None


def get_teacher() -> TeacherAdapter:
    return OpenAITeacher() if os.environ.get("OPENAI_API_KEY") else StubTeacher()
