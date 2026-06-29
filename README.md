# MentorOS

## AI Tutor That Never Forgets

MentorOS stores **not the conversation, but the state of learning**. Its only job:

> Every day, help the student take the next most useful step.

It is built on event sourcing: an **immutable log of facts** is the single source
of truth, and everything else — vocabulary mastery, the review schedule, the whole
profile — is **computed** from that log, never stored as primary data. See
[SPEC.md](SPEC.md) for the full v1.0 specification.

```
events  ──►  build_profile()  ──►  profile.json   (a regenerable cache, not the truth)
```

## Principles

0. **Usage beats architecture** — every change must increase the chance you open MentorOS tomorrow; if not, it waits. Outranks even YAGNI.
1. **Facts only** — no numbers "from the model's head"; all state reconstructs from history.
2. **History is immutable** — events are append-only; you never edit the past.
3. **Everything is computed** — the profile is always rebuilt from events.
4. **AI never changes facts** — AI only forms hypotheses (V2+); it is never a source of truth.
5. **The plan is computed, not stored** — no "150-day plan" file to patch; the plan, the level, today's lesson are all recomputed from `events + curriculum_graph`, like the review queue. (Rule 3 applied to the planner.)
6. **Assessment is continuous** — every learning event is also an assessment event; there is no "end of the test". Per-topic **mastery + confidence** (and the CEFR they imply) are recomputed from events forever.

## Quickstart (V1 — deterministic core, no DB/web/AI)

```bash
pip install -e ".[dev]"     # or: PYTHONPATH=. python3 -m mentoros.cli ...

# The daily flow, from the terminal — events are the source of truth:
mentoros add maintain "to keep in good condition" --difficulty 2
mentoros add inevitable "certain to happen"
mentoros review                                  # today's queue (computed)
mentoros answer maintain --correct --latency-ms 2100
mentoros profile                                 # rebuild + show; writes profile.json
```

Everything you see is recomputed from the event log on every command. Delete
`profile.json` any time — it rebuilds from the events.

## Python API

```python
from mentoros import EventStore, build_profile, build_review_queue

store = EventStore("data/alice.events.jsonl")
store.record("word_added", {"word": "maintain", "meaning": "to keep", "difficulty": 2})
store.record("word_answered", {"word": "maintain", "correct": True, "latency_ms": 2100})

profile = build_profile(store.read_all())          # pure, deterministic
queue = build_review_queue(profile.vocabulary, profile.generated_ts)
```

`build_profile` is order-independent: it replays events in timestamp order, so the
same history always yields the same profile (tested).

## Run the full stack (API + web)

One command — it bootstraps dependencies on first run, then starts both servers:

```bash
make dev          # API → http://localhost:8000 (/docs) · web → http://localhost:3000
make seed         # load the academic word list into your local store (once)
```

<details><summary>…or run the pieces by hand</summary>

```bash
pip install -e ".[api]" && uvicorn mentoros.api:app --reload   # backend
cd web && npm install && npm run dev                           # frontend
```
</details>

The web app reads/writes through the API (override its base URL with
`NEXT_PUBLIC_API_URL`). To move the event log from JSONL to PostgreSQL, install
`.[postgres]` and back the API with `PostgresEventStore` — same append-only contract.

## AI chat (memory-aware, model-agnostic)

Three endpoints, one rule — **the model never decides facts**:

- `POST /chat` — builds the prompt from the *computed* profile + today's queue, asks
  the tutor, then runs the model's proposed events through the **writeback engine**:
  objective outcomes become facts (appended to the log), guesses become hypotheses
  (Layer B, never in the log). The profile is then recomputed.
- `POST /events` — append a deterministic event directly.
- `GET /profile` — the computed profile.

The tutor sits behind an `AITutor` seam: `OpenAITutor` when `OPENAI_API_KEY` is set
(`pip install '.[ai]'`), otherwise an offline `StubTutor` so `/chat` still works.
Put your key in `.env` (copy `.env.example`) — it's gitignored and loaded by `make dev`.
Swap in a Claude/Gemini tutor and nothing else changes — all memory lives in
MentorOS, not in the model.

