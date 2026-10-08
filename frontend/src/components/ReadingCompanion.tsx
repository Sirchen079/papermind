import { useCallback, useEffect, useRef, useState } from 'react';
import { useApi } from '../workspaceContext';
import { usePaperDraft, libraryScope } from './usePaperDraft';
import { useChatDraft } from './useChatDraft';
import { useWorkspace } from '../workspaceContext';
import { useToast } from './ui/Toast';
import {appendPageAttachment} from '../pages/chatMaterialsModel';
import type {ComposerMaterials} from '../pages/Chat';
import { AgentActivity } from './AgentActivity';
import Chat from '../pages/Chat';
import type { PaperChatContext } from '../pages/chatContextModel';

export type ReadingSelection = {text: string; page: number; action: 'ask'; nonce: number};

export function ReadingCompanion({paperId, title, selection, preparation, onOpenPaper, currentPage, pageReady}: {
  paperId: number; title: string | null; selection: ReadingSelection | null;
  preparation: {status: string; message: string}; onOpenPaper: (id: number, page?: number) => void;
  currentPage: number; pageReady: boolean;
}) {
  const api = useApi();
  const [saved, setSaved] = usePaperDraft(paperId, {conversation: 0, text: '', quote: '', page: 0}, 'companion');
  const {workspace} = useWorkspace();
  const toast = useToast();
  const materials = useChatDraft<ComposerMaterials>(`${libraryScope()}:${workspace.id}:${saved.conversation}`, {attachments: [], queue: []});
  const [addingPage, setAddingPage] = useState<number|null>(null);
  const [pageError, setPageError] = useState('');
  const addingRef = useRef(false);
  const aliveRef = useRef(true);
  useEffect(() => {aliveRef.current = true; return () => {aliveRef.current = false;};}, []);
  const savedRef = useRef(saved); savedRef.current = saved;
  const saveRef = useRef(setSaved); saveRef.current = setSaved;
  async function bringPage() {
    if (addingRef.current || !saved.conversation || !materials.ready || !pageReady) return;
    const page = currentPage;
    const conversation = saved.conversation;
    // The captured update writes to this conversation's existing draft even
    // when the reader changes conversations while the page is being rendered.
    const target = materials.update;
    addingRef.current = true; setAddingPage(page); setPageError('');
    try {
      const item = await api.paperPageAttachment(paperId, page);
      const stored = await target(previous => appendPageAttachment(previous, item));
      if (aliveRef.current) {
        if (!stored) setPageError('原页已在输入区，附件草稿尚未保存成功；关闭前请重试带入本页。');
        else if (savedRef.current.conversation === conversation) toast.success(`PDF第${page}页原图已带入，可以继续写问题。`);
        else toast.info(`PDF第${page}页原图已加入此前的伴读会话，切回后可查看。`);
      }
    } catch (e: any) {if (aliveRef.current) setPageError(e.message || '原页读取失败，请重试。');}
    finally {addingRef.current = false; if (aliveRef.current) setAddingPage(null);}
  }
  const creating = useRef<Promise<{id: number; title: string}> | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState('');
  const [context, setContext] = useState<PaperChatContext | null>({paperId, paperTitle: title, selectedText: saved.quote ? `第 ${saved.page} 页选文：\n${saved.quote}` : null});
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
    setContext({paperId, paperTitle: title, selectedText: `第 ${selection.page} 页选文：\n${selection.text}`});
    saveRef.current({...savedRef.current, quote: selection.text, page: selection.page});
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
  return <section className="reading-companion" aria-label="AI 伴读">
    <header className="companion-intro"><div className="companion-heading"><span className="companion-mark" aria-hidden="true">✦</span><div><h3>一起读，深入想</h3><p>阅读 · 讨论 · 行动</p></div></div>
      <p className="companion-paper" title={title ?? ''}>{title ?? '当前论文'}</p>
      <div className="companion-readiness"><span className={preparation.status === 'loading' ? 'status-dot is-loading' : 'status-dot'} /><span>{preparation.message}</span></div>
      <button type="button" className="btn-ghost mt-2 text-xs" disabled={addingPage !== null || !pageReady || !saved.conversation || !materials.ready}
        onClick={() => void bringPage()} title="把当前 PDF 页作为图片加入输入区，再写问题发送。">{addingPage !== null ? `正在带入第${addingPage}页…` : `带入第${currentPage}页原图`}</button>
      {pageError && <p role="alert" className="mt-1 text-xs text-[var(--danger)]">{pageError}</p>}
    </header>
    {saved.conversation ? <Chat key={saved.conversation} embedded activeConv={saved.conversation} setActiveConv={selectConversation}
      initialDraft={saved.text} onOpenPaper={onOpenPaper} paperContext={context} onContextLoaded={loaded}
      onInitialDraftConsumed={() => saveRef.current({...savedRef.current, text: ''})}
      onSelectionConsumed={consume} onConversationDeleted={() => selectConversation(null)}
      onClearPaperContext={async () => {
        if (context?.selectedText) { consume(); return; }
        await api.clearConversationPaper(saved.conversation); setContext(null);
      }} /> : <div className="p-4">{error ? <p role="alert">{error}<button className="btn-ghost" onClick={() => setAttempt(n => n + 1)}>重试</button></p> : <AgentActivity label="正在准备伴读会话" />}</div>}
  </section>;
}
