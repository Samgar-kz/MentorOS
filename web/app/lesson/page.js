"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

// 127.0.0.1 (not "localhost"): on macOS localhost resolves to ::1 (IPv6) first.
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const KIND_LABEL = {
  warm_up: "Warm-up", explanation: "Explanation", guided: "Guided practice",
  independent: "Independent practice", quiz: "Quiz", summary: "Summary",
};
const EXERCISE = new Set(["guided", "independent", "quiz"]);

export default function LessonPage() {
  const [lesson, setLesson] = useState(null);
  const [i, setI] = useState(0);
  const [feedback, setFeedback] = useState(null); // {correct, answer, explanation, choice}
  const [result, setResult] = useState(null);      // knowledge after finishing
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [empty, setEmpty] = useState(false);

  const start = useCallback(async () => {
    setI(0); setFeedback(null); setResult(null); setError(null); setEmpty(false);
    try {
      const d = await fetch(`${API}/lesson/start`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      }).then((r) => r.json());
      if (!d.lesson) setEmpty(true);
      else setLesson(d.lesson);
    } catch (e) {
      setError(`Can't reach the API at ${API}. Is it running? (make dev)`);
    }
  }, []);

  useEffect(() => { start(); }, [start]);

  async function answer(choice) {
    if (busy || feedback) return;
    setBusy(true);
    try {
      const r = await fetch(`${API}/lesson/answer`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: step.question.id, choice }),
      }).then((r) => r.json());
      setFeedback({ ...r, choice });
    } catch (e) {
      setError(`Can't reach the API at ${API}.`);
    } finally { setBusy(false); }
  }

  async function finish() {
    setBusy(true);
    try {
      const r = await fetch(`${API}/lesson/finish`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: lesson.topic }),
      }).then((r) => r.json());
      setResult(r.knowledge);
    } finally { setBusy(false); }
  }

  function next() {
    setFeedback(null);
    if (i + 1 < lesson.steps.length) setI(i + 1);
    else finish();
  }

  if (empty) {
    return (
      <main>
        <p><Link href="/plan" style={{ color: "#06c" }}>← Today</Link></p>
        <h1>Lesson</h1>
        <p style={{ color: "#666" }}>Nothing to learn right now. 🎉 Check your level or come back later.</p>
      </main>
    );
  }
  if (error) return <main><p style={{ background: "#fff3f3", color: "#a00", padding: 12, borderRadius: 8 }}>{error}</p></main>;
  if (!lesson) return <main><p style={{ color: "#999" }}>Loading…</p></main>;

  const step = lesson.steps[i];
  const isExercise = EXERCISE.has(step?.kind);

  return (
    <main>
      <p style={{ marginBottom: 4 }}><Link href="/plan" style={{ color: "#06c" }}>← Today</Link></p>
      <h1>{lesson.title} <span style={{ color: "#bbb", fontSize: 16 }}>{lesson.level}</span></h1>
      <p style={{ color: "#666", marginTop: -8 }}>
        ~{lesson.estimated_minutes} min · target mastery {Math.round(lesson.target_mastery * 100)}%
      </p>

      {/* progress dots */}
      {!result && (
        <div style={{ display: "flex", gap: 4, margin: "10px 0 18px" }}>
          {lesson.steps.map((s, idx) => (
            <div key={idx} style={{ flex: 1, height: 6, borderRadius: 3, background: idx <= i ? "#0a7" : "#eee" }} />
          ))}
        </div>
      )}

      {!result && (
        <div style={{ border: "1px solid #eee", borderRadius: 12, padding: 20 }}>
          <div style={{ color: "#999", fontSize: 13, marginBottom: 8 }}>{KIND_LABEL[step.kind]}</div>

          {!isExercise && (
            <>
              <div style={{ whiteSpace: "pre-wrap", fontSize: 16, lineHeight: 1.5 }}>{step.prose}</div>
              <button onClick={next} disabled={busy} style={{ ...btn("#06c"), marginTop: 16 }}>
                {i + 1 < lesson.steps.length ? "Continue →" : "Finish"}
              </button>
            </>
          )}

          {isExercise && (
            <>
              <div style={{ fontSize: 18, marginBottom: 12 }}>{step.question.question}</div>
              {step.question.choices.map((c, idx) => {
                const isAns = feedback && idx === feedback.answer;
                const isWrong = feedback && idx === feedback.choice && !feedback.correct;
                return (
                  <button key={idx} onClick={() => answer(idx)} disabled={busy || !!feedback}
                    style={{
                      display: "block", width: "100%", textAlign: "left", margin: "6px 0", padding: "10px 12px",
                      borderRadius: 8, fontSize: 15, cursor: feedback ? "default" : "pointer",
                      border: `1px solid ${isAns ? "#0a7" : isWrong ? "#c33" : "#ddd"}`,
                      background: isAns ? "#e6f7ef" : isWrong ? "#fdeaea" : "#fff",
                    }}>
                    {c}
                  </button>
                );
              })}
              {feedback && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ color: feedback.correct ? "#0a7" : "#c33", fontWeight: 600 }}>
                    {feedback.correct ? "Correct ✓" : "Not quite ✗"}
                  </div>
                  {feedback.explanation && <div style={{ color: "#555", fontSize: 14, marginTop: 4 }}>{feedback.explanation}</div>}
                  <button onClick={next} disabled={busy} style={{ ...btn("#06c"), marginTop: 12 }}>
                    {i + 1 < lesson.steps.length ? "Continue →" : "Finish"}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {result && (
        <div style={{ border: "1px solid #eee", borderRadius: 12, padding: 24, textAlign: "center" }}>
          <div style={{ fontSize: 22, fontWeight: 700 }}>Lesson complete ✓</div>
          <p style={{ color: "#666", marginTop: 6 }}>
            {lesson.title}: mastery {Math.round(lesson.mastery * 100)}% → <strong>{Math.round(result.mastery * 100)}%</strong>{" "}
            · confidence {Math.round(lesson.confidence * 100)}% → <strong>{Math.round(result.confidence * 100)}%</strong>
            {result.known && <span style={{ color: "#0a7" }}> · mastered</span>}
          </p>
          <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 16 }}>
            <Link href="/plan" style={{ ...btn("#0a7"), textDecoration: "none" }}>Today&apos;s plan →</Link>
            <button onClick={start} style={btn("#06c")}>Next lesson</button>
          </div>
        </div>
      )}
    </main>
  );
}

const btn = (bg) => ({
  background: bg, color: "#fff", border: "none", borderRadius: 8,
  padding: "10px 16px", cursor: "pointer", fontSize: 15,
});
