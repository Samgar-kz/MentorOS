"use client";

import Link from "next/link";
import { useState } from "react";

// 127.0.0.1 (not "localhost"): on macOS localhost resolves to ::1 (IPv6) first.
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

// One representative card per CEFR level — "can you confidently use this?"
const LEVELS = [
  { level: "A1", title: "Beginner", examples: ["I work in an office.", "She has a car.", "There are two books on the table."] },
  { level: "A2", title: "Elementary", examples: ["I visited Rome last year.", "She is cooking dinner now.", "This box is bigger than that one."] },
  { level: "B1", title: "Intermediate", examples: ["I have lived here since 2019.", "If I had more time, I would learn piano.", "The email was sent yesterday."] },
  { level: "B2", title: "Upper-Intermediate", examples: ["She told me she had already left.", "By the time we arrived, the show had started.", "If he had studied, he would have passed."] },
  { level: "C1", title: "Advanced", examples: ["Never have I seen such dedication.", "Not only did she win, but she also set a record.", "The implementation of the policy proved difficult."] },
];

export default function Placement() {
  const [i, setI] = useState(0);
  const [known, setKnown] = useState([]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function answer(canDo) {
    const lvl = LEVELS[i].level;
    const nextKnown = canDo ? [...known, lvl] : known;
    setKnown(nextKnown);
    if (i + 1 < LEVELS.length) {
      setI(i + 1);
      return;
    }
    try {
      const r = await fetch(`${API}/placement`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ known_levels: nextKnown }),
      }).then((r) => r.json());
      setResult(r);
    } catch (e) {
      setError(`Can't reach the API at ${API}. Is it running? (make dev)`);
    }
  }

  function restart() {
    setI(0);
    setKnown([]);
    setResult(null);
    setError(null);
  }

  const card = LEVELS[i];

  return (
    <main>
      <p style={{ marginBottom: 4 }}>
        <Link href="/plan" style={{ color: "#06c" }}>← Today</Link>
      </p>
      <h1>Check your level</h1>
      <p style={{ color: "#666", marginTop: -8 }}>
        Tell MentorOS what you already know, so your plan starts at the right level —
        not at A1. You can always re-do this.
      </p>

      {error && (
        <p style={{ background: "#fff3f3", color: "#a00", padding: 12, borderRadius: 8 }}>{error}</p>
      )}

      {!result && card && (
        <div style={{ margin: "20px 0" }}>
          <p style={{ color: "#999", fontSize: 13 }}>
            {i + 1} / {LEVELS.length} · {card.level} · {card.title}
          </p>
          <div style={{ border: "1px solid #eee", borderRadius: 12, padding: 20 }}>
            <div style={{ color: "#666", marginBottom: 8 }}>Can you confidently use sentences like these?</div>
            {card.examples.map((ex) => (
              <div key={ex} style={{ fontSize: 17, margin: "6px 0" }}>“{ex}”</div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
            <button onClick={() => answer(false)} style={btn("#c33")}>Not yet</button>
            <button onClick={() => answer(true)} style={btn("#0a7")}>Yes, I can ✓</button>
          </div>
        </div>
      )}

      {result && (
        <div style={{ margin: "20px 0" }}>
          <div style={{ border: "1px solid #eee", borderRadius: 12, padding: 24, textAlign: "center" }}>
            <div style={{ color: "#999", fontSize: 13 }}>Your level</div>
            <div style={{ fontSize: 40, fontWeight: 800, margin: "2px 0" }}>{result.level}</div>
            <div style={{ color: "#666", marginTop: 6 }}>
              {result.placed.length > 0
                ? `${result.placed.length} topics marked as known. Your plan now starts where you are.`
                : "Starting from the beginning — your plan begins at A1."}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 20 }}>
            <Link href="/plan" style={{ ...btn("#0a7"), textDecoration: "none" }}>See today&apos;s plan →</Link>
            <button onClick={restart} style={{ ...btn("#eee"), color: "#333" }}>Re-do</button>
          </div>
        </div>
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
