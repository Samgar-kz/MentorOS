"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

// 127.0.0.1 (not "localhost"): on macOS localhost resolves to ::1 (IPv6) first.
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function Assessment() {
  const [step, setStep] = useState(null);     // current step (holds the question)
  const [feedback, setFeedback] = useState(null); // {correct, answer, explanation, choice}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const start = useCallback(async () => {
    setFeedback(null);
    try {
      const s = await fetch(`${API}/assessment/start`, { method: "POST" }).then((r) => r.json());
      setStep(s);
      setError(null);
    } catch (e) {
      setError(`Can't reach the API at ${API}. Is it running? (make dev)`);
    }
  }, []);

  useEffect(() => {
    start();
  }, [start]);

  async function answer(choice) {
    if (busy || feedback) return;
    setBusy(true);
    try {
      const r = await fetch(`${API}/assessment/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: step.question.id, choice }),
      }).then((r) => r.json());
      setFeedback({ correct: r.correct, answer: r.answer, explanation: r.explanation, choice });
      // stash the next step inside feedback's closure via state below
      setStep((prev) => ({ ...prev, _next: { done: r.done, question: r.question, asked_count: r.asked_count, cefr: r.cefr, knowledge: r.knowledge } }));
    } catch (e) {
      setError(`Can't reach the API at ${API}.`);
    } finally {
      setBusy(false);
    }
  }

  function next() {
    setStep(step._next);
    setFeedback(null);
  }

  const q = step?.question;
  const done = step?.done;
  const touched = (step?.knowledge || []).filter((k) => k.sample_size > 0);

  return (
    <main>
      <p style={{ marginBottom: 4 }}>
        <Link href="/plan" style={{ color: "#06c" }}>← Today</Link>
      </p>
      <h1>Level check</h1>
      <p style={{ color: "#666", marginTop: -8 }}>
        Adaptive — it asks until it&apos;s confident, then builds your plan. Your answers
        update <em>mastery</em> and <em>confidence</em> per topic.
      </p>

      {error && (
        <p style={{ background: "#fff3f3", color: "#a00", padding: 12, borderRadius: 8 }}>{error}</p>
      )}

      {/* A question */}
      {!done && q && (
        <div style={{ margin: "20px 0" }}>
          <p style={{ color: "#999", fontSize: 13 }}>
            Question {step.asked_count + 1} · {q.cefr} · honing in: {step.estimated_level}
          </p>
          <div style={{ border: "1px solid #eee", borderRadius: 12, padding: 20 }}>
            <div style={{ fontSize: 19, marginBottom: 12 }}>{q.question}</div>
            {q.choices.map((c, i) => {
              const isAnswer = feedback && i === feedback.answer;
              const isWrongPick = feedback && i === feedback.choice && !feedback.correct;
              const bg = isAnswer ? "#e6f7ef" : isWrongPick ? "#fdeaea" : "#fff";
              const border = isAnswer ? "#0a7" : isWrongPick ? "#c33" : "#ddd";
              return (
                <button
                  key={i}
                  onClick={() => answer(i)}
                  disabled={busy || !!feedback}
                  style={{
                    display: "block", width: "100%", textAlign: "left", margin: "6px 0",
                    padding: "10px 12px", borderRadius: 8, border: `1px solid ${border}`,
                    background: bg, cursor: feedback ? "default" : "pointer", fontSize: 15,
                  }}
                >
                  {c}
                </button>
              );
            })}
          </div>

          {feedback && (
            <div style={{ marginTop: 12 }}>
              <div style={{ color: feedback.correct ? "#0a7" : "#c33", fontWeight: 600 }}>
                {feedback.correct ? "Correct ✓" : "Not quite ✗"}
              </div>
              {feedback.explanation && (
                <div style={{ color: "#555", fontSize: 14, marginTop: 4 }}>{feedback.explanation}</div>
              )}
              <button onClick={next} style={{ ...btn("#06c"), marginTop: 12 }}>
                {step._next?.done ? "See result →" : "Next →"}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Result */}
      {done && (
        <div style={{ margin: "20px 0" }}>
          <div style={{ border: "1px solid #eee", borderRadius: 12, padding: 24, textAlign: "center" }}>
            <div style={{ color: "#999", fontSize: 13 }}>Estimated level</div>
            <div style={{ fontSize: 40, fontWeight: 800, margin: "2px 0" }}>{step.estimated_level}</div>
            <div style={{ color: "#666" }}>
              {step.asked_count} questions · the test honed in on your level
            </div>
          </div>

          <h2 style={{ fontSize: 16, marginTop: 20 }}>What we learned</h2>
          {touched.map((k) => (
            <div key={k.topic} style={{ margin: "10px 0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14 }}>
                <span>{k.topic.replace(/_/g, " ")}</span>
                <span style={{ color: "#888" }}>
                  mastery {Math.round(k.mastery * 100)}% · confidence {Math.round(k.confidence * 100)}%
                </span>
              </div>
              <div style={{ background: "#eee", borderRadius: 6, height: 8, marginTop: 4 }}>
                <div style={{ width: `${Math.round(k.mastery * 100)}%`, background: k.known ? "#0a7" : "#f0ad4e", height: 8, borderRadius: 6 }} />
              </div>
            </div>
          ))}

          <div style={{ display: "flex", gap: 8, marginTop: 20 }}>
            <Link href="/plan" style={{ ...btn("#0a7"), textDecoration: "none" }}>See today&apos;s plan →</Link>
            <button onClick={start} style={{ ...btn("#eee"), color: "#333" }}>Restart</button>
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
