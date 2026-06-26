"""MentorOS — an AI tutor that never forgets.

Public API for the V1 deterministic core. The whole philosophy in three names:
`EventStore` (the only source of truth) → `build_profile` (everything is computed)
→ `build_review_queue` (today's next useful step).
"""

from mentoros.events import (
    SESSION_FINISHED,
    SESSION_STARTED,
    WORD_ADDED,
    WORD_ANSWERED,
    Event,
    EventStore,
)
from mentoros.profile import Profile, SessionSummary, build_profile, save_profile
from mentoros.review import WordState, build_review_queue, next_box

__version__ = "0.1.0"

__all__ = [
    "Event",
    "EventStore",
    "WORD_ADDED",
    "WORD_ANSWERED",
    "SESSION_STARTED",
    "SESSION_FINISHED",
    "Profile",
    "SessionSummary",
    "build_profile",
    "save_profile",
    "WordState",
    "build_review_queue",
    "next_box",
]
