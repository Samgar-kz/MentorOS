"""Review scheduling — a deterministic Leitner spaced-repetition system.

A word's box, next-due time and "mastered" flag are never stored: they are a pure
function of that word's answer history (Rule 3). Correct answers promote a word to
a longer interval; a wrong answer drops it back to box 0. The review queue for
"today" is simply the words whose computed next-due time has passed.
"""

from __future__ import annotations

from dataclasses import dataclass

DAY_SECONDS = 86_400

# Leitner box index -> interval (days) until the word is due again.
# Box 0 = brand new or just-missed (due immediately).
BOX_INTERVALS_DAYS = [0, 1, 3, 7, 16, 30]
MASTERED_BOX = len(BOX_INTERVALS_DAYS) - 1  # top box == mastered


def next_box(box: int, correct: bool) -> int:
    """Leitner transition: correct promotes one box (capped), wrong resets to 0."""
    if not correct:
        return 0
    return min(box + 1, MASTERED_BOX)


def interval_seconds(box: int) -> int:
    box = max(0, min(box, MASTERED_BOX))
    return BOX_INTERVALS_DAYS[box] * DAY_SECONDS


@dataclass
class WordState:
    """Computed state of a single vocabulary word (not stored — see build_profile)."""

    word: str
    meaning: str
    difficulty: int
    box: int
    answers: int
    correct: int
    last_answered_ts: float | None

    @property
    def mastered(self) -> bool:
        return self.box >= MASTERED_BOX

    @property
    def accuracy(self) -> float:
        return self.correct / self.answers if self.answers else 0.0

    @property
    def next_due_ts(self) -> float:
        # Never answered -> due now (0.0 sorts before any real timestamp).
        if self.last_answered_ts is None:
            return 0.0
        return self.last_answered_ts + interval_seconds(self.box)

    def is_due(self, now: float) -> bool:
        return self.next_due_ts <= now


def build_review_queue(
    words: list[WordState], now: float, include_mastered: bool = False
) -> list[WordState]:
    """Today's queue: due words, most overdue (and hardest) first.

    Mastered words still come due (every 30 days) but are excluded by default so the
    daily queue stays focused on what actually needs work.
    """
    due = [
        w for w in words
        if w.is_due(now) and (include_mastered or not w.mastered)
    ]
    # Most overdue first; ties broken by higher difficulty, then word for stability.
    due.sort(key=lambda w: (w.next_due_ts, -w.difficulty, w.word))
    return due
