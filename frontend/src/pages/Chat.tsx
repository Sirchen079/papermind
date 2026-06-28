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
    setActive(id);
    const c = await api.getConversation(id);
    setMessages(c.messages);
  }

  async function newConv() {
    const c = await api.createConversation();
    await loadConvs();
    await openConv(c.id);
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
          // drop the empty placeholder
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
    <div className="flex gap-4 h-[80vh]">
      <aside className="w-52 shrink-0 bg-white rounded-lg shadow p-3 overflow-auto">
        <button onClick={newConv} className="w-full bg-slate-900 text-white rounded px-3 py-1.5 text-sm mb-3">
          + New
        </button>
        <div className="space-y-1">
          {convs.map((c) => (
            <button
              key={c.id}
              onClick={() => openConv(c.id)}
              className={`block w-full text-left text-sm px-2 py-1.5 rounded truncate ${
                active === c.id ? "bg-slate-200" : "hover:bg-slate-100"
              }`}
            >
              {c.title} #{c.id}
            </button>
          ))}
        </div>
      </aside>

      <section className="flex-1 flex flex-col bg-white rounded-lg shadow">
        {!active ? (
          <div className="flex-1 flex items-center justify-center text-slate-400">
            Start a new conversation
          </div>
        ) : (
          <>
            <div className="flex-1 overflow-auto p-4 space-y-3">
              {messages.map((m, i) => (
                <div key={i} className={m.role === "user" ? "text-right" : ""}>
                  <div
                    className={`inline-block max-w-[80%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap ${
                      m.role === "user" ? "bg-slate-900 text-white" : "bg-slate-100"
                    }`}
                  >
                    {m.content || (busy && m.role === "assistant" ? (
                      <span className="text-slate-400">thinking…</span>
                    ) : "")}
                  </div>
                </div>
              ))}
              <div ref={endRef} />
            </div>
            {error && <div className="text-red-600 text-sm px-4">{error}</div>}
            <div className="border-t p-3 flex gap-2">
              <input
                className="flex-1 border rounded px-3 py-1.5 text-sm"
                placeholder="Ask about your library…"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && send()}
              />
              <button
                onClick={send}
                disabled={busy}
                className="bg-slate-900 text-white px-4 py-1.5 rounded text-sm disabled:opacity-50"
              >
                Send
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
