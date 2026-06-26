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

## Scope

- **V1 (this milestone):** Vocabulary · Review Queue · Events · Profile Generator · Session History.
- **V2:** Grammar · Layer B (hypotheses) · Writing · Reading · Listening.
- **V3:** Speaking · Voice · Adaptive Conversations.

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
