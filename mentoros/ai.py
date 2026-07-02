"""AI tutor layer — the only place that talks to an LLM, behind a model-agnostic seam.

A chat turn never lets the model touch the truth (Rule 4):

    profile (computed) + today's queue  ->  build_prompt  ->  tutor.respond
                                                                   |
                                          proposed events  -->  writeback()
                                                                   |
                          facts (objective)  ->  appended to the event log
                          hypotheses (guesses) ->  Layer B, never in the log

Swap `OpenAITutor` for a Claude/Gemini implementation of `AITutor` and nothing else
changes — all memory and logic live in MentorOS, not in the model.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from mentoros.profile import Profile
from mentoros.review import WordState

# The only event types the tutor may assert as FACTS — each has an objective outcome.
FACT_TYPES = frozenset(
    {"word_answered", "grammar_question", "reading_finished", "essay_submitted", "session_finished"}
)

SYSTEM = (
    "You are MentorOS, a focused language tutor. Teach ONE concept at a time. Be "
    "concise. Prefer questions over explanations. Never overload the student.\n\n"
    "You do NOT decide facts. Return ONLY JSON: "
    '{"response": "<your message>", "events": [ ... ]}. Each event is either a FACT '
    'with an objective outcome, e.g. {"type":"grammar_question","payload":{"topic":'
    '"inversion","correct":true}}, or a HYPOTHESIS (a guess about the student), e.g. '
    '{"type":"hypothesis","payload":{"note":"may struggle with inversion"}}. Only '
    "assert a FACT when the outcome is objectively known from the exchange. NOTE: the "
    "server independently re-grades facts — a grammar_question is accepted as a fact only "
    "when it references a bank question id and the student's choice; anything else you "
    "propose is treated as a hypothesis."
)


@dataclass
class AIResult:
    response: str
    events: list[dict] = field(default_factory=list)  # events the model PROPOSES


@runtime_checkable
class AITutor(Protocol):
    name: str

    def respond(self, prompt: str) -> AIResult: ...


def build_prompt(
    profile: Profile,
    queue: list[WordState],
    message: str,
    goal: str = "TOEFL 100",
    focus_topic: dict | None = None,
) -> str:
    """Compose the per-turn context from computed state only (no stored chat history).

    ``focus_topic`` is chosen by the Planner (not the model): the tutor teaches the
    topic MentorOS picked. When it quizzes the student it must tag the outcome with
    that topic's id so the result folds back into topic mastery (Rule 4 writeback).
    """
    due = ", ".join(w.word for w in queue[:8]) or "(none)"
    focus_line = ""
    if focus_topic:
        focus_line = (
            f"Today's focus topic (chosen by MentorOS, teach THIS): "
            f"{focus_topic['title']} ({focus_topic['level']}).\n"
            f"When you quiz the student and the outcome is clear, emit a grammar_question "
            f'event: {{"type":"grammar_question","payload":{{"topic":"{focus_topic["id"]}",'
            f'"correct":true|false}}}}.\n'
        )
    return (
        f"Student goal: {goal}\n"
        f"Vocabulary: {profile.word_count} words, {profile.mastered_count} mastered, "
        f"{profile.due_count} due today.\n"
        f"Today's review: {due}\n"
        f"{focus_line}\n"
        f"Student says: {message}"
    )


def _is_objective(event_type: str, payload: dict) -> bool:
    if event_type in ("word_answered", "grammar_question"):
        return isinstance(payload.get("correct"), bool)
    return True  # reading_finished / essay_submitted / session_finished simply happened


def writeback(events: list[dict] | None) -> tuple[list[dict], list[dict]]:
    """Split the model's proposed events into facts and hypotheses (Rule 4).

    Conservative by construction: only a known type with an objective outcome becomes
    a fact; anything else — unknown type, missing outcome, explicit hypothesis — is a
    hypothesis and is never written to the deterministic event log.
    """
    facts: list[dict] = []
    hypotheses: list[dict] = []
    for e in events or []:
        etype = str(e.get("type", ""))
        payload = e.get("payload", {}) or {}
        if etype in FACT_TYPES and _is_objective(etype, payload):
            facts.append({"type": etype, "payload": payload})
        else:
            hypotheses.append(e)
    return facts, hypotheses


class StubTutor:
    """Deterministic, no-network tutor — the default when OPENAI_API_KEY is unset.

    Keeps /chat working offline for development and tests. Proposes no events (it
    can't objectively observe anything), so it never changes the profile.
    """

    name = "stub"

    def respond(self, prompt: str) -> AIResult:
        return AIResult(
            response=(
                "(offline tutor) Set OPENAI_API_KEY for a real tutor. "
                "For now: open today's review queue and practice your due words."
            ),
            events=[],
        )


class OpenAITutor:
    """OpenAI-backed tutor. One implementation of AITutor; swapping providers means a
    sibling class, not changes here. Requires `pip install 'mentoros[ai]'` + a key."""

    name = "openai"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("MENTOROS_MODEL", "gpt-4o-mini")

    def respond(self, prompt: str) -> AIResult:
        from openai import OpenAI  # lazy: keeps openai optional

        client = OpenAI()
        completion = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        raw = completion.choices[0].message.content or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return AIResult(response=raw, events=[])
        return AIResult(response=str(data.get("response", "")), events=list(data.get("events", []) or []))
