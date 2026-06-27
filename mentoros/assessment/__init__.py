"""Assessment Prototype — an adaptive diagnostic over a small curated question bank.

Proves the cycle end-to-end on a tiny, real dataset (Rule 0: usage beats architecture):

    question bank ─► selector ─► ask ─► grammar_question event ─► build_knowledge ─► next

It reuses the existing Knowledge Projection (mastery + confidence) and CEFR projection
— it only adds the *question delivery* and *adaptive selection*. No IRT/θ yet; the
question bank is content (data/assessment/), easy to split into its own repo later.
"""
