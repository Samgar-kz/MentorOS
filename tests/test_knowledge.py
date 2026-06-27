"""Knowledge Projection — mastery & confidence are computed from events (Rules 3 & 6).

Mastery answers "how well do they know it?"; confidence answers "how sure are we?".
They move independently, which is the whole point.
"""

from mentoros.curriculum import Curriculum, Topic
from mentoros.events import GRAMMAR_QUESTION, PLACEMENT_PASSED, Event
from mentoros.knowledge import (
    CONFIDENCE_THRESHOLD,
    MASTERY_THRESHOLD,
    build_knowledge,
    estimate_cefr,
)

GRAPH = Curriculum([
    Topic("a", "A", "A1", "grammar", ()),
    Topic("b", "B", "A2", "grammar", ("a",)),
    Topic("c", "C", "B1", "grammar", ("b",)),
])


def ev(type, payload, ts):
    return Event(type=type, payload=payload, ts=float(ts), id=f"{type}@{ts}-{payload.get('topic')}")


def gq(topic, correct, ts):
    return ev(GRAMMAR_QUESTION, {"topic": topic, "correct": correct}, ts)


def answers(topic, n_correct, n_wrong, start=1):
    out = []
    ts = start
    for _ in range(n_correct):
        out.append(gq(topic, True, ts)); ts += 1
    for _ in range(n_wrong):
        out.append(gq(topic, False, ts)); ts += 1
    return out


def test_no_evidence_is_half_mastery_zero_confidence():
    k = build_knowledge([], GRAPH)["a"]
    assert k.mastery == 0.5
    assert k.confidence == 0.0
    assert k.sample_size == 0
    assert k.known is False


def test_few_correct_high_mastery_but_low_confidence():
    # The "95% / 20%" case: right so far, but we've barely seen them.
    k = build_knowledge(answers("a", 3, 0), GRAPH)["a"]
    assert k.mastery >= MASTERY_THRESHOLD          # looks good...
    assert k.confidence < CONFIDENCE_THRESHOLD     # ...but we're not sure
    assert k.known is False


def test_many_correct_becomes_known():
    k = build_knowledge(answers("a", 12, 0), GRAPH)["a"]
    assert k.mastery >= MASTERY_THRESHOLD
    assert k.confidence >= CONFIDENCE_THRESHOLD
    assert k.known is True
    assert k.sample_size == 12


def test_confident_that_topic_is_not_mastered():
    # The "70% / high confidence" case: lots of data, but accuracy is low.
    k = build_knowledge(answers("a", 14, 6), GRAPH)["a"]
    assert k.mastery < MASTERY_THRESHOLD
    assert k.confidence >= CONFIDENCE_THRESHOLD
    assert k.known is False


def test_placement_makes_a_topic_known_without_real_answers():
    k = build_knowledge([ev(PLACEMENT_PASSED, {"topic": "b"}, 1)], GRAPH)
    assert k["b"].known is True
    assert k["a"].known is True          # foundation covered transitively
    assert k["b"].sample_size == 0       # placement is not a real answer


def test_placement_is_overridden_by_real_wrong_answers():
    events = [ev(PLACEMENT_PASSED, {"topic": "a"}, 1)] + answers("a", 0, 4, start=2)
    k = build_knowledge(events, GRAPH)["a"]
    assert k.known is False              # self-correcting: real failures pull it back


def test_estimate_cefr_is_a_projection():
    assert estimate_cefr(build_knowledge([], GRAPH), GRAPH) is None
    # Know a (A1) and b (A2) -> A2 reached; c (B1) still unknown.
    events = [ev(PLACEMENT_PASSED, {"topic": "b"}, 1)]
    assert estimate_cefr(build_knowledge(events, GRAPH), GRAPH) == "A2"
