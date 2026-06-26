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

1. **Facts only** — no numbers "from the model's head"; all state reconstructs from history.
2. **History is immutable** — events are append-only; you never edit the past.
3. **Everything is computed** — the profile is always rebuilt from events.
4. **AI never changes facts** — AI only forms hypotheses (V2+); it is never a source of truth.

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

```bash
# 1. Backend — event-sourced API over the core
pip install -e ".[api]"
uvicorn mentoros.api:app --reload          # http://localhost:8000  (docs at /docs)

# 2. Frontend — Next.js daily-flow UI
cd web && npm install && npm run dev        # http://localhost:3000
```

The web app reads/writes through the API (override its base URL with
`NEXT_PUBLIC_API_URL`). To move the event log from JSONL to PostgreSQL, install
`.[postgres]` and back the API with `PostgresEventStore` — same append-only contract.

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

- **V1 (now):** Vocabulary · Review Queue · Events · Profile Generator · Session History.
- **V2:** Grammar · Layer B (hypotheses) · Writing · Reading · Listening.
- **V3:** Speaking · Voice · Adaptive Conversations.

## Success metric

Not feature count — one question: *"Will I open this app tomorrow morning without a
reminder?"* If no, simplify; don't add features.

## Development

```bash
PYTHONPATH=. python3 -m pytest -q
```

MIT licensed.
