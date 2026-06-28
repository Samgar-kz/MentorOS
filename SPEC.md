# MentorOS v1.0 — Specification

## AI Tutor That Never Forgets

MentorOS is not a chat and not a typical AI tutor. It is a personal teacher that
stores **not the conversation, but the state of learning**.

The single job of the system:

> Every day, help the student take the next most useful step in their learning.

No extra features. No assumptions without evidence. No magic.

---

## Core principles (non-negotiable)

**Rule 0 — Usage beats architecture.** Every change must answer one question:
*"Does it increase the chance I open MentorOS tomorrow morning, without a reminder?"*
If the answer is no, the change waits. This rule outranks the others (even YAGNI):
it ties every engineering decision to the only goal that matters — daily use. The
next best feature is often *not writing a feature* but checking whether it's needed.

**Rule 1 — Facts only.** The source of truth is verifiable facts. There are no
percentages "from the model's head". Any state can be reconstructed from the
history of events.

**Rule 2 — History is immutable.** Events are append-only and never modified
(e.g. `word_answered`, `exercise_completed`, `essay_submitted`,
`speaking_session_finished`).

**Rule 3 — Everything is computed.** The profile is never stored as the primary
source. It is always rebuilt:

```
events  ──►  build_profile()  ──►  profile.json
```

**Rule 4 — AI never changes facts.** AI may only form *hypotheses* (Layer B). A
hypothesis becomes a fact only after objective confirmation; it never auto-promotes
into the deterministic Layer A.

**Rule 5 — The plan is computed, not stored.** There is no "150-day plan" file that
we create once and then keep patching. The plan, the student's level, the next
lesson — all of it is recomputed every morning from `events + curriculum_graph`,
exactly like the review queue. The plan "adapts" not because we edit it, but because
it never existed as stored state. This is Rule 3 applied to the planner — named
separately because the planner is where the temptation to store state is strongest.

**Rule 6 — Assessment is continuous. Every learning event is also an assessment
event.** There is no "end of the test". The first placement is only a start; the
knowledge model updates after every answer, exercise and lesson, forever. This follows
directly from Rules 1 + 3 (the level is a forever-recomputed projection of all events),
but is named because it is the product stance that sets MentorOS apart: you take the
test every day without noticing.

---

## Architecture (target)

```
Next.js (frontend)
   ↓
FastAPI
   ↓
PostgreSQL          # event log + derived/cached projections
   ↓
Learning Engine     # "what helps the student most today?"
   ↓
OpenAI API          # explanations / examples / generation only (never source of truth)
```

V1 implements the **deterministic core** (the bottom of this stack, minus the AI):
pure Python, no DB/web/AI required, fully testable. The DB, API, and frontend wrap it.

---

## The Knowledge Projection — the core (mastery + confidence)

The real heart of MentorOS is not the AI, the Planner or the Teacher — it is the
**math model of knowledge**. For every topic we compute two *different* numbers from
the event log, never stored (`mentoros/knowledge.py`):

- **mastery** — how well the student knows it (Beta-Binomial posterior mean over their
  answers),
- **confidence** — how sure *we* are of that mastery (narrowness of the posterior).

They move independently: a few right answers → high mastery but **low** confidence
(tiny sample); many answers → the interval narrows and confidence rises, whether the
verdict is "knows it" or "doesn't". This replaces meaningless single percentages
("Grammar: 82%") with an honest, two-number engineering estimate. A topic is *known*
only when **both** clear a threshold.

Everything else is a layer over this model, not a competitor to it:

```
Layer 0  Facts          events (the only source of truth)
Layer 1  Knowledge      build_knowledge(events) -> {topic: (mastery, confidence)}
Layer 2  Assessment     a projection: estimate_cefr(knowledge) — CEFR is computed, never stored
Layer 3  Planner        picks today's node from knowledge + curriculum graph + review queue
Layer 4  Teacher (LLM)  taught the chosen topic; never decides what to learn
```

