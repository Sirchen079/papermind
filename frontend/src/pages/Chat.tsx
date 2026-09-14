import { useApi } from '../workspaceContext';
import { useEffect, useRef, useState } from "react";
import { MarkdownContent } from '../components/MarkdownContent';
import { type Source, type TopicSource, type Paper, type ChatMessageExtra, type Clarification, type ClarificationResponse } from "../api";
import { ChatTopicSources } from '../components/ChatTopicSources';
import { AskUserCard } from "../components/AskUserCard";
import { usePaperDraft } from '../components/usePaperDraft';
import { AlertTriangle, BookOpen, Check, Copy, Lightbulb, Menu, MessageSquare, Pencil, Save, SquareIcon, Wrench, X } from "../icons";
import { useToast } from "../components/ui/Toast";
import { useConfirm } from "../components/ui/ConfirmDialog";
import { EmptyState } from "../components/ui/EmptyState";
import { ResearchMotif } from '../components/ui/ResearchMotif';
import { shouldSubmitOnEnter } from "./keyGuardModel";
import {
  chatMessagePayload,
  contextBadgeLabel,
  selectedTextOverLimit,
  type PaperChatContext,
} from "./chatContextModel";
import {
  captureFlow,
  ideaPayloadFromAnswer,
  notePayloadFromAnswer,
  resolveCapturePaper,
} from "./chatCaptureModel";

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
interface RetryTurn {
  text: string;
  serverId?: number;
  extra?: ChatMessageExtra;
}
interface Msg {
  id: number;
  role: string;
  content: string;
  model: string;
  sources?: Source[];
  topic_sources?: TopicSource[];
  tools?: ToolStep[];
  stopped?: boolean;
  error?: string;
  retry?: RetryTurn;
  clarification?: Clarification | null;
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
  paperContext,
  onClearPaperContext,
  onSelectionConsumed,
  onConversationDeleted,
  onContextLoaded,
}: {
  activeConv: number | null;
  setActiveConv: (id: number | null) => void;
  onOpenPaper: (id: number) => void;
  paperContext: PaperChatContext | null;
  onClearPaperContext: () => void;
  onSelectionConsumed: () => void;
  onConversationDeleted: (id: number) => void;
  onContextLoaded: (id: number, context: PaperChatContext | null) => void;
}) {
  const api = useApi();
  const [convs, setConvs] = useState<Conv[]>([]);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [composerDraft, setComposerDraft] = usePaperDraft(activeConv ?? 0, {content:''}, 'chat-composer');
  const input=composerDraft.content;
  const setInput=(content:string)=>setComposerDraft({content});
  const [manualSkills, setManualSkills] = useState<{id: number; name: string}[]>([]);
  const [manualSkillId, setManualSkillId] = useState("");
  useEffect(() => { let alive = true; api.listSkills().then(rows => { if (alive) setManualSkills(rows.filter(s => s.enabled && s.trigger === "manual" && ["instruction", "persona"].includes(s.type))); }).catch(() => {}); return () => { alive = false; }; }, []);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(activeConv != null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadRevision, setLoadRevision] = useState(0);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const toast = useToast();
  const confirm = useConfirm();
  const [navOpen, setNavOpen] = useState(false);
  const [editText, setEditText] = useState("");
  const [copiedId, setCopiedId] = useState<number | null>(null);
  // T6：回答回流（存为笔记 / 存为研究想法）。
  const [captureFor, setCaptureFor] = useState<{ msgId: number; mode: "note" | "idea" } | null>(null);
  const [chosenPaperId, setChosenPaperId] = useState<number | null>(null);
  const [captureBusy, setCaptureBusy] = useState(false);
  const [captureError, setCaptureError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const mountedRef = useRef(true);
  const creatingRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    // The request keeps its originating workspace client. Continue consuming
    // it in the background when the user changes page/project; Stop still aborts.
    return () => { mountedRef.current = false; };
  }, []);

  async function loadConvs() {
    try {
      const rows = await api.listConversations();
      if (mountedRef.current) setConvs(rows);
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
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError(null);
    let alive = true;
    let pollTimer:ReturnType<typeof setTimeout>|undefined;
    api
      .getConversation(activeConv)
      .then((c) => {
        const last=c.messages[c.messages.length-1];
        if(alive&&last?.role==='user'&&last.delivery_status==='pending'&&!last.retryable){
          pollTimer=setTimeout(()=>{if(alive)setLoadRevision(n=>n+1);},1500);
        }
        if (alive) onContextLoaded(c.id, c.paper_id == null ? null : { paperId: c.paper_id, paperTitle: c.paper_title, selectedText: null });
        if (alive)
          setMessages(
            c.messages.flatMap((m) => {
              const row = mk(m.role, m.content, m.model, { sources: m.sources ?? [], topic_sources: m.topic_sources ?? [], clarification: m.clarification });
              if (m.role !== "user" || !["failed", "pending"].includes(m.delivery_status ?? "")) return [row];
              return [row, mk("assistant", "", "", {
                error: m.error_message || (m.delivery_status==='pending'&&!m.retryable?'正在生成回答…':"上次回答尚未完成。"),
                retry: m.retryable ? { text: m.content, serverId: m.id } : undefined,
              })];
            }),
          );
      })
      .catch((e: any) => {
        if (alive) setLoadError(e.message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
      if(pollTimer)clearTimeout(pollTimer);
    };
  }, [activeConv, loadRevision, onContextLoaded]);

  useEffect(() => { setManualSkillId(""); }, [activeConv]);

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
    if (creatingRef.current || busy) return;
    creatingRef.current = true;
    setCreating(true);
    try {
      const c = await api.createConversation();
      if (!mountedRef.current) return;
      setActiveConv(c.id); // triggers the loader effect above
    } catch (e: any) {
      if (mountedRef.current) toast.error(e.message);
    } finally {
      creatingRef.current = false;
      if (mountedRef.current) setCreating(false);
    }
  }

  async function delConv(c: Conv) {
    const ok = await confirm({
      title: "删除对话？",
      message: `将删除「${c.title}」，此操作不可撤销。`,
      variant: "danger",
      confirmText: "删除",
    });
    if (!ok || !mountedRef.current) return;
    try {
      await api.deleteConversation(c.id);
      onConversationDeleted(c.id);
      if (!mountedRef.current) return;
      if (activeConv === c.id) setActiveConv(null);
      await loadConvs();
      toast.success("已删除对话。");
    } catch (e: any) {
      toast.error(e.message);
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
      toast.error(e.message);
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

  // ---- T6：回答回流 ----

  function beginCapture(m: Msg, mode: "note" | "idea") {
    setCaptureFor({ msgId: m.id, mode });
    setChosenPaperId(null);
    setCaptureError(null);
  }

  function closeCapture() {
    setCaptureFor(null);
    setChosenPaperId(null);
    setCaptureError(null);
  }

  async function commitCapture() {
    if (!captureFor || captureBusy) return;
    const message = messages.find((m) => m.id === captureFor.msgId);
    if (!message?.content) return;
    const flow = captureFlow(paperContext?.paperId ?? null, message.sources ?? []);
    const paper = resolveCapturePaper(flow, chosenPaperId);
    if (captureFor.mode === "note" && paper === "required") {
      setCaptureError("请先选择要保存到哪篇论文。");
      return;
    }
    if (paper === "required") {
      setCaptureError("请先选择来源论文（不会自动选第一篇）。");
      return;
    }
    setCaptureBusy(true);
    setCaptureError(null);
    try {
      if (captureFor.mode === "note") {
        if (paper == null) {
          setCaptureError("笔记必须挂到一篇论文；当前没有可用的论文上下文。");
          return;
        }
        await api.createNote(paper, notePayloadFromAnswer(message.content));
        toast.success("已保存为阅读笔记。");
      } else {
        await api.createIdea(ideaPayloadFromAnswer(message.content, paper));
        toast.success(paper != null ? "已保存为研究想法并挂接论文。" : "已保存为研究想法。");
      }
      closeCapture();
    } catch (e: any) {
      // 保存失败：保留回答与已选论文状态，只提示错误。
      setCaptureError(e?.message ?? "保存失败，请重试。");
    } finally {
      setCaptureBusy(false);
    }
  }

  const pendingQuestion = messages.find(m => m.clarification?.status === "pending")?.clarification;

  async function send() {
    await sendTurn(undefined, pendingQuestion ? { message_id: pendingQuestion.message_id, free_text: input } : undefined);
  }

  async function sendTurn(failedMessage?: Msg, answer?: ClarificationResponse, answerText?: string) {
    const retry = failedMessage?.retry;
    let text = retry?.text ?? answerText ?? input;
    if (activeConv == null || !text.trim() || busy || abortRef.current || loading || loadError || creating) return;
    const ac = new AbortController();
    abortRef.current = ac;
    setBusy(true);
    let serverId = retry?.serverId;
    const extra: ChatMessageExtra = retry?.extra ?? (answer ? { clarification_response: answer } :
      { ...chatMessagePayload(text, paperContext), skill_ids: manualSkillId ? [Number(manualSkillId)] : [] });
    let placeholderId: number | null = null;
    let userPlaceholderId: number | null = null;
    let completed = false;
    const fail = (message: string) => {
      if (!mountedRef.current) return;
      setMessages(rows => rows.map(row => row.id === placeholderId ? { ...row, error: message, retry: { text, serverId, extra } } : row));
    };
    try {
      if (retry) {
        // A network failure can happen after the server accepted the question.
        // Resolve its persisted identity before retrying to avoid a duplicate turn.
        const conversation = await api.getConversation(activeConv);
        const last = conversation.messages[conversation.messages.length - 1];
        if (last?.role === "user" && last.content === text && ["failed", "pending"].includes(last.delivery_status ?? "")) {
          if (!last.retryable) throw new Error("服务器仍在处理该问题，请稍后重试。");
          serverId = last.id;
        } else if (serverId != null || (last?.role === "assistant" && conversation.messages[conversation.messages.length - 2]?.content === text)) {
          setLoadRevision(value => value + 1);
          return;
        }
      }
      if (!mountedRef.current || ac.signal.aborted) return;
      const placeholder = mk("assistant");
      const userPlaceholder = mk("user", text);
      userPlaceholderId = userPlaceholder.id;
      placeholderId = placeholder.id;
      setMessages(rows => {
        const kept = failedMessage ? rows.filter(row => row.id !== failedMessage.id) : rows;
        // A retry reuses the visible and persisted question.
        return [...kept, ...(failedMessage ? [] : [userPlaceholder]), placeholder];
      });
      if (!retry && answerText === undefined) setInput("");
      if (!retry && !answer && paperContext?.selectedText) onSelectionConsumed();
      for await (const { event, data } of api.streamMessage(activeConv, text, ac.signal, { ...extra, retry_message_id: serverId })) {
        if (ac.signal.aborted) break;
        if (!mountedRef.current) continue;
        if (event === "accepted") {
          serverId = data.user_message_id;
          text = data.content ?? text;
          const response = data.clarification_response ?? extra.clarification_response;
          setMessages(rows => rows.map(row => {
            if (row.id === userPlaceholderId) return { ...row, content: text };
            if (response && row.clarification && row.clarification.message_id === response.message_id) return {
              ...row, clarification: { ...row.clarification, status: response.skipped ? "skipped" : "answered", response },
            };
            return row;
          }));
          if (data.title) await loadConvs();
        } else if (event === "tool") {
          setMessages(rows => rows.map(row => row.id === placeholderId ? { ...row, tools: [...(row.tools ?? []), { name: data.name, args: data.args ?? {}, result: data.result ?? "", ok: data.ok }] } : row));
        } else if (event === "delta") {
          setMessages(rows => rows.map(row => row.id === placeholderId ? { ...row, content: data.content ?? "" } : row));
        } else if (event === "ask_user") {
          completed = true;
          setMessages(rows => rows.map(row => row.id === placeholderId ? { ...row, content: data.content,
            model: data.model, sources: data.sources ?? [], topic_sources: data.topic_sources ?? [], clarification: data.clarification } : row));
          break;
        } else if (event === "done") {
          completed = true;
          setMessages(rows => rows.map(row => row.id === placeholderId ? { ...row, content: data.content, model: data.model, sources: data.sources ?? [], topic_sources: data.topic_sources ?? [] } : row));
          if (data.title) await loadConvs();
        } else if (event === "error") {
          serverId = data.user_message_id ?? serverId;
          fail(data.message ?? "回答生成失败，请重试。");
          completed = true;
          break;
        }
      }
      if (!completed) fail(ac.signal.aborted ? "已停止回答，可重试原问题。" : "连接已结束，未收到完整回答。请重试原问题。");
    } catch (e: any) {
      if (!mountedRef.current) return;
      const message = e?.name === "AbortError" ? "已停止回答，可重试原问题。" : e.message || "回答生成失败，请重试。";
      if (extra.clarification_response && serverId == null) {
        // Resolve an uncertain submission against durable state. The card's
        // locally saved answers survive if the server did not accept them.
        setMessages(rows => rows.filter(row => row.id !== placeholderId && row.id !== userPlaceholderId));
        if (answerText === undefined && !retry) setInput(input || text);
        setLoadRevision(value => value + 1);
        toast.error(message);
        return;
      }
      if (placeholderId != null) fail(message);
      else toast.error(message);
    } finally {
      if (abortRef.current === ac) abortRef.current = null;
      if (mountedRef.current) setBusy(false);
    }
  }

  return (
    <div className="chat-workspace relative flex gap-4 px-4 sm:px-6 lg:px-10">
      <aside
        className={`conversation-list absolute inset-y-0 left-0 z-20 flex w-64 shrink-0 flex-col overflow-hidden p-0 transition-transform duration-200 md:static md:z-auto md:w-56 md:translate-x-0 ${
          navOpen ? "translate-x-0 visible" : "-translate-x-full invisible md:visible"
        }`}
      >
        <div className="p-3 border-b border-[var(--border)]">
          <button
            onClick={() => {
              newConv();
              setNavOpen(false);
            }}
            className="btn-primary w-full"
            disabled={creating || busy}
          >
            + 新建对话
          </button>
        </div>
        <div className="flex-1 space-y-1 overflow-auto p-2">
          {convs.length === 0 && (
            <p className="px-2 py-4 text-center text-xs text-faint">
              还没有对话。
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
                      if (shouldSubmitOnEnter(e.key, false, e.nativeEvent.isComposing)) commitRename(c.id);
                      if (e.key === "Escape") setEditingId(null);
                    }}
                  />
                ) : (
                  <button
                    disabled={busy}
                    onClick={() => {
                      setActiveConv(c.id);
                      setNavOpen(false);
                    }}
                    className={`block w-full truncate rounded px-1 py-1.5 text-left text-sm ${
                      isActive ? "text-[var(--text)]" : "text-muted"
                    }`}
                    title={c.title}
                  >
                    {c.title || "未命名"}
                  </button>
                )}
                {!isEditing && (
                  <div className="flex shrink-0 items-center opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                    <button
                      onClick={() => startRename(c)}
                      className="px-1 text-xs text-faint"
                      title="重命名"
                      aria-label={`重命名「${c.title}」`}
                    >
                      <Pencil size={12} />
                    </button>
                    <button
                      onClick={() => delConv(c)}
                      className="px-1 text-xs text-faint"
                      title="删除"
                      aria-label={`删除对话「${c.title}」`}
                    >
                      <X size={12} />
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </aside>

      {navOpen && (
        <div
          className="modal-overlay z-10 md:hidden"
          onClick={() => setNavOpen(false)}
          aria-hidden="true"
        />
      )}

      <section className="chat-canvas flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="flex items-center gap-2 p-2 md:hidden border-b border-[var(--border)]">
          <button onClick={() => setNavOpen(true)} className="btn-ghost p-1.5" aria-label="打开对话列表">
            <Menu size={16} />
          </button>
          <span className="text-sm text-muted">
            {activeConv == null ? "选择或新建对话" : "当前对话"}
          </span>
        </div>
        {activeConv == null ? (
          <EmptyState
            className="chat-welcome flex-1"
            icon={<MessageSquare size={24} />}
            title="开始一个新对话"
            hint="向你的论文库提问、总结文献、梳理研究脉络。"
            action={
              <button onClick={newConv} className="btn-primary">
                + 新建对话
              </button>
            }
          />
        ) : (
          <>
            <div className="chat-messages flex-1 space-y-6 overflow-auto p-4">
              {loading && <p role="status" className="text-sm text-muted">正在加载对话…</p>}
              {loadError && <div role="alert" className="text-sm">无法加载对话：{loadError}<button className="btn-ghost ml-2" onClick={() => setLoadRevision(n => n + 1)}>重试</button></div>}
              {messages.length===0&&<div className="chat-starters"><ResearchMotif icon={<MessageSquare size={24}/>}/><h2>想从哪篇论文聊起？</h2><p className="text-sm text-muted">写下问题，或从一个方向开始。</p><div className="flex flex-wrap justify-center gap-2">{['解释论文中的一个概念','比较几篇论文的方法','根据原文总结局限'].map(prompt=><button key={prompt} className="btn-ghost text-xs" onClick={()=>{setInput(prompt);taRef.current?.focus();}}>{prompt}</button>)}</div></div>}
              {messages.map((m) => (
                <div
                  key={m.id}
                  className={m.role === "user" ? "text-right" : "group/msg"}
                >
                  <div
                    className={
                      m.role === "user"
                        ? "user-message inline-block max-w-[90%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-relaxed"
                        : "assistant-message w-full space-y-2 py-3"
                    }
                    style={
                      m.role === "user"
                        ? {
                            backgroundColor: "var(--surface-2)",
                            color: "var(--text)",
                          }
                        : { backgroundColor: "transparent" }
                    }
                  >
                    {m.tools?.map((t, i) => (
                      <details key={i} className="tool-card">
                        <summary title={t.ok ? "工具执行成功" : "工具执行失败"}>
                          <span className="flex items-center justify-center">{t.ok ? <Wrench size={12} /> : <AlertTriangle size={12} />}</span>
                          <code>
                            {t.name}
                            {argSummary(t.name, t.args)}
                          </code>
                        </summary>
                        <div className="tool-result">{t.result}</div>
                      </details>
                    ))}
                    {m.error && <div role="alert" className="mb-2 text-sm text-[var(--danger)]"><p>回答未完成：{m.error}</p>{m.retry && <button type="button" className="btn-ghost mt-2 text-xs" disabled={busy || loading} onClick={() => void sendTurn(m)}>重试原问题</button>}</div>}
                    {m.clarification ? <AskUserCard request={m.clarification} conversationId={activeConv}
                      disabled={busy || loading || !!loadError || creating}
                      onAnswer={(response, text) => void sendTurn(undefined, response, text)} /> : m.role === "assistant" ? (
                      m.content ? (
                        <MarkdownContent content={m.content} />
                      ) : busy && !m.error ? (
                        <span className="text-sm text-faint">
                          思考中…
                        </span>
                      ) : m.stopped ? (
                        <span className="text-sm italic text-faint">
                          （已停止）
                        </span>
                      ) : null
                    ) : (
                      <MarkdownContent content={m.content} />
                    )}
                  </div>
                  {/* Row of actions/sources under an assistant message. */}
                  {m.role === "assistant" &&
                    !m.error && !m.clarification && (m.content || m.tools?.length) &&
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
                            title="复制"
                          >
                            {copiedId === m.id ? (<><Check size={11} /> 已复制</>) : (<><Copy size={11} /> 复制</>)}
                          </button>
                        )}
                        {m.content && (
                          <button
                            type="button"
                            onClick={() => beginCapture(m, "note")}
                            className="rounded px-1.5 py-0.5 text-[11px] transition-opacity"
                            style={{ color: "var(--faint)", backgroundColor: "var(--surface-2)" }}
                            title="把这条回答保存为某篇论文的阅读笔记"
                          >
                            <Save size={11} /> 存为笔记
                          </button>
                        )}
                        {m.content && (
                          <button
                            type="button"
                            onClick={() => beginCapture(m, "idea")}
                            className="rounded px-1.5 py-0.5 text-[11px] transition-opacity"
                            style={{ color: "var(--faint)", backgroundColor: "var(--surface-2)" }}
                            title="把这条回答保存为研究想法"
                          >
                            <Lightbulb size={11} /> 存为研究想法
                          </button>
                        )}
                        {m.sources?.map((s, index) => (
                          <button
                            key={`${s.paper_id}:${index}`}
                            type="button"
                            onClick={() => onOpenPaper(s.paper_id)}
                            className="inline-block max-w-[260px] cursor-pointer truncate rounded-full px-2 py-0.5 text-[11px] transition-opacity hover:opacity-80"
                            style={{
                              backgroundColor: "var(--accent-soft)",
                              color: "var(--accent)",
                            }}
                            title={s.snippet}
                          >
                            <BookOpen size={11} /> {s.title}
                          </button>
                        ))}
                        {captureFor?.msgId === m.id && (
                          <CapturePanel
                            mode={captureFor.mode}
                            message={m}
                            contextPaperId={paperContext?.paperId ?? null}
                            contextTitle={paperContext?.paperTitle ?? null}
                            chosenPaperId={chosenPaperId}
                            onChoose={setChosenPaperId}
                            busy={captureBusy}
                            error={captureError}
                            onConfirm={() => void commitCapture()}
                            onCancel={closeCapture}
                          />
                        )}
                      </div>
                    )}
                  {m.role === 'assistant' && !m.error && <ChatTopicSources sources={m.topic_sources ?? []} />}
                </div>
              ))}
              <div ref={endRef} />
            </div>
            {paperContext && (
              <div
                className="flex flex-wrap items-center gap-2 border-t px-3 py-2 text-xs"
                style={{ borderColor: "var(--border)", backgroundColor: "var(--surface-2)" }}
              >
                <span className="rounded-full px-2 py-0.5" style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
                  {contextBadgeLabel(paperContext)}
                </span>
                <span className="text-faint">
                  {selectedTextOverLimit(paperContext.selectedText)
                    ? "选中文本过长，本次提问将只携带论文上下文"
                    : "回答会优先基于这篇论文的摘要、审阅矩阵、你的笔记与摘录"}
                </span>
                <button onClick={onClearPaperContext} className="btn-ghost ml-auto py-0.5 text-xs">
                  退出论文上下文
                </button>
              </div>
            )}
            {manualSkills.length > 0 && <label className="flex items-center gap-2 px-3 py-2 text-xs text-muted">
              本轮技能
              <select aria-label="本轮手动技能" className="input w-auto" disabled={busy || loading} value={manualSkillId} onChange={e => setManualSkillId(e.target.value)}>
                <option value="">不使用手动技能</option>
                {manualSkills.map(skill => <option key={skill.id} value={skill.id}>{skill.name}</option>)}
              </select>
              <span>选择后随提问应用；可随时取消。</span>
            </label>}
            <div
              className="chat-composer flex items-end gap-2"

            >
              <textarea
                ref={taRef}
                disabled={loading || !!loadError || creating}
                aria-label="向论文库提问"
                className="input resize-none"
                rows={1}
                placeholder={pendingQuestion ? "直接补充信息或调整需求，AI 会继续处理…" : "向论文库提问，支持 Markdown / LaTeX…（Shift+回车换行）"}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (shouldSubmitOnEnter(e.key, e.shiftKey, e.nativeEvent.isComposing)) {
                    e.preventDefault();
                    send();
                  }
                }}
              />
              {busy ? (
                <button
                  onClick={stop}
                  className="btn-ghost shrink-0 px-5"
                  title="停止生成"
                >
                  <SquareIcon size={12} /> 停止
                </button>
              ) : (
                <button
                  onClick={send}
                  disabled={!input.trim() || loading || !!loadError || creating}
                  className="btn-primary shrink-0 px-5"
                >
                  发送
                </button>
              )}
            </div>
          </>
        )}
      </section>
    </div>
  );
}

