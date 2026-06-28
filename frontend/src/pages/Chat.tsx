import { useEffect, useRef, useState } from "react";
import { api } from "../api";

interface Conv {
  id: number;
  title: string;
}
interface Msg {
  role: string;
  content: string;
  model: string;
}

export default function Chat() {
  const [convs, setConvs] = useState<Conv[]>([]);
  const [active, setActive] = useState<number | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  async function loadConvs() {
    try {
      setConvs(await api.listConversations());
    } catch {
      /* ignore */
    }
  }
  useEffect(() => {
    loadConvs();
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function openConv(id: number) {
    try {
      setActive(id);
      const c = await api.getConversation(id);
      setMessages(c.messages);
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function newConv() {
    try {
      const c = await api.createConversation();
      await loadConvs();
      await openConv(c.id);
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function send() {
    if (!active || !input.trim() || busy) return;
    const text = input;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: text, model: "" }]);
    // assistant placeholder streamed into incrementally
    setMessages((m) => [...m, { role: "assistant", content: "", model: "" }]);
    setBusy(true);
    setError(null);
    try {
      let last = "";
      for await (const { event, data } of api.streamMessage(active, text)) {
        if (event === "delta") {
          last += data.content;
          setMessages((m) => {
            const copy = [...m];
            copy[copy.length - 1] = { ...copy[copy.length - 1], content: last };
            return copy;
          });
        } else if (event === "done") {
          // authoritative final content + model, persisted server-side
          setMessages((m) => {
            const copy = [...m];
            copy[copy.length - 1] = { role: "assistant", content: data.content, model: data.model };
            return copy;
          });
        } else if (event === "error") {
          setError(data.message ?? "stream error");
          setMessages((m) => (m[m.length - 1]?.content === "" ? m.slice(0, -1) : m));
        }
      }
    } catch (e: any) {
      setError(e.message);
      setMessages((m) => (m[m.length - 1]?.content === "" ? m.slice(0, -1) : m));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-[78vh] gap-4">
      <aside className="card-tight flex w-56 shrink-0 flex-col overflow-hidden p-0">
        <div className="p-3" style={{ borderBottom: "1px solid var(--border)" }}>
          <button onClick={newConv} className="btn-primary w-full">
            + New conversation
          </button>
        </div>
        <div className="flex-1 space-y-1 overflow-auto p-2">
          {convs.length === 0 && (
            <p className="px-2 py-4 text-center text-xs" style={{ color: "var(--faint)" }}>
              No conversations yet.
            </p>
          )}
          {convs.map((c) => {
            const isActive = active === c.id;
            return (
              <button
                key={c.id}
                onClick={() => openConv(c.id)}
                className="block w-full truncate rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors"
                style={
                  isActive
                    ? { backgroundColor: "var(--accent-soft)", color: "var(--text)" }
                    : { color: "var(--muted)" }
                }
                onMouseEnter={(e) => {
                  if (!isActive) e.currentTarget.style.backgroundColor = "var(--surface-2)";
                }}
                onMouseLeave={(e) => {
                  if (!isActive) e.currentTarget.style.backgroundColor = "transparent";
                }}
              >
                {c.title} <span style={{ color: "var(--faint)" }}>#{c.id}</span>
              </button>
            );
          })}
        </div>
      </aside>

      <section className="card flex flex-1 flex-col overflow-hidden p-0">
        {!active ? (
          <div className="flex flex-1 items-center justify-center" style={{ color: "var(--faint)" }}>
            Start a new conversation
          </div>
        ) : (
          <>
            <div className="flex-1 space-y-3 overflow-auto p-4">
              {messages.map((m, i) => (
                <div key={i} className={m.role === "user" ? "text-right" : ""}>
                  <div
                    className="inline-block max-w-[80%] whitespace-pre-wrap rounded-xl px-3.5 py-2 text-sm leading-relaxed"
                    style={
                      m.role === "user"
                        ? { backgroundColor: "var(--accent)", color: "var(--accent-contrast)" }
                        : { backgroundColor: "var(--surface-2)" }
                    }
                  >
                    {m.content ||
                      (busy && m.role === "assistant" ? (
                        <span style={{ color: "var(--faint)" }}>thinking…</span>
                      ) : (
                        ""
                      ))}
                  </div>
                </div>
              ))}
              <div ref={endRef} />
            </div>
            {error && (
              <div className="px-4 py-2 text-sm" style={{ color: "var(--danger)" }}>
                {error}
              </div>
            )}
            <div className="flex gap-2 p-3" style={{ borderTop: "1px solid var(--border)" }}>
              <input
                className="input"
                placeholder="Ask about your library…"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && send()}
              />
              <button onClick={send} disabled={busy} className="btn-primary shrink-0 px-5">
                Send
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
