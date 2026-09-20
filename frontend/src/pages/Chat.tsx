import { useApi, useWorkspace } from '../workspaceContext';
import { useEffect, useRef, useState } from "react";
import { MarkdownContent } from '../components/MarkdownContent';
import { type ChatAttachment, type ChatModel, type Source, type TopicSource, type Paper, type ChatMessageExtra, type Clarification, type ClarificationResponse } from "../api";
import { ChatTopicSources } from '../components/ChatTopicSources';
import { AskUserCard } from "../components/AskUserCard";
import { DiscussionPapers } from '../components/DiscussionPapers';
import { useChatDraft } from '../components/useChatDraft';
import { appendQueued, nextQueued, finishQueued } from './chatQueueModel';
import { libraryScope } from '../components/usePaperDraft';
import { usePaperDraft } from '../components/usePaperDraft';
import { AlertTriangle, BookOpen, Check, Copy, Lightbulb, Menu, MessageSquare, Pencil, Save, SquareIcon, Wrench, X } from "../icons";
import { useToast } from "../components/ui/Toast";
import { useConfirm } from "../components/ui/ConfirmDialog";
import { EmptyState } from "../components/ui/EmptyState";
import { ResearchMotif } from '../components/ui/ResearchMotif';
import { shouldSubmitOnEnter } from "./keyGuardModel";
import {
  chatMessagePayload,
  conversationPaperContext,
  paperSetContext,
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
  queueId?: string;
  continuable?: boolean;
  text: string;
  serverId?: number;
  extra?: ChatMessageExtra;
}
interface QueuedTurn { id: string; state: 'waiting' | 'sending'; text: string; extra: ChatMessageExtra; }
interface ComposerMaterials { attachments: ChatAttachment[]; queue: QueuedTurn[]; }
interface Msg {
  attachments?: ChatAttachment[];
  status?: string;
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
  const { workspace } = useWorkspace();
  const draftKey = `${libraryScope()}:${workspace.id}:${activeConv ?? 0}`;
  const [convs, setConvs] = useState<Conv[]>([]);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [composerDraft, setComposerDraft, clearComposerDraft] = usePaperDraft(activeConv ?? 0, {content:''}, 'chat-composer');
  const input=composerDraft.content;
  const setInput=(content:string)=>setComposerDraft({content});
  const [manualSkills, setManualSkills] = useState<{id: number; name: string}[]>([]);
  const [reviewEvidence, setReviewEvidence] = useState(false);
  const [manualSkillId, setManualSkillId] = useState("");
  useEffect(() => { let alive = true; api.listSkills().then(rows => { if (alive) setManualSkills(rows.filter(s => s.enabled && s.trigger === "manual" && ["instruction", "persona"].includes(s.type))); }).catch(() => {}); return () => { alive = false; }; }, []);
  const [busy, setBusy] = useState(false);
  const materials = useChatDraft<ComposerMaterials>(draftKey, { attachments: [], queue: [] });
  const { attachments, queue } = materials.value;
  function setAttachments(value: ChatAttachment[] | ((items: ChatAttachment[]) => ChatAttachment[])) {
    materials.update(previous => ({ ...previous, attachments: typeof value === 'function' ? value(previous.attachments) : value }));
  }
  const [queuePaused, setQueuePaused] = useState(true);
  const pauseRef = useRef(true);
  function pauseQueue() { pauseRef.current = true; setQueuePaused(true); }
  const scopeRef = useRef(draftKey); scopeRef.current = draftKey;
  const [contextUsage, setContextUsage] = useState<{before: number; after: number; window: number; compacted: boolean; summarized: boolean} | null>(null);
  const [uploading, setUploading] = useState(false);
  const [models, setModels] = useState<ChatModel[]>([]);
  const [modelId, setModelId] = useState("");
  const [stopping, setStopping] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const uploadRef = useRef(false);
  const followRef = useRef(true);
  const selectedModel = models.find(m => String(m.id) === modelId) ?? models.find(m => m.is_default);
  function refreshModels() { api.chatModels().then(setModels).catch(e => toast.error(e.message)); }
  useEffect(() => { refreshModels(); }, []);
  useEffect(() => { pauseQueue(); setContextUsage(null); setBusy(false); setStopping(false); abortRef.current = null; followRef.current = true; }, [draftKey]);
  const [configOpen, setConfigOpen] = useState(false);
  const [contextDraft, setContextDraft] = useState("");
  const [effortDraft, setEffortDraft] = useState("");
  const [imageDraft, setImageDraft] = useState("auto");
  const [configBusy, setConfigBusy] = useState(false);
  async function saveConfig() {
    if (!selectedModel) return;
    const context = contextDraft.trim() ? Number(contextDraft) : null;
    if (context !== null && (!Number.isInteger(context) || context <= 0)) { toast.error("上下文需填写正整数"); return; }
    setConfigBusy(true);
    try {
      await api.patchModel(selectedModel.id, { context_window: context, reasoning_effort: effortDraft || null, supports_images: imageDraft === 'auto' ? null : imageDraft === 'true' });
      const rows = await api.chatModels(); setModels(rows); setConfigOpen(false); toast.success("模型配置已保存");
    } catch (e: any) { toast.error(e.message); }
    finally { setConfigBusy(false); }
  }
  async function addFiles(files: File[]) {
    if (!files.length) return;
    if (uploadRef.current || !materials.ready) { toast.error("请等当前处理完成后再添加附件"); return; }
    if (attachments.length + files.length > 4) { toast.error("每条消息最多添加 4 个附件"); return; }
    const scope = draftKey;
    uploadRef.current = true; setUploading(true);
    try {
      for (const file of files) {
        try {
          if (file.size > 10 * 1024 * 1024) throw new Error("每个附件最多 10 MB");
          const item = await api.uploadChatAttachment(file);
          if (mountedRef.current && scopeRef.current === scope) setAttachments(items => [...items, item]);
        } catch (e: any) { toast.error(`${file.name}：${e.message}`); }
      }
    } finally { uploadRef.current = false; if (mountedRef.current) setUploading(false); }
  }
  const [serverPending, setServerPending] = useState(false);
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
        if (alive) {
          const pending = last?.role === "user" && last.delivery_status === "pending" && !last.retryable;
          setServerPending(pending);
          if (!pending) setStopping(false);
        }
        if(alive&&last?.role==='user'&&last.delivery_status==='pending'&&!last.retryable){
          pollTimer=setTimeout(()=>{if(alive)setLoadRevision(n=>n+1);},1500);
        }
        if (alive) onContextLoaded(c.id, conversationPaperContext(c));
        if (alive)
          setMessages(
            c.messages.flatMap((m) => {
              const row = mk(m.role, m.content, m.model, { sources: m.sources ?? [], topic_sources: m.topic_sources ?? [], clarification: m.clarification, attachments: m.attachments, tools: m.tools });
              if (m.role !== "user" || !["failed", "pending"].includes(m.delivery_status ?? "")) return [row];
              return [row, mk("assistant", "", "", {
                ...(m.delivery_status === 'pending' && !m.retryable
                  ? { status: '后台正在生成回答…' }
                  : { error: m.error_message || '上次回答尚未完成。' }),
                retry: m.retryable ? { text: m.content, serverId: m.id, continuable: m.continuable } : undefined,
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

  useEffect(() => { setManualSkillId(""); setReviewEvidence(false); }, [draftKey]);

  useEffect(() => {
    if (followRef.current) endRef.current?.scrollIntoView({ behavior: "smooth" });
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

  async function stop() {
    if (activeConv == null || stopping) return;
    pauseQueue();
    setStopping(true);
    try { await api.stopChat(activeConv); }
    catch (e: any) { setStopping(false); toast.error(`停止请求未送达：${e.message}`); }
  }

  function copyMessage(m: Msg) {
    if (!navigator.clipboard) { toast.error("当前环境不支持复制，请手动选择文字复制。"); return; }
    navigator.clipboard.writeText(m.content).then(() => {
      setCopiedId(m.id);
      setTimeout(() => setCopiedId((id) => (id === m.id ? null : id)), 1500);
    }).catch(() => toast.error("复制失败，请检查剪贴板权限或手动复制。"));
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
    const flow = captureFlow(paperContext?.papers ? null : paperContext?.paperId ?? null, message.sources ?? []);
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

  useEffect(() => {
    const next = nextQueued(queue, queuePaused || pauseRef.current, busy || serverPending || uploading || loading || !!loadError || !materials.ready || !!pendingQuestion || !!abortRef.current);
    if (next && activeConv != null) void sendTurn(undefined, undefined, next.text, next.extra.attachments ?? [], String(next.extra.model_config_id ?? ''), next);
  }, [busy, queue, queuePaused, activeConv, loading, loadError, materials.ready, pendingQuestion, serverPending, uploading]);

  function queueCurrentTurn() {
    if ((!input.trim() && !attachments.length) || uploading || !materials.ready) return;
    if (attachments.some(a => a.kind === 'image') && selectedModel?.supports_images === false) { toast.error("请先选择支持图片的模型"); return; }
    if (paperContext && selectedTextOverLimit(paperContext.selectedText)) { toast.error("选中文本过长，请缩短后发送"); return; }
    const item: QueuedTurn = { id: crypto.randomUUID(), state: 'waiting', text: input.trim() || "请分析所附材料。", extra: {
      ...chatMessagePayload(input, paperContext), attachments, model_config_id: selectedModel?.id, review_evidence: reviewEvidence,
      skill_ids: manualSkillId ? [Number(manualSkillId)] : [],
    } };
    try {
      materials.update(previous => ({ attachments: [], queue: appendQueued(previous.queue, item) }));
      clearComposerDraft(composerDraft);
      if (paperContext?.selectedText) onSelectionConsumed();
      // Only a currently successful foreground run can drain a fresh queue.
      if (busy && !stopping && !queue.length) { pauseRef.current = false; setQueuePaused(false); }
    } catch (e: any) { toast.error(e.message); }
  }

  async function send() {
    if (busy || serverPending) { queueCurrentTurn(); return; }
    await sendTurn(undefined, pendingQuestion ? { message_id: pendingQuestion.message_id, free_text: input } : undefined);
  }

  async function sendTurn(failedMessage?: Msg, answer?: ClarificationResponse, answerText?: string, turnAttachments = attachments, turnModelId = modelId, queued?: QueuedTurn) {
    const origin = draftKey;
    const retry = failedMessage?.retry;
    let text = retry?.text ?? answerText ?? input;
    if (!text.trim() && turnAttachments.length) text = "请分析所附材料。";
    if (activeConv == null || !text.trim() || busy || serverPending || abortRef.current || loading || loadError || creating || uploading || !materials.ready) return;
    if (queued && (pauseRef.current || scopeRef.current !== origin)) return;
    if (!retry && !queued && attachments.some(a => a.kind === 'image') && selectedModel?.supports_images === false) { toast.error("请先选择支持图片的模型"); return; }
    const ac = new AbortController();
    abortRef.current = ac;
    setBusy(true); setStopping(false); setContextUsage(null); followRef.current = true;
    let serverId = retry?.serverId;
    const extra: ChatMessageExtra = retry?.extra ?? queued?.extra ?? { review_evidence: reviewEvidence, attachments: turnAttachments, model_config_id: turnModelId ? Number(turnModelId) : undefined, ...(answer ? { clarification_response: answer } :
      { ...chatMessagePayload(text, paperContext), skill_ids: manualSkillId ? [Number(manualSkillId)] : [] }) };
    let placeholderId: number | null = null;
    let userPlaceholderId: number | null = null;
    let completed = false;
    let succeeded = false;
    const fail = (message: string, continuable = false) => {
      if (!mountedRef.current || scopeRef.current !== origin) return;
      setMessages(rows => rows.map(row => row.id === placeholderId ? { ...row, error: message, retry: { text, serverId, extra, continuable, queueId: queued?.id ?? retry?.queueId } } : row));
    };
    try {
      if (queued) {
        const saved = await materials.update(previous => ({ ...previous, queue: previous.queue.map(item => item.id === queued.id ? { ...item, state: 'sending' } : item) }));
        if (!saved) {
          materials.update(previous => ({ ...previous, queue: previous.queue.map(item => item.id === queued.id ? { ...item, state: 'waiting' } : item) }));
          throw new Error("未能保存排队发送状态，已暂停，修复草稿存储后可继续。");
        }
        if (pauseRef.current || !mountedRef.current || scopeRef.current !== origin) {
          materials.update(previous => ({ ...previous, queue: previous.queue.map(item => item.id === queued.id ? { ...item, state: 'waiting' } : item) }));
          return;
        }
      }
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
      if (!mountedRef.current || scopeRef.current !== origin || ac.signal.aborted) return;
      const placeholder = mk("assistant");
      const userPlaceholder = mk("user", text, "", { attachments: extra.attachments });
      userPlaceholderId = userPlaceholder.id;
      placeholderId = placeholder.id;
      setMessages(rows => {
        const kept = failedMessage ? rows.filter(row => row.id !== failedMessage.id) : rows;
        // A retry reuses the visible and persisted question.
        return [...kept, ...(failedMessage ? [] : [userPlaceholder]), placeholder];
      });
      // Clear the draft only after the server acknowledges the message.
      if (!retry && !answer && !queued && paperContext?.selectedText) onSelectionConsumed();
      for await (const { event, data } of api.streamMessage(activeConv, text, ac.signal, { ...extra, model_config_id: turnModelId ? Number(turnModelId) : extra.model_config_id, retry_message_id: serverId })) {
        if (ac.signal.aborted) break;
        // Acknowledgements must update the originating durable draft even if
        // the page has been left. Never touch the newly selected conversation.
        if (event === "accepted") {
          const acceptedQueueId = queued?.id ?? retry?.queueId;
          if (acceptedQueueId) materials.update(previous => ({ ...previous, queue: finishQueued(previous.queue, acceptedQueueId) }));
          if (!retry && answerText === undefined) {
            clearComposerDraft(composerDraft);
            materials.update(previous => ({ ...previous, attachments: previous.attachments.filter(item => !turnAttachments.includes(item)) }));
          }
        }
        if (!mountedRef.current || scopeRef.current !== origin) continue;
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
        } else if (event === "status") {
          if (data.context) setContextUsage(previous => ({ ...data.context, compacted: !!data.context.compacted || !!previous?.compacted, summarized: data.context.compacted ? data.context.summarized : previous?.summarized ?? false }));
          const stage = data.phase === "tool" ? `正在执行 ${data.name}` : data.phase === "review" ? "正在整理并核对回答" : "正在等待模型响应";
          setMessages(rows => rows.map(row => row.id === placeholderId ? { ...row, status: `${stage} · ${data.step}/${data.max_steps} 轮` } : row));
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
          succeeded = true;
          setMessages(rows => rows.map(row => row.id === placeholderId ? { ...row, content: data.content, model: data.model, sources: data.sources ?? [], topic_sources: data.topic_sources ?? [] } : row));
          if (data.title) await loadConvs();
        } else if (event === "error") {
          serverId = data.user_message_id ?? serverId;
          fail(data.message ?? "回答生成失败，请重试。", !!data.continuable);
          completed = true;
          break;
        }
      }
      if (!completed) fail(ac.signal.aborted ? "已停止回答，可重试原问题。" : "连接已结束，未收到完整回答。请重试原问题。");
    } catch (e: any) {
      if (!mountedRef.current || scopeRef.current !== origin) return;
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
      if (mountedRef.current && scopeRef.current === origin) {
        if (!succeeded) pauseQueue();
        setBusy(false); setStopping(false);
      }
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
            <div className="chat-messages flex-1 space-y-6 overflow-auto p-4" onScroll={e => { const el = e.currentTarget; followRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100; }}>
              {loading && <p role="status" className="text-sm text-muted">正在加载对话…</p>}
              {loadError && <div role="alert" className="text-sm">无法加载对话：{loadError}<button className="btn-ghost ml-2" onClick={() => setLoadRevision(n => n + 1)}>重试</button></div>}
              {messages.length===0&&<div className="chat-starters"><ResearchMotif icon={<MessageSquare size={24}/>}/><h2>想讨论什么研究问题？</h2><p className="text-sm text-muted">写下问题，或从一个方向开始。</p><div className="flex flex-wrap justify-center gap-2">{['一起梳理我的研究背景与目标','讨论一个研究 idea 的可行性','比较几篇论文的方法'].map(prompt=><button key={prompt} className="btn-ghost text-xs" onClick={()=>{setInput(prompt);taRef.current?.focus();}}>{prompt}</button>)}</div></div>}
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
                    {m.attachments?.length ? <div className="mb-2 flex flex-wrap gap-2 justify-end">{m.attachments.map((a, i) => <AttachmentChip key={i} attachment={a} />)}</div> : null}
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
                    {m.error && <div role="alert" className="mb-2 text-sm text-[var(--danger)]"><p>回答未完成：{m.error}</p>{m.retry && <button type="button" className="btn-ghost mt-2 text-xs" disabled={busy || serverPending || loading} onClick={() => void sendTurn(m)}>{m.retry.continuable ? "从已保存进度继续" : "重试原问题"}</button>}</div>}
                    {m.clarification ? <AskUserCard request={m.clarification} conversationId={activeConv}
                      disabled={busy || loading || !!loadError || creating}
                      onAnswer={(response, text) => void sendTurn(undefined, response, text)} /> : m.role === "assistant" ? (
                      m.content ? (
                        <MarkdownContent content={m.content} />
                      ) : (busy || serverPending) && !m.error ? (
                        <span className="text-sm text-faint">
                          {stopping ? "正在停止，等待当前请求结束；不会继续调用工具…" : m.status || "正在连接模型…"}
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
                            contextPaperId={paperContext?.papers ? null : paperContext?.paperId ?? null}
                            contextTitle={paperContext?.papers ? null : paperContext?.paperTitle ?? null}
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
                    : paperContext.papers ? '优先围绕所选论文讨论，可连续追问、比较方法和探索 idea；需要时读取全文。' : "回答会优先基于这篇论文的摘要、审阅矩阵、你的笔记与摘录"}
                </span>
                <button onClick={onClearPaperContext} disabled={busy || queue.length > 0} className="btn-ghost ml-auto py-0.5 text-xs">
                  退出论文上下文
                </button>
                {paperContext.papers && <DiscussionPapers papers={paperContext.papers} onOpenPaper={onOpenPaper} />}
              </div>
            )}
            {manualSkills.length > 0 && <label className="flex items-center gap-2 px-3 py-2 text-xs text-muted">
              本轮技能
              <select aria-label="本轮手动技能" className="input w-auto" disabled={loading} value={manualSkillId} onChange={e => setManualSkillId(e.target.value)}>
                <option value="">不使用手动技能</option>
                {manualSkills.map(skill => <option key={skill.id} value={skill.id}>{skill.name}</option>)}
              </select>
              <span>选择后随提问应用；可随时取消。</span>
            </label>}
            <div className="flex flex-wrap items-center gap-2 px-3 py-2 text-xs text-muted">
              <label className="flex max-w-full flex-wrap items-center gap-2">对话模型 <select aria-label="对话模型" className="input w-auto max-w-full" value={modelId} disabled={loading} onFocus={refreshModels} onChange={e => setModelId(e.target.value)}>
                <option value="">默认模型{models.find(m => m.is_default) ? ` · ${models.find(m => m.is_default)!.name}` : "（请在设置中添加）"}</option>
                {models.map(m => <option key={m.id} value={m.id}>{m.provider} · {m.name}</option>)}
              </select></label>
              {selectedModel && <button type="button" className="btn-ghost text-xs" disabled={busy} onClick={() => { setContextDraft(selectedModel.context_window?.toString() || ''); setEffortDraft(selectedModel.reasoning_effort || ''); setImageDraft(selectedModel.supports_images == null ? 'auto' : String(selectedModel.supports_images)); setConfigOpen(!configOpen); }}>配置模型</button>}
              {selectedModel && <span>上下文 {selectedModel.context_window ? `${Math.round(selectedModel.context_window / 1000)}k` : "自动"} · 思考 {selectedModel.reasoning_effort || "自动"} · {selectedModel.supports_images === true ? "支持图片" : selectedModel.supports_images === false ? "仅文本" : "图片能力未声明"}</span>}
              <label className="flex items-center gap-1" title="开启后额外调用模型核对材料，耗时更长；可随时关闭，普通讨论无需开启">
                <input type="checkbox" checked={reviewEvidence} onChange={e => setReviewEvidence(e.target.checked)} aria-label="额外证据复核" />额外证据复核
              </label>
              {contextUsage && <span title="上次请求的服务端消息估算，含系统提示、材料和工具结果；不含工具定义和输出预留，图片按固定值估算，并非服务商精确用量">上次请求约 {contextUsage.after.toLocaleString()} / {contextUsage.window.toLocaleString()} tokens</span>}
              {contextUsage?.compacted && <span role="status">较早消息已{contextUsage.summarized ? '压缩为摘要' : '移出本次上下文'}，完整历史仍保留</span>}
            </div>
            {configOpen && selectedModel && <div className="mx-3 rounded-lg border border-[var(--border)] p-3 flex flex-wrap items-end gap-3 text-xs">
              <label>上下文 tokens<input aria-label="上下文 tokens" type="number" min="1" className="input" value={contextDraft} onChange={e => setContextDraft(e.target.value)} placeholder="自动" /></label>
              <label>思考等级<select aria-label="思考等级" className="input" value={effortDraft} onChange={e => setEffortDraft(e.target.value)}><option value="">自动</option>{['low','medium','high','xhigh','max'].map(v => <option key={v}>{v}</option>)}</select></label>
              <label>图片输入<select aria-label="图片输入" className="input" value={imageDraft} onChange={e => setImageDraft(e.target.value)}><option value="auto">未声明</option><option value="true">支持</option><option value="false">不支持</option></select></label>
              <button className="btn-primary" disabled={configBusy || busy} onClick={() => void saveConfig()}>保存模型配置</button>
              <button className="btn-ghost" onClick={() => setConfigOpen(false)}>取消</button>
              <p className="w-full text-faint">设置应用于此模型的后续调用；共享连接会同步。思考等级需与服务商支持的参数一致。</p>
            </div>}
            {!materials.ready && <p role="status" className="px-3 text-xs">正在恢复附件和排队草稿…</p>}
            {materials.error && <p role="alert" className="px-3 text-xs text-[var(--danger)]">附件或排队草稿未能保存到本机，请勿关闭页面。<button className="btn-ghost" onClick={() => materials.update(value => ({ ...value }))}>重试保存</button></p>}
            {materials.saving && <p role="status" className="px-3 text-xs text-faint">正在保存草稿…</p>}
            {queue.length > 0 && <div className="mx-3 max-h-40 overflow-auto rounded-lg border border-[var(--border)] p-2 text-xs" aria-label="待发送队列">
              <div className="flex items-center gap-2"><span>已排队 {queue.length} 条 · {queuePaused ? '已暂停' : '当前回答成功后依次发送'}</span>
                {queuePaused ? <button className="btn-ghost" disabled={busy || loading || !!loadError || serverPending || !!pendingQuestion || queue[0].state === 'sending'} onClick={() => { pauseRef.current = false; setQueuePaused(false); }}>继续队列</button> : <button className="btn-ghost" onClick={pauseQueue}>暂停队列</button>}
              </div>
              {queue.map((item, index) => <div key={item.id} className="flex items-center gap-2 py-1">
                <span className="min-w-0 flex-1 truncate" title={item.text}>{index + 1}. {item.text} · {item.extra.attachments?.length ?? 0} 个附件</span>
                {item.state === 'sending' && <span>发送状态待确认，请检查历史并使用原消息重试</span>}
                {item.state === 'waiting' && <button className="btn-ghost" disabled={!!input.trim() || !!attachments.length || uploading} onClick={() => {
                  setInput(item.text);
                  setModelId(String(item.extra.model_config_id ?? ''));
                  setReviewEvidence(!!item.extra.review_evidence);
                  setManualSkillId(String(item.extra.skill_ids?.[0] ?? ''));
                  onContextLoaded(activeConv!, item.extra.paper_ids?.length ? paperSetContext(item.extra.paper_ids.map(id => ({id, title: paperContext?.papers?.find(p => p.id === id)?.title ?? null}))) : item.extra.paper_id == null ? null : {paperId: item.extra.paper_id, paperTitle: null, selectedText: item.extra.selected_text ?? null});
                  materials.update(previous => ({ attachments: item.extra.attachments ?? [], queue: finishQueued(previous.queue, item.id) }));
                  pauseQueue();
                }} aria-label={`编辑排队消息 ${index + 1}`}>编辑</button>}
                <button className="btn-ghost" disabled={busy && item.state === 'sending'} onClick={() => materials.update(previous => ({ ...previous, queue: finishQueued(previous.queue, item.id) }))} aria-label={`移除排队消息 ${index + 1}`}>移除</button>
              </div>)}
              {pendingQuestion && <p>请先回答 AI 的补充问题，再继续队列。</p>}
            </div>}
            {attachments.length > 0 && <div className="flex flex-wrap gap-2 px-3 py-2">{attachments.map((a, i) => <AttachmentChip key={i} attachment={a} onRemove={() => setAttachments(items => items.filter((_, index) => index !== i))} />)}</div>}
            {attachments.some(a => a.kind === 'text') && <p className="px-3 pb-1 text-xs text-faint">文件按提取的文字发送，可点击附件预览；PDF、Word 中的图表请另附截图。</p>}
            {attachments.some(a => a.kind === 'image') && selectedModel?.supports_images === false && <p role="alert" className="px-3 text-sm text-[var(--danger)]">当前模型仅支持文本，请切换支持图片的模型后发送。</p>}
            <div
              onDragOver={e => { if (e.dataTransfer.types.includes('Files')) e.preventDefault(); }}
              onDrop={e => { if (e.dataTransfer.files.length) { e.preventDefault(); void addFiles(Array.from(e.dataTransfer.files)); } }}
              className="chat-composer flex flex-wrap items-end gap-2"

            >
              <input ref={fileRef} type="file" multiple className="hidden" accept=".png,.jpg,.jpeg,.webp,.gif,.bmp,.pdf,.docx,.txt,.md,.csv,.tsv,.json,.log,.py,.js,.ts,.tex,.bib,.yaml,.yml,.xml,.html,.css,.r" onChange={e => { void addFiles(Array.from(e.target.files || [])); e.target.value = ''; }} />
              <button type="button" className="btn-ghost shrink-0" disabled={uploading || loading || !materials.ready} onClick={() => fileRef.current?.click()} title="添加图片、PDF、Word 或文本；每个最多 10 MB">{uploading ? "读取中…" : "+ 附件"}</button>
              <textarea
                onPaste={e => { const files = Array.from(e.clipboardData.items).filter(i => i.kind === 'file').map(i => i.getAsFile()).filter((f): f is File => !!f); if (files.length) { e.preventDefault(); void addFiles(files); } }}
                ref={taRef}
                disabled={loading || !!loadError || creating || !materials.ready}
                aria-label="向论文库提问"
                className="input order-first min-w-0 basis-full resize-none"
                rows={1}
                placeholder={pendingQuestion ? "直接补充信息或调整需求，AI 会继续处理…" : "输入问题，Ctrl+V 粘贴截图，或拖入文件…（Shift+回车换行）"}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (shouldSubmitOnEnter(e.key, e.shiftKey, e.nativeEvent.isComposing)) {
                    e.preventDefault();
                    send();
                  }
                }}
              />
              {busy || serverPending ? (
                <div className="ml-auto flex gap-2 shrink-0">
                  <button type="button" onClick={queueCurrentTurn} className="btn-ghost px-3" disabled={(!input.trim() && !attachments.length) || uploading || !materials.ready} title="当前回答结束后发送这条问题">排队发送</button>
                  <button onClick={stop} className="btn-ghost px-4" title="停止后不再发起工具调用；已发送的模型请求可能需要等待返回" disabled={stopping}>
                    <SquareIcon size={12} /> {stopping ? "停止中…" : "停止"}
                  </button>
                </div>
              ) : (
                <button
                  onClick={send}
                  disabled={(!input.trim() && !attachments.length) || !materials.ready || uploading || loading || !!loadError || creating || (attachments.some(a => a.kind === "image") && selectedModel?.supports_images === false)}
                  className="btn-primary ml-auto shrink-0 px-5"
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

function AttachmentChip({ attachment: a, onRemove }: { attachment: ChatAttachment; onRemove?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  return <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] p-2 text-left text-xs max-w-full">
    <button type="button" className="flex items-center gap-2" onClick={() => setExpanded(!expanded)} title="查看附件">
      {a.kind === 'image' && <img src={a.data_url} alt={a.name} className="h-12 w-16 rounded object-contain" />}
      <span className="max-w-[220px] truncate">{a.name}</span><span className="text-faint">{a.kind === 'text' ? `${a.text.length} 字符` : '图片'}</span>
    </button>
    {expanded && (a.kind === 'image' ? <img src={a.data_url} alt={a.name} className="mt-2 max-h-96 max-w-full object-contain" /> : <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap">{a.text}</pre>)}
    {onRemove && <button type="button" className="btn-ghost text-xs mt-1" aria-label={`移除 ${a.name}`} onClick={onRemove}>移除</button>}
  </div>;
}
