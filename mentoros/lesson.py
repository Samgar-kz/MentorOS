"""Lesson Engine v1 — turn a topic into a lesson. Pure, computed, never stored (Rule 5).

The Planner answers *what* to learn; the Lesson Engine answers *how*. ``build_lesson``
is a projection: given a topic + the Knowledge Projection + the question bank, it lays
out a linear lesson —

    warm-up → explanation → guided → independent → quiz → summary

The exercises are reused from the question bank (the same items the assessment uses), so
a lesson's answers are ``grammar_question`` facts that feed Knowledge — doing a lesson is
also continuous assessment (Rule 6). Prose steps are deterministic here (key points pulled
from the bank); the Teacher (LLM) can enrich them later without changing this structure.

v1 is linear on purpose. Conditional transitions (Lesson Runtime) and a full adaptive
graph come later — first prove the simple cycle works (Rule 0).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from mentoros.assessment.question_bank import Question
from mentoros.curriculum import Curriculum
from mentoros.knowledge import MASTERY_THRESHOLD, TopicKnowledge

# How many bank items to spend on each practice phase (capped by what the topic has).
GUIDED, INDEPENDENT, QUIZ = 2, 2, 2


@dataclass
class LessonStep:
    kind: str                       # warm_up | explanation | guided | independent | quiz | summary
    prose: str = ""                 # text for prose steps
    question: dict | None = None    # public question (no answer key) for exercise steps


@dataclass
class Lesson:
    topic: str
    title: str
    level: str
    target_mastery: float
    mastery: float
    confidence: float
    estimated_minutes: int
    steps: list[LessonStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _explanation(questions: list[Question]) -> str:
    seen: set[str] = set()
    points: list[str] = []
    for q in questions:
        e = q.explanation.strip()
        if e and e not in seen:
            seen.add(e)
            points.append(e)
        if len(points) >= 3:
            break
    if not points:
        return "Let's review this topic with a few examples."
    return "Key points:\n- " + "\n- ".join(points)


def build_lesson(
    topic_id: str,
    knowledge: dict[str, TopicKnowledge],
    bank: tuple[Question, ...],
    curriculum: Curriculum,
    fallback_bank: tuple[Question, ...] = (),
) -> Lesson:
    """Compose a linear lesson for one topic. ``bank`` is the Lesson Content (practice);
    if it has nothing for this topic yet, fall back to the assessment bank. Pure."""
    topic = curriculum.by_id[topic_id]
    k = knowledge.get(topic_id)
    mastery = k.mastery if k else 0.5
    confidence = k.confidence if k else 0.0

    qs = sorted((q for q in bank if q.topic == topic_id), key=lambda q: q.difficulty)
    if not qs and fallback_bank:
        qs = sorted((q for q in fallback_bank if q.topic == topic_id), key=lambda q: q.difficulty)
    guided = qs[:GUIDED]
    independent = qs[GUIDED:GUIDED + INDEPENDENT]
    quiz = qs[GUIDED + INDEPENDENT:GUIDED + INDEPENDENT + QUIZ]
    n_exercises = len(guided) + len(independent) + len(quiz)

    steps: list[LessonStep] = [
        LessonStep(
            "warm_up",
            prose=(
                f"Today's focus: {topic.title} ({topic.level}). Current mastery "
                f"{round(mastery * 100)}% (confidence {round(confidence * 100)}%). "
                "Let's make it solid."
            ),
        ),
        LessonStep("explanation", prose=_explanation(qs)),
    ]
    for q in guided:
        steps.append(LessonStep("guided", question=q.public()))
    for q in independent:
        steps.append(LessonStep("independent", question=q.public()))
    for q in quiz:
        steps.append(LessonStep("quiz", question=q.public()))
    steps.append(LessonStep("summary", prose="Nice work — let's see how this changed your knowledge."))

    return Lesson(
        topic=topic.id,
        title=topic.title,
        level=topic.level,
        target_mastery=MASTERY_THRESHOLD,
        mastery=mastery,
        confidence=confidence,
        estimated_minutes=4 + n_exercises,
        steps=steps,
    )