## Architecture

```
Next.js (frontend)  →  FastAPI  →  PostgreSQL  →  Learning Engine  →  OpenAI API
                                   (event log +      ("what helps      (explanations /
                                    projections)      today?")          generation only)
```

**V1 (this milestone)** implements the bottom deterministic core in pure Python —
the event log, `build_profile`, the Leitner review scheduler, session history — so
it is fully testable with no DB, web, or AI. The DB / API / frontend wrap it next.

## Roadmap

One invariant across every version: **new capabilities are added as projections or
services over the Event Store — never by rewriting the core.** Layers are gated by
**usage, not time**. See [SPEC.md](SPEC.md#roadmap) for detail.

- **✅ Core v1 (completed, in use):** Event Store · Profile Projection · Review Queue · AI Chat · Planner · Curriculum Graph (`data/curriculum/`) · Onboarding · Level Placement (self-report) · Daily Lesson · Rules 1–6 · **Knowledge Projection** (per-topic mastery + confidence, `mentoros/knowledge.py`, `GET /knowledge`).
- **🚧 Assessment v2 (multi-skill):** adaptive diagnostic over a curated **Question Bank** (`data/assessment/` — **155 items across Grammar / Vocabulary / Reading / Listening**, 32 topics). **Per-skill narrowing:** each skill has its own ability estimate θ (up/down staircase) and budget; the selector asks only near that skill's θ → each skill gets its own CEFR level (a per-skill **Knowledge Graph**). Listening is Reading + audio — same MCQ grading (no ASR); the item carries a `script` the browser speaks via TTS (path A; path B = pre-generated audio files). Server-side grading, event-sourced session (`POST /assessment/start` · `/assessment/answer`). **Deferred (need ASR / LLM-scoring infra — Coach v4):** Speaking, Writing. Produces higher-quality events; the core is untouched.
- **🚧 Lesson Engine v2.1 (linear lesson shipped):** `build_lesson(topic, knowledge, bank)` is a *computed* lesson (`mentoros/lesson.py`) — warm-up → explanation → guided → independent → quiz → summary, exercises reused from the bank. `POST /lesson/start` · `/lesson/answer` · `/lesson/finish`. Lesson answers are `grammar_question` facts, so doing a lesson is also continuous assessment (Rule 6). Next: Lesson Runtime (conditional transitions) → Lesson Graph.
- **🚧 Teacher v3 (live teacher in lessons):** three layers — **Lesson Engine** (deterministic steps) → **Teacher Runtime** (owns all routing: retry vs advance, when to stop) → **LLM Adapter** (`mentoros/teacher.py`: `StubTeacher`/`OpenAITeacher`, strict contract `feedback/hint/encouragement`, content only). A static **Persona** (`data/teacher/persona.json`) sets the style (patient, Socratic, never reveals the answer immediately). `POST /lesson/answer` returns the Teacher's feedback + the Runtime's retry decision; `POST /lesson/explain` narrates a step. Swap the model = swap one adapter; the LLM never routes (Rule 7).
- **🚧 Coach v4 (the other skills):** Reading · Listening · Speaking · Writing · Vocabulary — each on the same shape `events → knowledge → planner → teacher`.
- **🚧 Psychometrics v5 (optional, data-permitting):** calibrate item difficulty/discrimination (real IRT) once enough data accrues; the system works without it.

**Content is split by purpose (v3.1):** **Assessment Content** (`data/assessment/`) — few, high-quality items for *measuring*; **Lesson Content** (`data/lessons/`) — many practice items for *learning* (lessons fall back to the assessment bank for topics the practice bank doesn't cover yet). Both feed the same facts → Knowledge.

CEFR is **only an outward label**: `Events → Knowledge Projection → CEFR Projection`,
never the reverse. The LLM lives only in the Teacher seam — swapping OpenAI → Claude →
anything else changes only that layer; memory, knowledge, plan and review are untouched.

## Success metric

Not feature count — one question: *"Will I open this app tomorrow morning without a
reminder?"* If no, simplify; don't add features.

## Development

```bash
PYTHONPATH=. python3 -m pytest -q
```

MIT licensed.
