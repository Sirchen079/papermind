import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useApi } from '../workspaceContext';
import { X } from '../icons';
import { MarkdownContent } from './MarkdownContent';
import { useToast } from './ui/Toast';
import { TranslationModelControl, useTranslationModel } from './TranslationModelSettings';
import './TranslationPopover.css';

export interface TranslationSelection {
  text: string;
  page: number;
  nonce: number;
  anchor: { left: number; right: number; top: number; bottom: number };
}

export function TranslationPopover({ paperId, selection, readingArea, onClose }: {
  paperId: number;
  selection: TranslationSelection;
  readingArea: HTMLElement | null;
  onClose: () => void;
}) {
  const api = useApi();
  const toast = useToast();
  const config = useTranslationModel();
  const [target, setTarget] = useState('中文');
  const [result, setResult] = useState<{ text: string; model: string } | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [position, setPosition] = useState({ left: 12, top: 12 });
  const panelRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const dragRef = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const tooLong = selection.text.length > 12000;

  const clampPosition = (left: number, top: number) => {
    const rect = panelRef.current?.getBoundingClientRect();
    return {
      left: Math.max(12, Math.min(left, window.innerWidth - (rect?.width ?? 400) - 12)),
      top: Math.max(12, Math.min(top, window.innerHeight - (rect?.height ?? 300) - 12)),
    };
  };
  useLayoutEffect(() => {
    const rect = panelRef.current?.getBoundingClientRect();
    if (!rect) return;
    const area = readingArea?.getBoundingClientRect();
    const right = area?.right ?? window.innerWidth;
    const left = area?.left ?? 0;
    const anchor = selection.anchor;
    let x = anchor.right + 12;
    let y = anchor.top;
    if (x + rect.width > right - 12) {
      if (anchor.left - rect.width - 12 >= left + 12) x = anchor.left - rect.width - 12;
      else { x = Math.max(left + 12, Math.min(anchor.left, right - rect.width - 12)); y = anchor.bottom + 12; }
    }
    setPosition(clampPosition(x, y));
  }, [selection.nonce, readingArea]);
  useEffect(() => {
    closeRef.current?.focus({ preventScroll: true });
    const resize = () => setPosition(current => {
      const next = clampPosition(current.left, current.top);
      return next.left === current.left && next.top === current.top ? current : next;
    });
    const observer = new ResizeObserver(resize);
    if (panelRef.current) observer.observe(panelRef.current);
    window.addEventListener('resize', resize);
    return () => { observer.disconnect(); window.removeEventListener('resize', resize); };
  }, []);

  useEffect(() => {
    if (!config.ready || tooLong) { setLoading(false); setResult(null); setError(''); return; }
    const controller = new AbortController();
    setLoading(true); setError(''); setResult(null);
    api.translateSelection(paperId, selection.text, target, config.model ? Number(config.model) : undefined, controller.signal)
      .then(value => { if (!controller.signal.aborted) setResult(value); })
      .catch((e: Error) => { if (!controller.signal.aborted) setError(e.message || '翻译失败，请重试。'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [api, paperId, selection.nonce, selection.text, target, config.ready, config.model, tooLong, attempt]);

  async function copy() {
    if (!result) return;
    try { await navigator.clipboard.writeText(result.text); toast.success('译文已复制'); }
    catch { toast.error('复制失败，可以直接选中译文复制。'); }
  }

  return createPortal(<div ref={panelRef} role="dialog" aria-modal="false" aria-label="划词翻译"
    className="translation-popover" style={{ left: position.left, top: position.top }}>
    <header className="translation-popover-header"
      onPointerDown={event => {
        if (event.button !== 0 || (event.target as Element).closest('button')) return;
        dragRef.current = { x: event.clientX, y: event.clientY, ...position };
        event.currentTarget.setPointerCapture(event.pointerId); event.preventDefault();
      }}
      onPointerMove={event => {
        const drag = dragRef.current;
        if (drag) setPosition(clampPosition(drag.left + event.clientX - drag.x, drag.top + event.clientY - drag.y));
      }}
      onPointerUp={event => {
        dragRef.current = null;
        if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
      }}
      onPointerCancel={() => { dragRef.current = null; }}>
      <div><h3>划词翻译</h3><span className="text-xs text-muted">第 {selection.page} 页 · 拖动标题可移动</span></div>
      <button ref={closeRef} className="btn-ghost" aria-label="关闭翻译" onClick={onClose}><X size={16} /></button>
    </header>
    <div className="translation-popover-body">
      <div className="translation-popover-controls">
        <TranslationModelControl config={config} />
        <label className="block text-xs text-muted">译为
          <select aria-label="翻译目标语言" className="input mt-1 w-full text-xs" value={target} onChange={event => setTarget(event.target.value)}>
            <option>中文</option><option>English</option>
          </select>
        </label>
      </div>
      <details className="translation-original"><summary>查看原文 · {selection.text.length} 字符</summary><p>{selection.text}</p></details>
      <div className="translation-result" aria-live="polite" aria-busy={loading}>
        {tooLong ? <p role="alert">选文超过 12,000 字符，请选择较短的段落后翻译。</p>
          : loading ? <p role="status" className="text-sm text-muted">正在翻译选文…</p>
          : error ? <p role="alert" style={{ color: 'var(--danger)' }}>{error}</p>
          : result ? <MarkdownContent content={result.text} /> : null}
      </div>
    </div>
    <footer className="translation-popover-footer">
      <span className="truncate text-xs text-muted" title={result?.model}>{result ? `模型：${result.model}` : '译文仅供当前阅读使用'}</span>
      <button className="btn-ghost text-xs" onClick={() => setAttempt(n => n + 1)} disabled={loading || !config.ready || tooLong}>{error ? '重试翻译' : '重新翻译'}</button>
      <button className="btn-secondary text-xs" onClick={() => void copy()} disabled={!result || loading}>复制译文</button>
    </footer>
  </div>, document.body);
}
