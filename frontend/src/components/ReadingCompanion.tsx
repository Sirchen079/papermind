import { useCallback, useEffect, useRef, useState } from 'react';
import { useApi } from '../workspaceContext';
import { usePaperDraft } from './usePaperDraft';
import { MarkdownContent } from './MarkdownContent';
import { AgentActivity } from './AgentActivity';
import Chat from '../pages/Chat';
import type { PaperChatContext } from '../pages/chatContextModel';

export type ReadingSelection = {text: string; page: number; action: 'ask' | 'translate'; nonce: number};

export function ReadingCompanion({paperId, title, selection, preparation, onOpenPaper}: {
  paperId: number; title: string | null; selection: ReadingSelection | null;
  preparation: {status: string; message: string}; onOpenPaper: (id: number) => void;
}) {
  const api = useApi();
  const [saved, setSaved] = usePaperDraft(paperId, {conversation: 0, text: '', quote: '', page: 0}, 'companion');
  const savedRef = useRef(saved); savedRef.current = saved;
  const saveRef = useRef(setSaved); saveRef.current = setSaved;
  const creating = useRef<Promise<{id: number; title: string}> | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState('');
  const [context, setContext] = useState<PaperChatContext | null>({paperId, paperTitle: title, selectedText: saved.quote ? `第 ${saved.page} 页选文：\n${saved.quote}` : null});
  const [model, setModel] = useState<number>();
  const [original, setOriginal] = useState('');
  const [translation, setTranslation] = useState('');
  const [translationError, setTranslationError] = useState('');
  const [translating, setTranslating] = useState(false);
  const [target, setTarget] = useState('中文');
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  useEffect(() => {
    if (saved.conversation) return;
    let alive = true;
    setError('');
    const request = creating.current ?? (creating.current = api.createConversation(paperId));
    request.then(c => {
      if (alive) saveRef.current({...savedRef.current, conversation: c.id});
    }).catch(e => { if (alive) { creating.current = null; setError(e.message); } });
    return () => { alive = false; };
  }, [api, paperId, saved.conversation, attempt]);
  useEffect(() => {
    if (!selection) return;
    if (selection.action === 'ask') {
      setContext({paperId, paperTitle: title, selectedText: `第 ${selection.page} 页选文：\n${selection.text}`});
      saveRef.current({...savedRef.current, quote: selection.text, page: selection.page});
    } else { setOriginal(selection.text); void translate(selection.text); }
  }, [selection]);
  const loaded = useCallback((_id: number, current: PaperChatContext | null) => {
    setContext(previous => current ? {...current, selectedText: previous?.selectedText ?? null} : null);
  }, []);
  const consume = useCallback(() => {
    setContext(previous => previous ? {...previous, selectedText: null} : null);
    saveRef.current({...savedRef.current, quote: '', page: 0, text: ''});
  }, []);
  const selectConversation = useCallback((id: number | null) => {
    saveRef.current({...savedRef.current, conversation: id ?? 0});
    if (id === null) creating.current = null;
  }, []);
  async function translate(text = original) {
    const version = ++generation.current;
    setTranslating(true); setTranslation(''); setTranslationError('');
    try {
      const result = await api.translateSelection(paperId, text, target, model);
      if (generation.current === version) setTranslation(result.text);
    } catch (e: any) { if (generation.current === version) setTranslationError(e.message); }
    finally { if (generation.current === version) setTranslating(false); }
  }
  return <section className="reading-companion" aria-label="AI 伴读">
    <header className="companion-intro"><div className="companion-heading"><span className="companion-mark" aria-hidden="true">✦</span><div><h3>一起读，深入想</h3><p>阅读 · 讨论 · 行动</p></div></div>
      <p className="companion-paper" title={title ?? ''}>{title ?? '当前论文'}</p>
      <div className="companion-readiness"><span className={preparation.status === 'loading' ? 'status-dot is-loading' : 'status-dot'} /><span>{preparation.message}</span></div>
    </header>
    {original && <details className="companion-translation" open><summary>划词翻译</summary>
      <div className="flex flex-wrap gap-2 py-2"><select aria-label="翻译目标语言" className="input text-xs" value={target} onChange={e => setTarget(e.target.value)}><option>中文</option><option>English</option></select><button className="btn-ghost text-xs" disabled={translating} onClick={() => void translate()}>重新翻译</button><button className="btn-ghost text-xs" onClick={() => { generation.current++; setTranslating(false); setOriginal(''); }}>关闭</button></div>
      <div className="translation-content"><details><summary>原文</summary><p>{original}</p></details>{translating ? <AgentActivity label="正在翻译选文" /> : <MarkdownContent content={translation} />}{translationError && <p role="alert">{translationError}</p>}</div>
    </details>}
    {saved.conversation ? <Chat key={saved.conversation} embedded activeConv={saved.conversation} setActiveConv={selectConversation}
      initialDraft={saved.text} onOpenPaper={onOpenPaper} paperContext={context} onContextLoaded={loaded}
      onInitialDraftConsumed={() => saveRef.current({...savedRef.current, text: ''})}
      onModelSelected={setModel} onSelectionConsumed={consume} onConversationDeleted={() => selectConversation(null)}
      onClearPaperContext={async () => {
        if (context?.selectedText) { consume(); return; }
        await api.clearConversationPaper(saved.conversation); setContext(null);
      }} /> : <div className="p-4">{error ? <p role="alert">{error}<button className="btn-ghost" onClick={() => setAttempt(n => n + 1)}>重试</button></p> : <AgentActivity label="正在准备伴读会话" />}</div>}
  </section>;
}