Because the model is subject-agnostic, switching TOEFL → GRE → any subject changes
only the curriculum graph and the question bank — not the core.

## The Planner (V2) — four pure functions, not four modules

The "personal teacher" is **not** four big stateful modules. It is four functions on
top of the existing core. Three of them contain no AI at all — they are projections,
like `build_review_queue`:

```python
profile = assess(events)                                   # level is computed, never stored
graph   = curriculum_graph                                 # static topic DAG (A1 → C1), versioned data
lesson  = build_plan(profile, graph, review_queue, today)  # today's plan, rebuilt every morning
action  = next_action(profile, lesson, review_queue)       # "what helps most right now?"
```

- **`assess`** — the level (`Grammar: B1+`) is a *projection* of answers, not a fact the
  AI writes (Rule 1 + 4). A diagnostic is just a series of `*_answered` events.
- **`curriculum_graph`** — the one genuinely new piece of data: topics A1 → C1 and their
  dependencies. A static, versioned file, like the vocabulary seed. Almost never changes.
- **`build_plan` / `next_action`** — pure functions. No stored plan (Rule 5).
- **Placement** — a `placement_passed` *event* records the levels a student already
  knows; `build_topic_states` then treats those topics (and their prerequisites) as
  mastered, so the plan starts where the student is, not at A1. The placement is a
  *fact* (Rule 1), not a stored flag, and it is self-correcting: a later wrong answer
  on a placed topic resets its box and resurfaces it (Rule 5).
- **Onboarding gate** — a new student does the level check *first*. Finishing it
  records an `assessment_completed` fact; only then is the plan shown. "Onboarded" and
  the found CEFR level are computed from events, never stored. Flow:
  *check level → know level → plan is created.*

**The LLM lives only in the Teacher** — the seam that turns today's plan into an actual
explanation. It receives `{today's topic, weak spots, recent mistakes, explanation level}`
and teaches; the only facts it produces are objective outcomes (answers). Because all
memory lives in MentorOS and not in the model, **swapping OpenAI → Claude → anything else
changes only the Teacher.** Memory, profile, plan, review, and diagnostics are untouched.
That is what makes the architecture durable.

---

## Memory model

`Memory = Events`. No summaries. No chat history. Only events, e.g.:

```
word=maintain  correct=true  latency_ms=2100  ts=...
```

- **Layer A — deterministic.** Vocabulary, exercise results, reading/listening
  scores, homework completion. All computed from events.
- **Layer B — hypotheses** (V2+). e.g. "student may confuse articles". Never a
  fact; never auto-merged into Layer A.

---

## Entities

- **User** — goal, current exam, daily time, target score.
- **Event** — every user action (append-only, immutable).
- **Vocabulary** — word, meaning, difficulty, review schedule *(computed)*, mastered *(computed)*.
- **Review Queue** — words to show today *(computed automatically)*.
- **Session** — date, duration, topics, mistakes, result.
- **Profile** — never stored; always generated from events.

---

## Daily flow

1. Open the app.
2. Get today's review queue.
3. Answer the questions.
4. The system records events automatically.
5. The profile is recomputed.
6. Show the next material.

No extra steps.

---

## Roadmap

The one invariant across every version: **new capabilities are added as new
projections or services over the Event Store — never by rewriting the core.** Each
layer is gated by **usage, not time** (Rule 0).

- **✅ Core v1 — *completed, in use*.** Event Store (append-only) · Profile Projection ·
  Review Queue · AI Chat · Planner · Curriculum Graph · Onboarding · Level Placement
  (self-report) · Daily Lesson · Rules 1–6 · **Knowledge Projection (mastery + confidence)**.
