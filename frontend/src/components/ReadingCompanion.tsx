import { useEffect, useRef, useState } from 'react';
import { useApi } from '../workspaceContext';
import type { ChatMessageExtra, ChatModel } from '../api';
import { usePaperDraft } from './usePaperDraft';
import { MarkdownContent } from './MarkdownContent';
import { AskUserCard } from './AskUserCard';

export type ReadingSelection = {text: string; page: number; action: 'ask' | 'translate'; nonce: number};

export function ReadingCompanion({paperId, selection, preparation}: {
  paperId: number; selection: ReadingSelection | null; preparation: {status: string; message: string};
}) {
  const api = useApi();
  const [saved, setSaved] = usePaperDraft(paperId, {conversation: 0, text: '', quote: '', page: 0}, 'companion');
  const [models, setModels] = useState<ChatModel[]>([]);
  const [model, setModel] = useState<number>();
  const [messages, setMessages] = useState<Awaited<ReturnType<typeof api.getConversation>>['messages']>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [live, setLive] = useState('');
  const [status, setStatus] = useState('');
  const [translation, setTranslation] = useState('');
  const [translationError, setTranslationError] = useState('');
  const [translating, setTranslating] = useState(false);
  const [target, setTarget] = useState('中文');
  const [original, setOriginal] = useState('');
  const controller = useRef<AbortController | null>(null);
  const activeId = useRef(0);
  const mounted = useRef(true);
  const latestSaved = useRef(saved);
  latestSaved.current = saved;
  const generation = useRef(0);
  const inFlight = useRef(false);
  const [historyReady, setHistoryReady] = useState(!saved.conversation);
  const [historyAttempt, setHistoryAttempt] = useState(0);
  const tail = useRef<HTMLDivElement>(null);
  useEffect(() => { api.chatModels().then(setModels).catch(e => setError(e.message)); }, [api]);
  useEffect(() => {
    let alive = true;
    if (!saved.conversation) { setMessages([]); setHistoryReady(true); return; }
    setHistoryReady(false);
    if (saved.conversation) api.getConversation(saved.conversation).then(c => {
      if (alive) { if (c.paper_id !== paperId) throw new Error('伴读会话与论文不匹配'); setMessages(c.messages); setHistoryReady(true); }
    }).catch(e => { if (alive) setError(`加载伴读历史失败：${e.message}`); });
    return () => { alive = false; };
  }, [api, saved.conversation, paperId, historyAttempt]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++; if (activeId.current) void api.stopChat(activeId.current).catch(() => {}); controller.current?.abort(); }; }, [api]);
  useEffect(() => { tail.current?.scrollIntoView({block: 'nearest'}); }, [messages, live, status]);
  useEffect(() => {
    if (!selection) return;
    if (selection.action === 'ask') setSaved({...saved, quote: selection.text, page: selection.page});
    else { setOriginal(selection.text); void translate(selection.text); }
  }, [selection]);

  async function translate(text = original) {
    const version = ++generation.current;
    setTranslating(true); setTranslation(''); setTranslationError('');
    try {
      const result = await api.translateSelection(paperId, text, target, model);
      if (generation.current === version) setTranslation(result.text);
    } catch (e: any) { if (generation.current === version) setTranslationError(e.message); }
    finally { if (generation.current === version) setTranslating(false); }
  }

  async function send(text = saved.text, extra: ChatMessageExtra = {}) {
    if (inFlight.current || !text.trim() || !historyReady) return;
    if (saved.quote.length > 3900 && !extra.retry_message_id) { setError('选中文本过长，请缩小到 3900 字以内后提问。'); return; }
    inFlight.current = true; setBusy(true); setError(''); setLive(''); setStatus('正在准备回答…');
    let id = saved.conversation;
    const ac = new AbortController(); controller.current = ac;
    let accepted = false;
    try {
      if (!id) { id = (await api.createConversation(paperId)).id; setSaved({...saved, conversation: id}); }
      if (!mounted.current) return;
      activeId.current = id;
      let complete = false;
      for await (const {event, data} of api.streamMessage(id, text, ac.signal, {
        paper_id: paperId, model_config_id: model,
        selected_text: saved.quote ? `第 ${saved.page} 页选文：\n${saved.quote}`.slice(0, 4000) : undefined, ...extra,
      })) {
        if (event === 'accepted') {
          accepted = true;
          const current = latestSaved.current;
          setSaved({...current, conversation: id, text: current.text === saved.text ? '' : current.text,
            quote: current.quote === saved.quote ? '' : current.quote, page: current.quote === saved.quote ? 0 : current.page});
          setMessages((await api.getConversation(id)).messages);
        } else if (event === 'delta') setLive(data.content ?? '');
        else if (event === 'status') setStatus(data.phase === 'tool' ? `正在使用 ${data.name}…` : '正在思考…');
        else if (event === 'done' || event === 'ask_user') { complete = true; break; }
        else if (event === 'error') throw new Error(data.message || '回答失败，请重试');
      }
      if (!complete) throw new Error('连接中断，可以重试原问题。');
    } catch (e: any) { setError(e.name === 'AbortError' ? '已停止回答' : e.message); }
    finally {
      if (id) try { setMessages((await api.getConversation(id)).messages); } catch { setError('历史刷新失败，请重新打开伴读查看已保存的回答。'); }
      if (!accepted) setStatus('问题尚未确认接收，草稿已保留'); else setStatus('');
      setLive(''); setBusy(false); inFlight.current = false; activeId.current = 0;
    }
  }

  return <section className="flex h-full min-h-0 flex-col gap-3 p-3" aria-label="AI 伴读">
    <p className="text-xs text-muted">{preparation.status === 'ready' ? '已关联本篇论文，可讨论方法、公式、实验与 idea。' : `${preparation.message}；现在也可以先讨论选文。`}</p>
    <select className="input w-full text-xs" aria-label="伴读模型" value={model ?? ''} disabled={busy || translating} onChange={e => setModel(e.target.value ? Number(e.target.value) : undefined)}>
      <option value="">默认对话模型</option>{models.map(m => <option key={m.id} value={m.id}>{m.name} · {m.provider}</option>)}
    </select>
    {original && <section className="max-h-72 shrink-0 space-y-2 overflow-y-auto rounded-lg border p-2 text-sm" aria-label="划词翻译">
      <details><summary>查看原文</summary><p className="max-h-32 overflow-auto whitespace-pre-wrap">{original}</p></details>
      <div className="flex gap-2"><select aria-label="翻译目标语言" className="input text-xs" value={target} onChange={e => setTarget(e.target.value)}><option>中文</option><option>English</option></select><button className="btn-ghost text-xs" disabled={translating} onClick={() => void translate()}>重新翻译</button><button className="btn-ghost text-xs" onClick={() => { generation.current++; setTranslating(false); setOriginal(''); }}>关闭</button></div>
      {translating ? <p role="status">翻译中…</p> : <MarkdownContent content={translation} />}
      {translationError && <p role="alert">{translationError}</p>}
    </section>}
    <div className="min-h-24 flex-1 space-y-4 overflow-y-auto" aria-live="polite">
      {!messages.length && <p className="text-sm text-muted">可以直接提问，也可以划选正文后点击“问 AI”。例如：这篇论文的方法依赖哪些假设？</p>}
      {messages.map(m => <article key={m.id} className="space-y-2 text-sm"><strong>{m.role === 'user' ? '你' : 'AI'}</strong><MarkdownContent content={m.content} />
        {m.clarification && <AskUserCard request={m.clarification} conversationId={saved.conversation} disabled={busy} onAnswer={(response, text) => void send(text, {clarification_response: response})} />}
        {m.error_message && <p className="text-xs text-[var(--danger)]">{m.error_message}</p>}
        {m.role === 'user' && m.retryable && <button disabled={busy} className="btn-ghost text-xs" onClick={() => void send(m.content, {retry_message_id: m.id})}>重试原问题</button>}
      </article>)}
      {busy && <article className="text-sm"><p role="status" className="text-xs text-muted">{status}</p><MarkdownContent content={live} /></article>}
      <div ref={tail} />
    </div>
    {error && <p role="alert" className="text-xs text-[var(--danger)]">{error}</p>}
    {!historyReady && !busy && <div className="flex gap-2"><button className="btn-ghost text-xs" onClick={() => setHistoryAttempt(n => n + 1)}>重新加载历史</button><button className="btn-ghost text-xs" onClick={() => { setSaved({...saved, conversation: 0}); setError(''); }}>新建伴读会话</button></div>}
    {saved.quote && <div className="rounded border p-2 text-xs"><p className="max-h-24 overflow-auto">第 {saved.page} 页：{saved.quote}</p><button className="btn-ghost text-xs" onClick={() => setSaved({...saved, quote: '', page: 0})}>取消引用</button></div>}
    <textarea aria-label="伴读问题" className="input min-h-20 w-full resize-y text-sm" placeholder="问问这篇论文…（Ctrl+Enter 发送）" value={saved.text} disabled={busy} onChange={e => setSaved({...saved, text: e.target.value})} onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} />
    <div className="flex gap-2"><button className="btn-primary text-sm" disabled={busy || !historyReady || !saved.text.trim()} onClick={() => void send()}>发送</button>{busy && <button className="btn-ghost text-sm" onClick={async () => { try { if (activeId.current) await api.stopChat(activeId.current); controller.current?.abort(); } catch (e: any) { setError(e.message); } }}>停止</button>}</div>
  </section>;
}
