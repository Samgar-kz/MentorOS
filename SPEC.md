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

## Roadmap & the gate

The layers are gated by **usage, not time** (Rule 0). Each layer is a set of
projections on top of an unchanged core — never a rewrite.

- **Core v1 — *done*.** Event Store · Profile Projection · Review Queue · AI Teacher
  (chat) · Deterministic Memory.
- **Planner v2 — *built*.** Curriculum Graph (`data/curriculum/`) · `assess(events)` ·
  `build_topic_states(...)` · `build_plan(...)` · `next_action(...)` · `GET /plan`.
  The system itself decides what to teach today; the Teacher only teaches the chosen
  topic. *(Built ahead of the usage gate by explicit request — the gate now guards v3.)*
- **Teacher v3 — *gated*.** Voice · Writing / Speaking / Reading / Listening coaches.
  **Goal: turn the Planner into a full personal teacher.**

**The gate (before v3):** after **14 days**, answer one question —
*"Did I open MentorOS on my own, without reminders?"*

- **Yes** → build the next layer.
- **No** → do **not** add features. Find out why the desire to open it disappeared.
  A bigger plan won't fix a loop that isn't pulling you back; it will only hide the
  problem behind complexity.

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
