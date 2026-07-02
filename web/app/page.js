"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

// Use 127.0.0.1 (not "localhost"): on macOS localhost resolves to ::1 (IPv6) first,
// but uvicorn binds IPv4 — a browser fetch to localhost:8000 would hit ::1 and fail.
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function Home() {
  const [queue, setQueue] = useState([]);
  const [profile, setProfile] = useState(null);
  const [word, setWord] = useState("");
  const [meaning, setMeaning] = useState("");
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [rv, pr] = await Promise.all([
        fetch(`${API}/review`).then((r) => r.json()),
        fetch(`${API}/profile`).then((r) => r.json()),
      ]);
      setQueue(rv.queue || []);
      setProfile(pr);
      setError(null);
    } catch (e) {
      setError(`Can't reach the API at ${API}. Is it running? (uvicorn mentoros.api:app)`);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function addWord(e) {
    e.preventDefault();
    if (!word.trim()) return;
    await fetch(`${API}/words`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ word: word.trim(), meaning: meaning.trim() }),
    });
    setWord("");
    setMeaning("");
    refresh();
  }

  async function answer(w, correct) {
    await fetch(`${API}/answers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ word: w, correct }),
    });
    refresh();
  }

  return (
    <main>
      <h1>MentorOS</h1>
      <p style={{ color: "#666", marginTop: -8 }}>The next most useful step, today.</p>
      <div style={{ display: "flex", gap: 8, margin: "12px 0 20px", flexWrap: "wrap" }}>
        <Link href="/plan" style={navBtn("#0a7")}>Today&apos;s plan</Link>
        <Link href="/assessment" style={navBtn("#444")}>Check your level</Link>
        <Link href="/chat" style={navBtn("#06c")}>Chat with tutor</Link>
      </div>

      {error && (
        <p style={{ background: "#fff3f3", color: "#a00", padding: 12, borderRadius: 8 }}>{error}</p>
      )}

      {profile && (
        <p style={{ color: "#444" }}>
          {profile.word_count} words · {profile.mastered_count} mastered ·{" "}
          {profile.due_count} due today · {Math.round((profile.accuracy || 0) * 100)}% accuracy
        </p>
      )}

      <h2>Today&apos;s review</h2>
      {queue.length === 0 ? (
        <p style={{ color: "#666" }}>Nothing due. 🎉 Add a word below.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0 }}>
          {queue.map((w) => (
            <li
              key={w.word}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "10px 12px",
                border: "1px solid #eee",
                borderRadius: 8,
                marginBottom: 8,
              }}
            >
              <span>
                <strong>{w.word}</strong>
                <span style={{ color: "#888" }}> — {w.meaning || "?"} </span>
                <span style={{ color: "#bbb", fontSize: 12 }}>box {w.box}</span>
              </span>
              <span>
                <button onClick={() => answer(w.word, true)} style={btn("#0a7")}>
                  ✓
                </button>
                <button onClick={() => answer(w.word, false)} style={btn("#c33")}>
                  ✗
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <h2>Add a word</h2>
      <form onSubmit={addWord} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input
          value={word}
          onChange={(e) => setWord(e.target.value)}
          placeholder="word"
          style={input}
        />
        <input
          value={meaning}
          onChange={(e) => setMeaning(e.target.value)}
          placeholder="meaning"
          style={{ ...input, flex: 1 }}
        />
        <button type="submit" style={btn("#06c")}>
          Add
        </button>
      </form>
    </main>
  );
}

const input = {
  padding: "8px 10px",
  border: "1px solid #ccc",
  borderRadius: 8,
  fontSize: 14,
};

const btn = (bg) => ({
  background: bg,
  color: "#fff",
  border: "none",
  borderRadius: 8,
  padding: "8px 12px",
  marginLeft: 6,
  cursor: "pointer",
  fontSize: 14,
});

const navBtn = (bg) => ({
  background: bg,
  color: "#fff",
  borderRadius: 8,
  padding: "10px 16px",
  fontSize: 15,
  textDecoration: "none",
});
