"""Stop rules — when does the adaptive diagnostic end?

No fixed length. We stop when there is nothing useful left to ask (every remaining
topic is settled or out of questions) or we hit the question cap. A topic counts as
settled once we are very confident about it (see ``CONFIDENCE_STOP``, used by the
selector to drop that topic from the candidate pool).
"""

from __future__ import annotations

from mentoros.assessment.question_bank import Question

CONFIDENCE_STOP = 0.90   # stop probing a topic once we are this sure of its mastery
MAX_QUESTIONS = 60       # overall safety cap across all skills
MAX_PER_SKILL = 20       # hard cap per skill (safety; confidence usually stops earlier)
MIN_PER_SKILL = 5        # always ask at least this many before trusting the estimate
SE_STOP = 0.6            # stop a skill once the θ standard error drops below this (confident)


def should_stop(asked_count: int, next_question: Question | None) -> bool:
    return asked_count >= MAX_QUESTIONS or next_question is None