- **🚧 Assessment v2 — *prototype shipped*.** An adaptive diagnostic over a curated
  **Question Bank** (`mentoros/assessment/`, `data/assessment/`): selector (uncertainty +
  coverage + review) · stop-by-confidence · session is event-sourced (asked questions
  derived from events) · `POST /assessment/start` + `/assessment/answer` grade server-side
  and feed the Knowledge Projection. Doesn't touch the core — it just produces
  higher-quality events. **Multi-skill (v2.3):** four objectively-gradable skills —
  **Grammar (110), Vocabulary (24), Reading (12), Listening (9)** — 155 items across 32
  topics, content split per skill under `data/curriculum/` + `data/assessment/`
  (AI-authored, needs human review). **Listening** is Reading + audio: same MCQ grading
  (a fact, no ASR), the item carries a `script` the **browser speaks via TTS** (path A —
  transcript reaches the client; path B = pre-generated audio files keeps it server-side). **Narrowing, per skill:** each skill has its own ability estimate θ (up/down
  staircase) and its own question budget; the selector asks only questions near that
  skill's θ, so each skill is measured separately and yields its own CEFR level → a
  per-skill **Knowledge Graph**. On finish, levels below each skill's result are marked
  known (evidence-based placement). `estimated_level` (θ, working level) can lead the CEFR
  projection (mastered-up-to) by ~1 level. **Deferred (need infra, Coach v4):** Speaking
  (audio + ASR + pronunciation scoring), Writing (LLM rubric — a hypothesis, not a fact).
- **🚧 Lesson Engine v2.1 — *linear lesson shipped*.** `build_lesson(topic, knowledge,
  bank)` is a *computed* lesson (Rule 5, not stored): warm-up → explanation → guided →
  independent → quiz → summary. Exercises are reused from the question bank, so a lesson's
  answers are `grammar_question` facts that update Knowledge — **doing a lesson is also
  continuous assessment** (Rule 6). `POST /lesson/start` · `/lesson/answer` · `/lesson/finish`
  (returns the topic's updated mastery/confidence — the visible payoff). *Next: Lesson
  Runtime (conditional transitions) → Lesson Graph (full adaptive navigation).*
- **🚧 Teacher v3 — *live teacher, in lessons*.** Split into three responsibilities:
  **Lesson Engine** (deterministic steps) → **Teacher Runtime** (owns ALL routing:
  retry vs advance, when to stop — `runtime_should_retry`, max retries) → **LLM Adapter**
  (`mentoros/teacher.py`: `StubTeacher`/`OpenAITeacher` under a strict contract —
  `feedback / hint / encouragement`; produces *content only*, never routes). A static
  **Persona** (`data/teacher/persona.json`) gives one teaching style (patient, Socratic,
  never reveals the answer immediately). `POST /lesson/answer` returns Teacher feedback +
  the Runtime's retry decision; `POST /lesson/explain` narrates a step. Swap the model =
  swap one adapter. The LLM never decides what to learn or when the lesson ends (Rule 7).
- **🚧 Coach v4 — *the other skills*.** Reading · Listening · Speaking · Writing ·
  Vocabulary — each built on the same shape: `events → knowledge → planner → teacher`.
  The architecture is identical regardless of skill.
- **🚧 Psychometrics v5 — *optional, data-permitting*.** When enough data accrues,
  move from heuristics to calibrated item difficulty / discrimination (real IRT). If
  data is insufficient, the system keeps working on the current model. Not required.

CEFR is **only an outward label**: internally the system has events, per-topic
knowledge, and the curriculum graph. `Events → Knowledge Projection → CEFR Projection`,
never the reverse (Rule 3 + Rule 6).

---

## AI usage

AI is **not** a source of truth. It is used only for: explanations, examples,
exercise generation, motivation, essay analysis, conversation practice. All facts
stay deterministic. (No AI in V1.)

---

## Success metric

Not feature count, not architecture, not number of models — one question:

> "Will I open this app tomorrow morning without a reminder?"

If yes, the system works. If no, simplify — don't add features.

---

## Long-term vision

A system that grows with the student: today TOEFL, tomorrow CS, then grad school,
then interviews. The core never changes: **Facts → Events → Profile → Daily Learning.**
