"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

// 127.0.0.1 (not "localhost"): on macOS localhost resolves to ::1 (IPv6) first.
const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send(e) {
    e.preventDefault();
    const msg = input.trim();
    if (!msg || busy) return;
    setMessages((m) => [...m, { role: "user", text: msg }]);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg }),
      });
      const d = await r.json();
      setMessages((m) => [
        ...m,
        { role: "tutor", text: d.response, tutor: d.tutor, facts: d.recorded_facts || [] },
      ]);
    } catch (err) {
      setError(`Can't reach the API at ${API}. Is it running? (make dev)`);
    } finally {
      setBusy(false);
    }
  }

  const offline = messages.some((m) => m.role === "tutor" && m.tutor === "stub");

  return (
    <main>
      <p style={{ marginBottom: 4 }}>
        <Link href="/" style={{ color: "#06c" }}>← Review</Link>
      </p>
      <h1>MentorOS Chat</h1>
      <p style={{ color: "#666", marginTop: -8 }}>
        The tutor sees your computed profile, not your chat history.
      </p>

      {offline && (
        <p style={{ background: "#fffbe6", color: "#7a5", padding: 10, borderRadius: 8, fontSize: 14 }}>
          Offline tutor (stub). Set <code>OPENAI_API_KEY</code> and restart (<code>make dev</code>)
          for real responses.
        </p>
      )}
      {error && (
        <p style={{ background: "#fff3f3", color: "#a00", padding: 12, borderRadius: 8 }}>{error}</p>
      )}

      <div style={{ minHeight: 240, margin: "16px 0" }}>
        {messages.length === 0 && (
          <p style={{ color: "#999" }}>Ask anything — e.g. “I don&apos;t understand inversion.”</p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              justifyContent: m.role === "user" ? "flex-end" : "flex-start",
              margin: "8px 0",
            }}
          >
            <div
              style={{
                maxWidth: "80%",
                padding: "10px 14px",
                borderRadius: 14,
                background: m.role === "user" ? "#06c" : "#f1f1f4",
                color: m.role === "user" ? "#fff" : "#111",
                whiteSpace: "pre-wrap",
              }}
            >
              {m.text}
              {m.role === "tutor" && m.facts && m.facts.length > 0 && (
                <div style={{ marginTop: 6, fontSize: 12, color: "#0a7" }}>
                  recorded: {m.facts.map((f) => f.type).join(", ")}
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <form onSubmit={send} style={{ display: "flex", gap: 8 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={busy ? "thinking…" : "Type a message"}
          disabled={busy}
          style={{ flex: 1, padding: "10px 12px", border: "1px solid #ccc", borderRadius: 8, fontSize: 14 }}
        />
        <button
          type="submit"
          disabled={busy}
          style={{ background: "#06c", color: "#fff", border: "none", borderRadius: 8, padding: "10px 16px", cursor: "pointer" }}
        >
          Send
        </button>
      </form>
    </main>
  );
}
