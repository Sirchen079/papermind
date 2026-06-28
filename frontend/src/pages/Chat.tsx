import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, type Source } from "../api";

interface Conv {
  id: number;
  title: string;
}
interface ToolStep {
  name: string;
  args: Record<string, unknown>;
  result: string;
  ok: boolean;
}
interface Msg {
  id: number;
  role: string;
  content: string;
  model: string;
  sources?: Source[];
  tools?: ToolStep[];
  stopped?: boolean;
}

// Stable, monotonically-increasing key per message so React can reconcile the
// streamed list correctly (index keys break when the tail is replaced/removed).
let nextMsgId = 0;
function mk(
  role: string,
  content = "",
  model = "",
  extra: Partial<Msg> = {},
): Msg {
  return { id: nextMsgId++, role, content, model, ...extra };
}

/** Friendly arg summary for the tool card header, e.g. `search_library("attention")`. */
function argSummary(name: string, args: Record<string, unknown>): string {
  const vals = Object.values(args ?? {});
  if (!vals.length) return "";
  const first = vals[0];
  const shown = typeof first === "string" ? `"${first}"` : JSON.stringify(first);
  return vals.length > 1 ? `(${shown}, …)` : `(${shown})`;
}

export default function Chat({
  activeConv,
  setActiveConv,
  onOpenPaper,
}: {
  activeConv: number | null;
  setActiveConv: (id: number | null) => void;
  onOpenPaper: (id: number) => void;
}) {
  const [convs, setConvs] = useState<Conv[]>([]);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

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

  // Load the active conversation whenever App says it changed (this also
  // restores the user's place after navigating away and back — P5).
  useEffect(() => {
    if (activeConv == null) {
      setMessages([]);
      return;
    }
    let alive = true;
    api
      .getConversation(activeConv)
      .then((c) => {
        if (alive)
          setMessages(
            c.messages.map((m) =>
              mk(m.role, m.content, m.model, { sources: m.sources ?? [] }),
            ),
          );
      })
      .catch((e: any) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [activeConv]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-grow the textarea up to a few lines, then scroll.
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
  }, [input]);

  async function newConv() {
    if (busy) return; // switching mid-stream would corrupt the in-flight view
    try {
      const c = await api.createConversation();
      await loadConvs();
      setActiveConv(c.id); // triggers the loader effect above
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function delConv(id: number) {
    try {
      await api.deleteConversation(id);
      if (activeConv === id) setActiveConv(null);
      await loadConvs();
    } catch (e: any) {
      setError(e.message);
    }
  }

  function startRename(c: Conv) {
    setEditingId(c.id);
    setEditText(c.title);
  }

  async function commitRename(id: number) {
    const title = editText.trim();
    setEditingId(null);
    if (!title) return;
    try {
      await api.renameConversation(id, title);
      await loadConvs();
    } catch (e: any) {
      setError(e.message);
    }
  }

  function stop() {
    abortRef.current?.abort();
  }

  function copyMessage(m: Msg) {
    navigator.clipboard?.writeText(m.content).then(() => {
      setCopiedId(m.id);
      setTimeout(() => setCopiedId((id) => (id === m.id ? null : id)), 1500);
    });
  }

  async function send() {
    if (activeConv == null || !input.trim() || busy) return;
    const text = input;
    setInput("");
    setMessages((m) => [...m, mk("user", text)]);
    // assistant placeholder: tool steps stream in first, then the final answer.
    setMessages((m) => [...m, mk("assistant")]);
    setBusy(true);
    setError(null);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      for await (const { event, data } of api.streamMessage(
        activeConv,
        text,
        ac.signal,
      )) {
        if (event === "tool") {
          setMessages((m) => {
            const copy = [...m];
            const last = copy[copy.length - 1];
            copy[copy.length - 1] = {
              ...last,
              tools: [
                ...(last.tools ?? []),
                {
                  name: data.name,
                  args: data.args ?? {},
                  result: data.result ?? "",
                  ok: data.ok,
                },
              ],
            };
            return copy;
          });
        } else if (event === "delta") {
          // The agent emits one delta carrying the FULL answer (it runs
          // non-streaming per step for robust tool parsing), so replace.
          setMessages((m) => {
            const copy = [...m];
            copy[copy.length - 1] = {
              ...copy[copy.length - 1],
              content: data.content ?? "",
            };
            return copy;
          });
        } else if (event === "done") {
          // authoritative final content + model, persisted server-side
          setMessages((m) => {
            const copy = [...m];
            copy[copy.length - 1] = {
              ...copy[copy.length - 1],
              content: data.content,
              model: data.model,
              sources: data.sources ?? [],
            };
            return copy;
          });
          // first message may have auto-derived a title — sync the sidebar.
          if (data.title) await loadConvs();
        } else if (event === "error") {
          setError(data.message ?? "stream error");
          setMessages((m) =>
            m[m.length - 1]?.content === "" && !(m[m.length - 1]?.tools?.length)
              ? m.slice(0, -1)
              : m,
          );
        }
      }
    } catch (e: any) {
      if (e?.name === "AbortError") {
        // User stopped generation. Keep any tool steps / partial answer that
        // already arrived; drop an entirely-empty placeholder.
        setMessages((m) => {
          const last = m[m.length - 1];
          if (!last) return m;
          if (!last.content && !last.tools?.length) return m.slice(0, -1);
          return [...m.slice(0, -1), { ...last, stopped: true }];
        });
      } else {
        setError(e.message);
        setMessages((m) =>
          m[m.length - 1]?.content === "" && !(m[m.length - 1]?.tools?.length)
            ? m.slice(0, -1)
            : m,
        );
      }
    } finally {
      abortRef.current = null;
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
            <p
              className="px-2 py-4 text-center text-xs"
              style={{ color: "var(--faint)" }}
            >
              No conversations yet.
            </p>
          )}
          {convs.map((c) => {
            const isActive = activeConv === c.id;
            const isEditing = editingId === c.id;
            return (
              <div
                key={c.id}
                className="group flex items-center gap-1 rounded-lg px-1.5 transition-colors"
                style={
                  isActive
                    ? { backgroundColor: "var(--accent-soft)" }
                    : { backgroundColor: "transparent" }
                }
              >
                {isEditing ? (
                  <input
                    autoFocus
                    className="my-1 w-full rounded border bg-transparent px-1.5 py-1 text-sm"
                    style={{ borderColor: "var(--accent)", color: "var(--text)" }}
                    value={editText}
                    onChange={(e) => setEditText(e.target.value)}
                    onBlur={() => commitRename(c.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") commitRename(c.id);
                      if (e.key === "Escape") setEditingId(null);
                    }}
                  />
                ) : (
                  <button
                    onClick={() => {
                      if (!busy) setActiveConv(c.id);
                    }}
                    disabled={busy}
                    className="block w-full truncate rounded px-1 py-1.5 text-left text-sm"
                    style={
                      isActive ? { color: "var(--text)" } : { color: "var(--muted)" }
                    }
                    title={c.title}
                  >
                    {c.title || "Untitled"}
                  </button>
                )}
                {!isEditing && (
                  <div className="flex shrink-0 items-center opacity-0 transition-opacity group-hover:opacity-100">
                    <button
                      onClick={() => startRename(c)}
                      className="px-1 text-xs"
                      style={{ color: "var(--faint)" }}
                      title="Rename"
                    >
                      ✎
                    </button>
                    <button
                      onClick={() => delConv(c.id)}
                      className="px-1 text-xs"
                      style={{ color: "var(--faint)" }}
                      title="Delete"
                    >
                      ✕
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </aside>

      <section className="card flex flex-1 flex-col overflow-hidden p-0">
        {activeConv == null ? (
          <div
            className="flex flex-1 items-center justify-center"
            style={{ color: "var(--faint)" }}
          >
            Start a new conversation
          </div>
        ) : (
          <>
            <div className="flex-1 space-y-3 overflow-auto p-4">
              {messages.map((m) => (
                <div
                  key={m.id}
                  className={m.role === "user" ? "text-right" : "group/msg"}
                >
                  <div
                    className={
                      m.role === "user"
                        ? "inline-block max-w-[80%] whitespace-pre-wrap rounded-xl px-3.5 py-2 text-sm leading-relaxed"
                        : "inline-block max-w-[88%] space-y-2 rounded-xl px-3.5 py-2.5"
                    }
                    style={
                      m.role === "user"
                        ? {
                            backgroundColor: "var(--accent)",
                            color: "var(--accent-contrast)",
                          }
                        : { backgroundColor: "var(--surface-2)" }
                    }
                  >
                    {m.tools?.map((t, i) => (
                      <details key={i} className="tool-card">
                        <summary title={t.ok ? "tool ran" : "tool failed"}>
                          <span>{t.ok ? "🔧" : "⚠️"}</span>
                          <code>
                            {t.name}
                            {argSummary(t.name, t.args)}
                          </code>
                        </summary>
                        <div className="tool-result">{t.result}</div>
                      </details>
                    ))}
                    {m.role === "assistant" ? (
                      m.content ? (
                        <div className="prose-chat">
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{
                              a: (props) => (
                                <a {...props} target="_blank" rel="noreferrer" />
                              ),
                            }}
                          >
                            {m.content}
                          </ReactMarkdown>
                        </div>
                      ) : busy ? (
                        <span className="text-sm" style={{ color: "var(--faint)" }}>
                          thinking…
                        </span>
                      ) : m.stopped ? (
                        <span className="text-sm italic" style={{ color: "var(--faint)" }}>
                          (stopped)
                        </span>
                      ) : null
                    ) : (
                      m.content
                    )}
                  </div>
                  {/* Row of actions/sources under an assistant message. */}
                  {m.role === "assistant" &&
                    (m.content || m.tools?.length) &&
                    (m.sources?.length || m.content) && (
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 pl-1">
                        {m.content && (
                          <button
                            type="button"
                            onClick={() => copyMessage(m)}
                            className="rounded px-1.5 py-0.5 text-[11px] opacity-0 transition-opacity group-hover/msg:opacity-100"
                            style={{
                              color: copiedId === m.id ? "var(--success)" : "var(--faint)",
                              backgroundColor: "var(--surface-2)",
                            }}
                            title="Copy"
                          >
                            {copiedId === m.id ? "✓ copied" : "📋 copy"}
                          </button>
                        )}
                        {m.sources?.map((s) => (
                          <button
                            key={s.paper_id}
                            type="button"
                            onClick={() => onOpenPaper(s.paper_id)}
                            className="inline-block max-w-[260px] cursor-pointer truncate rounded-full px-2 py-0.5 text-[11px] transition-opacity hover:opacity-80"
                            style={{
                              backgroundColor: "var(--accent-soft)",
                              color: "var(--accent)",
                            }}
                            title={s.snippet}
                          >
                            📚 {s.title}
                          </button>
                        ))}
                      </div>
                    )}
                </div>
              ))}
              <div ref={endRef} />
            </div>
            {error && (
              <div className="px-4 py-2 text-sm" style={{ color: "var(--danger)" }}>
                {error}
              </div>
            )}
            <div
              className="flex items-end gap-2 p-3"
              style={{ borderTop: "1px solid var(--border)" }}
            >
              <textarea
                ref={taRef}
                className="input resize-none"
                rows={1}
                placeholder="Ask about your library…  (Enter to send · Shift+Enter for newline)"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
              />
              {busy ? (
                <button
                  onClick={stop}
                  className="btn-ghost shrink-0 px-5"
                  title="Stop generating"
                >
                  ■ Stop
                </button>
              ) : (
                <button
                  onClick={send}
                  disabled={!input.trim()}
                  className="btn-primary shrink-0 px-5"
                >
                  Send
                </button>
              )}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
