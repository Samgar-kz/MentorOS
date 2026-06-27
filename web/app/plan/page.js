"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

// 127.0.0.1 (not "localhost"): on macOS localhost resolves to ::1 (IPv6) first.
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const STATUS_STYLE = {
  learning: { label: "in progress", color: "#f0ad4e" },
  available: { label: "ready", color: "#0a7" },
  mastered: { label: "mastered", color: "#06c" },
  locked: { label: "locked", color: "#bbb" },
};

export default function Plan() {
  const [plan, setPlan] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const p = await fetch(`${API}/plan`).then((r) => r.json());
      setPlan(p);
      setError(null);
    } catch (e) {
      setError(`Can't reach the API at ${API}. Is it running? (make dev)`);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function answerTopic(topicId, correct) {
    setBusy(true);
    try {
      await fetch(`${API}/topics/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: topicId, correct }),
      });
      await refresh(); // the plan recomputes itself — mastery may unlock the next topic
    } finally {
      setBusy(false);
    }
  }

  const action = plan?.next_action;
  const lesson = plan?.focus?.[0];
  const upcoming = plan?.focus?.slice(1) || [];

  return (
    <main>
      <p style={{ marginBottom: 4 }}>
        <Link href="/" style={{ color: "#06c" }}>← Home</Link>
      </p>
      <h1>Today</h1>
      <p style={{ color: "#666", marginTop: -8 }}>
        MentorOS decides the next most useful step. The plan is <em>computed</em>, never stored.
      </p>

      {error && (
        <p style={{ background: "#fff3f3", color: "#a00", padding: 12, borderRadius: 8 }}>{error}</p>
      )}

      {/* New student: no plan until the level check is done. */}
      {plan && !plan.onboarded && (
        <div style={{ border: "1px solid #cde3ff", background: "#eef6ff", borderRadius: 12, padding: 24, margin: "16px 0" }}>
          <div style={{ fontSize: 20, fontWeight: 700 }}>👋 Welcome to MentorOS</div>
          <p style={{ color: "#555", marginTop: 6 }}>
            Before building your plan, let&apos;s find your level — it takes about a minute.
            Your plan is then created from what you already know, so you don&apos;t start at A1.
          </p>
          <Link href="/placement" style={{ ...btn("#06c"), textDecoration: "none", display: "inline-block" }}>
            Check my level →
          </Link>
        </div>
      )}

      {plan && plan.onboarded && (
        <>
          {/* The single most useful step right now */}
          {action && (
            <div style={{ background: "#0a7", color: "#fff", borderRadius: 12, padding: 20, margin: "16px 0" }}>
              <div style={{ fontSize: 12, opacity: 0.8, textTransform: "uppercase", letterSpacing: 1 }}>
                Next step
              </div>
              <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{action.detail}</div>
              {action.kind === "review" && (
                <Link href="/" style={{ color: "#fff", textDecoration: "underline", fontSize: 14 }}>
                  Go to review →
                </Link>
              )}
            </div>
          )}

          {/* Today's lesson — the topic the planner chose */}
          {lesson ? (
            <div style={{ border: "1px solid #eee", borderRadius: 12, padding: 20, margin: "16px 0" }}>
              <div style={{ color: "#999", fontSize: 13 }}>
                Today&apos;s lesson · {lesson.level} ·{" "}
                <span style={{ color: STATUS_STYLE[lesson.status]?.color }}>
                  {STATUS_STYLE[lesson.status]?.label}
                </span>
              </div>
              <div style={{ fontSize: 20, fontWeight: 600, margin: "4px 0 2px" }}>{lesson.title}</div>
              <div style={{ color: "#888", fontSize: 13 }}>
                Mastery {lesson.box}/3 · {lesson.answers} attempt{lesson.answers === 1 ? "" : "s"}
              </div>

              <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
                <Link href="/chat" style={{ ...btn("#06c"), textDecoration: "none" }}>
                  Learn with tutor →
                </Link>
                <button disabled={busy} onClick={() => answerTopic(lesson.id, true)} style={btn("#0a7")}>
                  I got it ✓
                </button>
                <button disabled={busy} onClick={() => answerTopic(lesson.id, false)} style={btn("#c33")}>
                  Missed it ✗
                </button>
              </div>
              <p style={{ color: "#aaa", fontSize: 12, marginTop: 8 }}>
                3 correct in a row masters a topic and unlocks the next one.
              </p>
            </div>
          ) : (
            <p style={{ color: "#666" }}>No topic available right now. 🎉</p>
          )}

          {/* What's coming up next on the path */}
          {upcoming.length > 0 && (
            <>
              <h2 style={{ fontSize: 16 }}>Coming up</h2>
              <ul style={{ listStyle: "none", padding: 0 }}>
                {upcoming.map((t) => (
                  <li key={t.id} style={{ padding: "8px 12px", border: "1px solid #f0f0f0", borderRadius: 8, marginBottom: 6, color: "#555" }}>
                    {t.title} <span style={{ color: "#bbb", fontSize: 12 }}>{t.level}</span>
                  </li>
                ))}
              </ul>
            </>
          )}

          {/* Footer stats */}
          <p style={{ color: "#888", fontSize: 13, marginTop: 20 }}>
            Level: <strong>{plan.cefr_level || "—"}</strong> · Grammar:{" "}
            {plan.topics_mastered}/{plan.topics_total} mastered · {plan.review_due} words due ·{" "}
            <Link href="/placement" style={{ color: "#06c" }}>re-check level</Link>
          </p>
        </>
      )}
    </main>
  );
}

const btn = (bg) => ({
  background: bg,
  color: "#fff",
  border: "none",
  borderRadius: 8,
  padding: "10px 16px",
  cursor: "pointer",
  fontSize: 15,
});
