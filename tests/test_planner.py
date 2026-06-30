"""Planner v2 is a deterministic projection of events + the curriculum graph (Rule 5).

No plan is stored: every assertion here builds the plan fresh from an event list.
"""

import pytest

from mentoros.curriculum import Curriculum, Topic, load_curriculum
from mentoros.events import (
    ASSESSMENT_COMPLETED,
    GRAMMAR_QUESTION,
    PLACEMENT_PASSED,
    WORD_ADDED,
    WORD_ANSWERED,
    Event,
)
from mentoros.planner import (
    STATUS_AVAILABLE,
    STATUS_LEARNING,
    STATUS_LOCKED,
    STATUS_MASTERED,
    build_topic_states,
    next_action,
    plan_today,
)

NOW = 1000.0  # close to the synthetic event timestamps, so the forgetting curve is a no-op here


def ev(type, payload, ts):
    return Event(type=type, payload=payload, ts=float(ts), id=f"{type}@{ts}-{payload.get('topic') or payload.get('word')}")


def gq(topic, correct, ts):
    return ev(GRAMMAR_QUESTION, {"topic": topic, "correct": correct}, ts)


def placed(topic, ts):
    return ev(PLACEMENT_PASSED, {"topic": topic}, ts)


# A tiny graph: a -> b -> c (b requires a, c requires b).
GRAPH = Curriculum([
    Topic("a", "A", "A1", "grammar", ()),
    Topic("b", "B", "A2", "grammar", ("a",)),
    Topic("c", "C", "B1", "grammar", ("b",)),
])


def master(topic, start_ts=1):
    # Placement is the clean way to mark a topic known in tests (see test_knowledge.py
    # for the answer-driven path). It marks the topic and its prerequisites known.
    return [placed(topic, start_ts)]


# --- curriculum validation -------------------------------------------------- #
def test_unknown_prerequisite_is_rejected():
    with pytest.raises(ValueError):
        Curriculum([Topic("x", "X", "A1", "grammar", ("missing",))])


def test_cycle_is_rejected():
    with pytest.raises(ValueError):
        Curriculum([
            Topic("p", "P", "A1", "grammar", ("q",)),
            Topic("q", "Q", "A1", "grammar", ("p",)),
        ])


def test_shipped_curriculum_loads_and_is_acyclic():
    cur = load_curriculum()
    assert len(cur.topics) >= 20
    assert "inversion" in cur.by_id  # the C1 topic we discussed


# --- topic states ----------------------------------------------------------- #
def test_fresh_graph_only_roots_available():
    states = build_topic_states([], GRAPH, NOW)
    assert states["a"].status == STATUS_AVAILABLE   # no prereqs
    assert states["b"].status == STATUS_LOCKED      # needs a
    assert states["c"].status == STATUS_LOCKED


def test_mastering_a_unlocks_b():
    states = build_topic_states(master("a"), GRAPH, NOW)
    assert states["a"].status == STATUS_MASTERED
    assert states["b"].status == STATUS_AVAILABLE
    assert states["c"].status == STATUS_LOCKED


def test_in_progress_topic_is_learning():
    # one correct answer: started, but too little evidence to be "known"
    states = build_topic_states([gq("a", True, 1)], GRAPH, NOW)
    assert states["a"].status == STATUS_LEARNING
    assert states["a"].sample_size == 1


def test_a_few_correct_is_not_yet_known():
    # High mastery but low confidence -> still learning, not mastered (Knowledge model).
    events = [gq("a", True, 1), gq("a", True, 2), gq("a", True, 3)]
    states = build_topic_states(events, GRAPH, NOW)
    assert states["a"].status == STATUS_LEARNING
    assert states["a"].mastery >= 0.7


# --- next action ------------------------------------------------------------ #
def test_next_action_prioritizes_due_reviews():
    states = build_topic_states([], GRAPH, NOW)
    from mentoros.planner import focus_topics

    action = next_action(review_due=4, focus=focus_topics(GRAPH, states))
    assert action.kind == "review"
    assert action.count == 4


def test_next_action_learns_when_nothing_due():
    states = build_topic_states([], GRAPH, NOW)
    from mentoros.planner import focus_topics

    action = next_action(review_due=0, focus=focus_topics(GRAPH, states))
    assert action.kind == "learn"
    assert action.topic_id == "a"  # the only unlocked topic


# --- end-to-end plan -------------------------------------------------------- #
def test_plan_today_is_deterministic_and_unstored():
    events = master("a", start_ts=1)
    p1 = plan_today(events, GRAPH, now=NOW)
    p2 = plan_today(events, GRAPH, now=NOW)
    assert p1.to_dict() == p2.to_dict()
    assert p1.topics_mastered == 1
    assert p1.focus[0]["id"] == "b"  # next learnable after mastering a


def test_plan_advances_as_events_accumulate():
    cur = GRAPH
    before = plan_today([], cur, now=NOW)
    after = plan_today(master("a"), cur, now=NOW)
    assert before.focus[0]["id"] == "a"
    assert after.focus[0]["id"] == "b"  # the plan "changed" with zero stored state


# --- placement (auto level placement) --------------------------------------- #
def test_placement_masters_topic_and_its_prerequisites():
    # Placing into "b" covers b AND its prerequisite a; c (requires b) becomes available.
    states = build_topic_states([placed("b", 1)], GRAPH, NOW)
    assert states["a"].status == STATUS_MASTERED  # foundation covered, not directly tested
    assert states["b"].status == STATUS_MASTERED
    assert states["c"].status == STATUS_AVAILABLE


def test_placement_is_self_correcting():
    # Placed into b, then got b wrong repeatedly -> b resurfaces; a (placed) stays known.
    events = [placed("b", 1), gq("b", False, 2), gq("b", False, 3), gq("b", False, 4)]
    states = build_topic_states(events, GRAPH, NOW)
    assert states["a"].status == STATUS_MASTERED
    assert states["b"].status == STATUS_LEARNING
    assert states["c"].status == STATUS_LOCKED  # b no longer known -> c relocks


def test_placement_by_level_starts_plan_above_a1():
    cur = load_curriculum()
    a1_a2 = [t for t in cur.topics if t.level in ("A1", "A2")]
    events = [placed(t.id, i + 1) for i, t in enumerate(a1_a2)]
    plan = plan_today(events, cur, now=NOW)
    assert plan.topics_mastered == len(a1_a2)
    # The focus has moved off the A1 roots onto B1 material.
    assert all(f["level"] != "A1" for f in plan.focus)
    assert any(f["level"] == "B1" for f in plan.focus)


# --- onboarding gate -------------------------------------------------------- #
def test_new_student_is_not_onboarded():
    plan = plan_today([], GRAPH, now=NOW)
    assert plan.onboarded is False
    assert plan.cefr_level is None


def test_assessment_completed_marks_onboarded_but_cefr_is_computed():
    # Onboarding is a fact (assessment_completed); CEFR is a projection of knowledge,
    # so with no actual evidence yet it stays None even though the student is onboarded.
    events = [ev(ASSESSMENT_COMPLETED, {"level": "B1", "known_levels": ["A1", "A2", "B1"]}, 5)]
    plan = plan_today(events, GRAPH, now=NOW)
    assert plan.onboarded is True
    assert plan.cefr_level is None
