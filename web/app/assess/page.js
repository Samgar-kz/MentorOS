"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

// 127.0.0.1 (not "localhost"): on macOS localhost resolves to ::1 (IPv6) first.
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const TIER = { 1: "Core", 2: "Academic", 3: "Advanced" };

// Pick a short diagnostic: spread across difficulty tiers, prefer unanswered words.
function pickDiagnostic(vocabulary, perTier = 4) {
  const out = [];
  for (const d of [1, 2, 3]) {
    const tier = vocabulary.filter((w) => w.difficulty === d);
    tier.sort((a, b) => a.answers - b.answers || Math.random() - 0.5);
    out.push(...tier.slice(0, perTier));
  }
  return out;
}

export default function Assess() {
  const [words, setWords] = useState([]);
  const [i, setI] = useState(0);
  const [reveal, setReveal] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [empty, setEmpty] = useState(false);

  const start = useCallback(async () => {
    try {
      const p = await fetch(`${API}/profile`).then((r) => r.json());
      const picked = pickDiagnostic(p.vocabulary || []);
      setWords(picked);
      setI(0);
      setReveal(false);
      setResult(null);
      setEmpty(picked.length === 0);
      setError(null);
    } catch (e) {
      setError(`Can't reach the API at ${API}. Is it running? (make dev)`);
    }
  }, []);

  useEffect(() => {
    start();
  }, [start]);

  async function answer(correct) {
    const w = words[i];
    try {
      await fetch(`${API}/answers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ word: w.word, correct }),
      });
    } catch (e) {
      setError(`Can't reach the API at ${API}.`);
      return;
    }
    if (i + 1 < words.length) {
      setI(i + 1);
      setReveal(false);
    } else {
      const level = await fetch(`${API}/level`).then((r) => r.json());
      setResult(level);
    }
  }

  const w = words[i];
  const done = result !== null;

  return (
    <main>
      <p style={{ marginBottom: 4 }}>
        <Link href="/" style={{ color: "#06c" }}>← Home</Link>
      </p>
      <h1>Check your level</h1>
      <p style={{ color: "#666", marginTop: -8 }}>
        A quick vocabulary check. Your level is <em>computed from your answers</em>,
        not guessed by the AI.
      </p>

      {error && (
        <p style={{ background: "#fff3f3", color: "#a00", padding: 12, borderRadius: 8 }}>{error}</p>
      )}

      {empty && !error && (
        <p style={{ background: "#fffbe6", color: "#7a5", padding: 12, borderRadius: 8 }}>
          No words yet. Run <code>make seed</code> (or add words on the Home page) first.
        </p>
      )}

      {!done && w && (
        <div style={{ margin: "24px 0" }}>
          <p style={{ color: "#999", fontSize: 13 }}>
            {i + 1} / {words.length} · {TIER[w.difficulty] || "Word"}
          </p>
          <div
            style={{
              border: "1px solid #eee",
              borderRadius: 12,
              padding: 24,
              textAlign: "center",
            }}
          >
            <div style={{ fontSize: 28, fontWeight: 600 }}>{w.word}</div>
            {reveal ? (
              <div style={{ color: "#666", marginTop: 8 }}>{w.meaning || "—"}</div>
            ) : (
              <button
                onClick={() => setReveal(true)}
                style={{ ...btn("#eee"), color: "#333", marginTop: 12 }}
              >
                Show meaning
              </button>
            )}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 16, justifyContent: "center" }}>
            <button onClick={() => answer(false)} style={btn("#c33")}>I don&apos;t know it</button>
            <button onClick={() => answer(true)} style={btn("#0a7")}>I know it</button>
          </div>
        </div>
      )}

      {done && (
        <div style={{ margin: "24px 0" }}>
          <div
            style={{
              border: "1px solid #eee",
              borderRadius: 12,
              padding: 24,
              textAlign: "center",
            }}
          >
            <div style={{ color: "#999", fontSize: 13 }}>Estimated vocabulary level</div>
            <div style={{ fontSize: 32, fontWeight: 700, margin: "6px 0" }}>{result.level}</div>
            <div style={{ color: "#666" }}>{result.note}</div>
          </div>

          <div style={{ marginTop: 16 }}>
            {result.tiers.map((t) => (
              <div key={t.difficulty} style={{ margin: "10px 0" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14 }}>
                  <span>
                    {t.label}{" "}
                    {t.solid && <span style={{ color: "#0a7" }}>✓</span>}
                  </span>
                  <span style={{ color: "#888" }}>
                    {t.answered} words · {Math.round((t.accuracy || 0) * 100)}%
                  </span>
                </div>
                <div style={{ background: "#eee", borderRadius: 6, height: 8, marginTop: 4 }}>
                  <div
                    style={{
                      width: `${Math.round((t.accuracy || 0) * 100)}%`,
                      background: t.solid ? "#0a7" : "#f0ad4e",
                      height: 8,
                      borderRadius: 6,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>

          <div style={{ display: "flex", gap: 8, marginTop: 20 }}>
            <button onClick={start} style={{ ...btn("#eee"), color: "#333" }}>Check again</button>
            <Link href="/chat" style={{ ...btn("#06c"), textDecoration: "none" }}>Ask the tutor →</Link>
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
