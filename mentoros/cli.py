"""mentoros CLI — the V1 daily flow from the terminal, no DB/web/AI required.

    mentoros add maintain "to keep in good condition" --difficulty 2
    mentoros review            # today's queue (computed from events)
    mentoros answer maintain --correct --latency-ms 2100
    mentoros profile           # rebuild + show the profile (and write profile.json)

Events are appended to a JSONL log (the source of truth); everything shown is
recomputed from that log on every command.
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path

from mentoros.events import (
    SESSION_FINISHED,
    SESSION_STARTED,
    WORD_ADDED,
    WORD_ANSWERED,
    EventStore,
)
from mentoros.profile import build_profile, save_profile
from mentoros.review import build_review_queue


def _store(args) -> EventStore:
    path = args.store or os.environ.get("MENTOROS_STORE") or "data/default.events.jsonl"
    return EventStore(path)


def _cmd_add(args) -> int:
    _store(args).record(
        WORD_ADDED,
        {"word": args.word, "meaning": args.meaning, "difficulty": args.difficulty},
    )
    print(f"+ added word: {args.word}")
    return 0


def _cmd_answer(args) -> int:
    _store(args).record(
        WORD_ANSWERED,
        {"word": args.word, "correct": args.correct, "latency_ms": args.latency_ms},
    )
    print(f"+ recorded answer: {args.word} -> {'correct' if args.correct else 'wrong'}")
    return 0


def _cmd_review(args) -> int:
    store = _store(args)
    profile = build_profile(store.read_all())
    queue = build_review_queue(profile.vocabulary, profile.generated_ts)
    if not queue:
        print("Nothing due today. 🎉  Add words with `mentoros add`.")
        return 0
    print(f"Today's review queue ({len(queue)} word(s)):\n")
    for w in queue:
        print(f"  • {w.word:<16} box {w.box}  acc {w.accuracy*100:.0f}%  — {w.meaning}")
    return 0


def _cmd_session(args) -> int:
    store = _store(args)
    if args.action == "start":
        sid = uuid.uuid4().hex
        store.record(SESSION_STARTED, {"session_id": sid})
        print(f"session started: {sid}")
    else:
        store.record(
            SESSION_FINISHED,
            {"session_id": args.session_id, "duration_s": args.duration_s},
        )
        print(f"session finished: {args.session_id} ({args.duration_s}s)")
    return 0


def _cmd_seed(args) -> int:
    store = _store(args)
    existing = {w.word for w in build_profile(store.read_all()).vocabulary}
    words = json.loads(Path(args.file).read_text(encoding="utf-8"))
    added = 0
    for entry in words:
        if entry["word"] in existing:
            continue  # idempotent: never re-add a word already in the log
        store.record(
            WORD_ADDED,
            {
                "word": entry["word"],
                "meaning": entry.get("meaning", ""),
                "difficulty": int(entry.get("difficulty", 1)),
            },
        )
        added += 1
    print(f"seeded {added} new word(s); {len(words) - added} already present")
    return 0


def _cmd_profile(args) -> int:
    store = _store(args)
    profile = build_profile(store.read_all())
    out = Path(args.store or "data/default.events.jsonl").with_suffix(".profile.json")
    save_profile(profile, out)
    print("MentorOS profile (computed from events)\n")
    print(f"  words:     {profile.word_count}")
    print(f"  mastered:  {profile.mastered_count}")
    print(f"  due today: {profile.due_count}")
    print(f"  answers:   {profile.total_answers}")
    print(f"  accuracy:  {profile.accuracy*100:.0f}%")
    print(f"  sessions:  {len(profile.sessions)}")
    print(f"\n  (cache written to {out} — regenerable from events)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mentoros", description="AI tutor that never forgets — V1 core.")
    p.add_argument("--store", help="Path to the event log (default: data/default.events.jsonl or $MENTOROS_STORE)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="Add a vocabulary word")
    a.add_argument("word")
    a.add_argument("meaning")
    a.add_argument("--difficulty", type=int, default=1)
    a.set_defaults(func=_cmd_add)

    ans = sub.add_parser("answer", help="Record an answer for a word")
    ans.add_argument("word")
    ans.add_argument("--correct", action="store_true", help="Mark the answer correct (omit for wrong)")
    ans.add_argument("--latency-ms", dest="latency_ms", type=int, default=0)
    ans.set_defaults(func=_cmd_answer)

    rv = sub.add_parser("review", help="Show today's review queue")
    rv.set_defaults(func=_cmd_review)

    pr = sub.add_parser("profile", help="Rebuild and show the profile")
    pr.set_defaults(func=_cmd_profile)

    sd = sub.add_parser("seed", help="Load words from a JSON file (idempotent)")
    sd.add_argument("--file", default="data/seed/toefl_academic.json")
    sd.set_defaults(func=_cmd_seed)

    se = sub.add_parser("session", help="Record a study session")
    se.add_argument("action", choices=["start", "finish"])
    se.add_argument("--session-id", dest="session_id", default="")
    se.add_argument("--duration-s", dest="duration_s", type=float, default=0.0)
    se.set_defaults(func=_cmd_session)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