/** T6：回流面板——确认目标论文后保存。失败保留选择状态。 */
function CapturePanel({
  mode,
  message,
  contextPaperId,
  contextTitle,
  chosenPaperId,
  onChoose,
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  mode: "note" | "idea";
  message: Msg;
  contextPaperId: number | null;
  contextTitle: string | null;
  chosenPaperId: number | null;
  onChoose: (id: number | null) => void;
  busy: boolean;
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const api = useApi();
  // 与 commitCapture 使用同一决策函数，保证提示与实际保存行为一致。
  const flow = captureFlow(contextPaperId, message.sources ?? []);
  const sources = (message.sources ?? []).filter((s, index, all) =>
    all.findIndex(other => other.paper_id === s.paper_id) === index);
  const [paperQuery, setPaperQuery] = useState("");
  const [paperOptions, setPaperOptions] = useState<Paper[]>([]);
  const [searchError, setSearchError] = useState("");
  const [searching, setSearching] = useState(false);
  useEffect(() => {
    if (flow.flow !== "free" || mode !== "note") return;
    let alive = true;
    setSearching(true); setSearchError("");
    const timer = window.setTimeout(() => api.listPapers(50, 0, paperQuery.trim() || undefined)
      .then(page => { if (alive) setPaperOptions(page.items); })
      .catch(e => { if (alive) setSearchError(e.message); })
      .finally(() => { if (alive) setSearching(false); }), 200);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [paperQuery, flow.flow, mode]);
  return (
    <div
      className="mt-1 w-full rounded-lg border p-2 text-xs"
      style={{ borderColor: "var(--accent)", backgroundColor: "var(--surface-2)" }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{mode === "note" ? "存为阅读笔记" : "存为研究想法"}</span>
        {flow.flow === "paper" && contextTitle != null && (
          <span className="rounded-full px-2 py-0.5" style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}>
            默认保存到《{contextTitle}》
          </span>
        )}
        {sources.length > 0 && (
          <select
            className="input max-w-[220px] py-0.5 text-xs"
            value={chosenPaperId == null ? "" : String(chosenPaperId)}
            onChange={(e) => onChoose(e.target.value ? Number(e.target.value) : null)}
            aria-label="选择来源论文"
          >
            <option value="">
              {contextTitle != null ? `使用当前论文上下文` : "请选择来源论文…"}
            </option>
            {sources.map((s) => (
              <option key={s.paper_id} value={s.paper_id}>
                {s.title ?? `论文 #${s.paper_id}`}
              </option>
            ))}
          </select>
        )}
        <div className="ml-auto flex gap-1">
          <button onClick={onConfirm} disabled={busy || (mode === "note" && flow.flow !== "paper" && chosenPaperId == null)} className="btn-primary py-0.5 text-xs">
            {busy ? "保存中…" : "保存"}
          </button>
          <button onClick={onCancel} className="btn-ghost py-0.5 text-xs">
            取消
          </button>
        </div>
      </div>
      {error && (
        <p className="mt-1" style={{ color: "var(--danger)" }}>{error}</p>
      )}
      {flow.flow === "free" && mode === "note" && (
        <div className="mt-2 space-y-2">
          <p className="text-faint">选择笔记归属论文；可搜索整个论文库。</p>
          <input className="input w-full" aria-label="搜索笔记归属论文" placeholder="输入论文标题或作者" value={paperQuery} onChange={e => { setPaperQuery(e.target.value); onChoose(null); }}/>
          {searchError ? <p role="alert">{searchError}</p> : <select className="input w-full" aria-label="选择笔记归属论文" disabled={searching} value={chosenPaperId ?? ""} onChange={e => onChoose(e.target.value ? Number(e.target.value) : null)}>
            <option value="">{searching ? "正在搜索…" : paperOptions.length ? "请选择论文（最多显示 50 篇，可输入关键词缩小范围）" : "没有匹配的论文"}</option>
            {paperOptions.map(p => <option key={p.id} value={p.id}>{p.title ?? `论文 #${p.id}`}</option>)}
          </select>}
        </div>
      )}
      {flow.flow === "free" && mode === "idea" && (
        <p className="mt-1 text-faint">将保存为不挂论文的研究想法（origin=manual）。</p>
      )}
    </div>
  );
}
