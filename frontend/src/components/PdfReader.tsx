/**
 * 内置 PDF 阅读器（P11.2 起步，P11.3–P11.5 与 T4/T5 在此扩展）。
 *
 * - 渲染：pdfjs-dist 单页 canvas + 文本层（textLayer，划选/搜索的基础）；
 *   worker 经 Vite `?url` 资产打包，零 CDN；中文 PDF 所需的 cMaps 与标准字体
 *   由 vite.config.ts 的 pdfjsAssets 插件在 dev/build 两条路径下提供。
 * - 控件：上一页/下一页/页码跳转 + 缩放（−/百分比/＋/重置）。
 * - 布局：全屏覆盖层，主区域滚动阅读；右侧栏展示并就地编辑该论文的
 *   笔记与摘录（备注可改、可直接新建笔记），划选可存摘录或「问 AI」。
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
// 官方 textLayer 样式（划选高亮、透明文本 span 的定位都由它定义）。
import "pdfjs-dist/web/pdf_viewer.css";
import "./PdfReader.css";
import { X } from "../icons";
import { useToast } from "./ui/Toast";
import { useConfirm } from "./ui/ConfirmDialog";
import type { PaperExcerpt, PaperNote } from "../api";
import { useApi, useWorkspace } from '../workspaceContext';
import { ReadingCompanion, type ReadingSelection } from './ReadingCompanion';
import { TranslationPopover, type TranslationSelection } from './TranslationPopover';
import { DocumentProcessingPanel } from './DocumentProcessingPanel';
import { shouldSubmitOnEnter } from "../pages/keyGuardModel";
import {
  READER_NOTE_KINDS,
  buildExcerptNotePayload,
  emptyReaderNoteDraft,
  readerNoteDraftError,
  type NoteForm,
} from "../pages/readingWorkspaceModel";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

const MIN_SCALE = 0.5;
const MAX_SCALE = 3;
const DEFAULT_SCALE = 1.2;

const NOTE_KIND_LABELS: Record<string, string> = {
  note: "笔记",
  question: "问题",
  idea: "想法",
  critique: "批注",
  todo: "待办",
};

interface PdfReaderProps {
  paperId: number;
  title: string | null;
  /** P11.3：保存划选摘录（quote + 当前页）；返回是否成功，成功后清除选区。 */
  onSaveExcerpt: (quote: string, page: number) => Promise<boolean>;
  /** T4：就地编辑摘录备注；返回是否成功，成功后收起编辑框。 */
  onSaveExcerptNote: (excerptId: number, note: string) => Promise<boolean>;
  /** T4：在阅读器内新建 PaperNote；返回是否成功，成功后清空草稿。 */
  onCreateNote: (payload: Record<string, unknown>) => Promise<boolean>;
  /** T5：带着当前选中正文去对话（论文上下文 + selected_text）。 */
  onAskAi?: (selectedText: string) => void;
  /** 右侧栏展示的该论文笔记与摘录（侧栏内可就地编辑备注、新建笔记）。 */
  notes: PaperNote[];
  excerpts: PaperExcerpt[];
  /** P11.5：恢复上次阅读页码（null 表示从头读）。 */
  initialPage: number | null;
  /** P11.5：翻页后上报进度（父级做 2s 防抖节流写回）。 */
  onProgress: (page: number) => void;
  onClose: () => void;
  onOpenPaper: (id: number) => void;
  onRefreshNotes: () => Promise<void>;
}

/** 划选状态：选中文本 + 浮动按钮锚点（视口坐标）。 */
interface SelectionAnchor {
  text: string;
  x: number;
  y: number;
  bottom: number;
}

function clampPage(page: number, pageCount: number): number {
  if (!Number.isFinite(page)) return 1;
  return Math.min(Math.max(Math.trunc(page), 1), Math.max(pageCount, 1));
}

export default function PdfReader({
  paperId,
  title,
  onSaveExcerpt,
  onSaveExcerptNote,
  onCreateNote,
  notes,
  excerpts,
  initialPage,
  onProgress,
  onClose,
  onOpenPaper,
  onRefreshNotes,
}: PdfReaderProps) {
  const {base}=useWorkspace();
  const api = useApi();
  const [tab, setTab] = useState<'ai' | 'notes'>('ai');
  const [readingSelection, setReadingSelection] = useState<ReadingSelection | null>(null);
  const [translationSelection, setTranslationSelection] = useState<TranslationSelection | null>(null);
  const [preparation, setPreparation] = useState({status: 'loading', message: '论文加载中…'});
  const [prepareAttempt, setPrepareAttempt] = useState(0);
  const [processingOpen, setProcessingOpen] = useState(false);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    setPreparation({status: 'loading', message: '论文加载中…'});
    async function poll(retry = false) {
      try {
        const result = await api.prepareReading(paperId, retry);
        if (!alive) return;
        setPreparation(result);
        if (result.status === 'loading') timer = setTimeout(() => void poll(), 1200);
      } catch (e: any) { if (alive) setPreparation({status: 'error', message: e.message}); }
    }
    void poll(prepareAttempt > 0);
    return () => { alive = false; clearTimeout(timer); };
  }, [api, paperId, prepareAttempt]);
  function useSelection(action: 'ask' | 'translate') {
    if (!selection) return;
    if (action === 'translate') {
      const range = window.getSelection();
      const rect = range?.rangeCount ? range.getRangeAt(0).getBoundingClientRect() : null;
      setTranslationSelection({ text: selection.text, page: currentPage, nonce: Date.now(),
        anchor: { left: rect?.left ?? selection.x, right: rect?.right ?? selection.x, top: selection.y, bottom: selection.bottom } });
    } else {
      setReadingSelection({text: selection.text, page: currentPage, action, nonce: Date.now()});
      setTab('ai'); setNotesOpen(true);
    }
    setSelection(null);
    window.getSelection()?.removeAllRanges();
  }
  const toast = useToast();
  const confirm = useConfirm();
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [renderAttempt, setRenderAttempt] = useState(0);
  const [pageCount, setPageCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const [scale, setScale] = useState(DEFAULT_SCALE);
  const [notesOpen, setNotesOpen] = useState(() => window.matchMedia("(min-width: 768px)").matches);
  const [rendering, setRendering] = useState(false);
  const [selection, setSelection] = useState<SelectionAnchor | null>(null);
  const [savingSelection, setSavingSelection] = useState(false);
  // T4 侧栏就地编辑：摘录备注 + 新建笔记（保存失败保留草稿与错误提示）。
  const [editingExcerptId, setEditingExcerptId] = useState<number | null>(null);
  const [excerptNoteDraft, setExcerptNoteDraft] = useState("");
  const [excerptNoteSaving, setExcerptNoteSaving] = useState(false);
  const [excerptNoteError, setExcerptNoteError] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState<NoteForm>(emptyReaderNoteDraft);
  const [noteSaving, setNoteSaving] = useState(false);
  const [noteError, setNoteError] = useState<string | null>(null);
  const hasDraft = !!noteDraft.content.trim() || !!noteDraft.tags.trim() ||
    (editingExcerptId !== null && excerptNoteDraft !== (excerpts.find(e => e.id === editingExcerptId)?.note ?? ""));
  useEffect(() => {
    if (!hasDraft && !noteSaving && !excerptNoteSaving && !savingSelection) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [hasDraft, noteSaving, excerptNoteSaving, savingSelection]);
  async function leaveReader(action: () => void) {
    if (noteSaving || excerptNoteSaving || savingSelection) { toast.error("正在保存，请稍候。"); return; }
    if (hasDraft && !await confirm({ title: "还有未保存的笔记", message: "离开会丢弃当前笔记或摘录备注草稿。可取消并先保存。", confirmText: "丢弃并离开", variant: "danger" })) return;
    action();
  }
  useEffect(() => {
    const onEscape = (event: KeyboardEvent) => {
      if (processingOpen) return;
      if (event.key !== "Escape" || event.isComposing || event.defaultPrevented || document.querySelector('[role="alertdialog"]')) return;
      // Editors and IME candidates own Escape while the user is typing.
      if (event.target instanceof Element && event.target.closest('input, textarea, select, [contenteditable="true"]')) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (translationSelection) { setTranslationSelection(null); return; }
      const activeSelection = window.getSelection();
      if (activeSelection && !activeSelection.isCollapsed && textLayerRef.current?.contains(activeSelection.anchorNode)) {
        activeSelection.removeAllRanges();
        setSelection(null);
        return;
      }
      void leaveReader(onClose);
    };
    window.addEventListener("keydown", onEscape, true);
    return () => window.removeEventListener("keydown", onEscape, true);
  });

  const docRef = useRef<PDFDocumentProxy | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const textLayerRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const selectionToolbarRef = useRef<HTMLDivElement | null>(null);
  const renderTaskRef = useRef<RenderTask | null>(null);
  const selectingRef = useRef(false);
  const renderSeq = useRef(0);
  const renderedPageRef = useRef<number | null>(null);
  const excerptSearchSeq = useRef(0);
  const [locatingExcerpt, setLocatingExcerpt] = useState(false);
  const excerptEditRef = useRef({ id: editingExcerptId, draft: excerptNoteDraft });
  excerptEditRef.current = { id: editingExcerptId, draft: excerptNoteDraft };
  // P11.4: 每页归一化文本缓存（去空白），供无页码摘录的全文搜索定位。
  const textCacheRef = useRef<Map<number, string> | null>(null);
  // P11.5: 恢复页码只在文档加载时读取一次（后续进度变化不触发重载）。
  const initialPageRef = useRef<number | null>(initialPage);
  // P11.5: 已上报的页码——恢复的初始页不重复上报。
  const reportedPageRef = useRef<number | null>(null);

  useEffect(() => {
    initialPageRef.current = initialPage;
  }, [initialPage]);

  // 加载文档（一个 paperId 只加载一次；卸载时销毁释放 worker 内存）。
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErrorMsg(null);
    setPageError(null);
    renderedPageRef.current = null;
    reportedPageRef.current = null;
    const task = pdfjsLib.getDocument({
      url: `${base}/papers/${paperId}/file`,
      cMapUrl: "/pdfjs/cmaps/",
      cMapPacked: true,
      standardFontDataUrl: "/pdfjs/standard_fonts/",
    });
    task.promise
      .then((doc) => {
        // cancelled 时无需单独销毁 doc：cleanup 里的 task.destroy() 会连 worker 一起释放。
        if (cancelled) return;
        docRef.current = doc;
        textCacheRef.current = new Map();
        setPageCount(doc.numPages);
        // P11.5: 恢复上次读到的页码（夹在 1..numPages 内）。
        const target = clampPage(initialPageRef.current ?? 1, doc.numPages);
        setCurrentPage(target);
        setPageInput(String(target));
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoading(false);
        const status = (err as { status?: number })?.status;
        setErrorMsg(
          status === 404
            ? "该论文没有可读的 PDF 文件。"
            : `PDF 加载失败：${err instanceof Error ? err.message : String(err)}`,
        );
      });
    return () => {
      cancelled = true;
      excerptSearchSeq.current++;
      task.destroy();
      docRef.current = null;
      textCacheRef.current = null;
    };
  }, [paperId, base, loadAttempt]);

  // 渲染当前页（canvas + 文本层）；页码或缩放变化时取消旧渲染再重画。
  useEffect(() => {
    const doc = docRef.current;
    if (!doc || loading) return;
    const seq = ++renderSeq.current;
    let cancelled = false;
    let textLayer: pdfjsLib.TextLayer | null = null;
    // Never leave the previous page's hit targets over a new canvas.
    textLayerRef.current?.replaceChildren();
    window.getSelection()?.removeAllRanges();
    setSelection(null);
    setPageError(null);
    setRendering(true);
    (async () => {
      try {
        const page = await doc.getPage(currentPage);
        if (cancelled || seq !== renderSeq.current) return;
        const viewport = page.getViewport({ scale });
        const canvas = canvasRef.current;
        const wrapper = wrapperRef.current;
        const textDiv = textLayerRef.current;
        if (!canvas || !wrapper || !textDiv) return;
        const scroll = scrollRef.current;
        const oldRect = wrapper.getBoundingClientRect();
        const scrollRect = scroll?.getBoundingClientRect();
        const focus = renderedPageRef.current === currentPage && oldRect.width > 0 && scroll && scrollRect
          ? { x: (scrollRect.left + scroll.clientWidth / 2 - oldRect.left) / oldRect.width,
              y: (scrollRect.top + scroll.clientHeight / 2 - oldRect.top) / oldRect.height }
          : null;
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;
        wrapper.style.width = `${Math.floor(viewport.width)}px`;
        wrapper.style.height = `${Math.floor(viewport.height)}px`;
        wrapper.style.setProperty("--scale-factor", String(viewport.scale));
        wrapper.style.setProperty("--total-scale-factor", String(viewport.scale * viewport.userUnit));
        if (focus && scroll && scrollRect) {
          const newRect = wrapper.getBoundingClientRect();
          scroll.scrollLeft += newRect.left + focus.x * newRect.width - scrollRect.left - scroll.clientWidth / 2;
          scroll.scrollTop += newRect.top + focus.y * newRect.height - scrollRect.top - scroll.clientHeight / 2;
        }
        renderedPageRef.current = currentPage;

        renderTaskRef.current?.cancel();
        const renderTask = page.render({
          canvas,
          viewport,
          transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
        });
        renderTaskRef.current = renderTask;
        try {
          await renderTask.promise;
        } catch (err) {
          if (cancelled || seq !== renderSeq.current) return;
          throw err;
        }
        if (cancelled || seq !== renderSeq.current) return;

        // 文本层：透明文本覆盖在 canvas 上，供划选（P11.3）与搜索定位。
        const textContent = await page.getTextContent();
        if (cancelled || seq !== renderSeq.current) return;
        textDiv.replaceChildren();
        textLayer = new pdfjsLib.TextLayer({
          textContentSource: textContent,
          container: textDiv,
          viewport,
        });
        await textLayer.render();
      } catch (err: unknown) {
        if (!cancelled && seq === renderSeq.current) {
          textLayerRef.current?.replaceChildren();
          setPageError(`页面渲染失败：${err instanceof Error ? err.message : String(err)}`);
        }
      } finally {
        if (!cancelled && seq === renderSeq.current) setRendering(false);
      }
    })();
    return () => {
      cancelled = true;
      textLayer?.cancel();
      textLayerRef.current?.replaceChildren();
      try {
        renderTaskRef.current?.cancel();
      } catch {
        /* already done */
      }
    };
  }, [currentPage, scale, loading, renderAttempt]);

  // Only a page change resets position; zoom keeps the visible page centre.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0, left: 0 });
    setPageInput(String(currentPage));
    setSelection(null);
  }, [currentPage]);

  // P11.3 划选：鼠标抬起时读取选区，非空则锚定「存为摘录」浮钮。
  const handleTextSelection = useCallback(() => {
    if (selectingRef.current) return;
    const sel = window.getSelection();
    const text = sel?.toString().replace(/\s+/g, " ").trim() ?? "";
    if (!sel || !sel.rangeCount || sel.isCollapsed || !text || !textLayerRef.current?.contains(sel.anchorNode) || !textLayerRef.current?.contains(sel.focusNode)) {
      setSelection(null);
      return;
    }
    try {
      const bounds = scrollRef.current?.getBoundingClientRect();
      const rects = Array.from(sel.getRangeAt(0).getClientRects()).filter(rect =>
        rect.width > 0 && rect.height > 0 && bounds && rect.bottom > bounds.top && rect.top < bounds.bottom && rect.right > bounds.left && rect.left < bounds.right,
      );
      const rect = rects[0];
      if (!rect || !bounds) { setSelection(null); return; }
      setSelection({ text, x: rect.left + rect.width / 2, y: rect.top, bottom: rects[rects.length - 1].bottom });
    } catch {
      setSelection(null);
    }
  }, []);

  // Measure actual controls: touch targets and translated labels can be taller
  // than the old fixed 44px offset, which covered the first selected line.
  useLayoutEffect(() => {
    const toolbar = selectionToolbarRef.current;
    const bounds = scrollRef.current?.getBoundingClientRect();
    if (!selection || !toolbar || !bounds) return;
    const { width, height } = toolbar.getBoundingClientRect();
    const left = Math.max(8, bounds.left + 8);
    const right = Math.min(window.innerWidth - 8, bounds.right - 8);
    toolbar.style.left = `${Math.max(left, Math.min(right - width, selection.x - width / 2))}px`;
    const above = selection.y - height - 8;
    toolbar.style.top = `${Math.max(bounds.top + 8, Math.min(bounds.bottom - height - 8,
      above >= bounds.top + 8 ? above : selection.bottom + 8))}px`;
  }, [selection, savingSelection]);

  // Wait until dragging ends; document-level release also covers the page margin.
  useEffect(() => {
    let frame = 0;
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(handleTextSelection);
    };
    const onPointerUp = () => { selectingRef.current = false; schedule(); };
    function onSelChange() {
      if (!selectingRef.current) schedule();
    }
    document.addEventListener("pointerup", onPointerUp);
    document.addEventListener("pointercancel", onPointerUp);
    document.addEventListener("selectionchange", onSelChange);
    window.addEventListener("resize", schedule);
    const observer = new ResizeObserver(schedule);
    if (scrollRef.current) observer.observe(scrollRef.current);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("pointerup", onPointerUp);
      document.removeEventListener("pointercancel", onPointerUp);
      document.removeEventListener("selectionchange", onSelChange);
      window.removeEventListener("resize", schedule);
      observer.disconnect();
    };
  }, [handleTextSelection]);

  // P11.5: 翻页后上报进度（恢复页/首页不重复上报；父级节流写回）。
  useEffect(() => {
    if (loading) return;
    if (reportedPageRef.current === null) {
      reportedPageRef.current = currentPage;
      return;
    }
    if (reportedPageRef.current !== currentPage) {
      reportedPageRef.current = currentPage;
      onProgress(currentPage);
    }
  }, [currentPage, loading, onProgress]);

  const goToPage = useCallback(
    (page: number) => {
      excerptSearchSeq.current++;
      setLocatingExcerpt(false);
      setPageInput(String(clampPage(page, pageCount)));
      setCurrentPage((cur) => {
        const next = clampPage(page, pageCount);
        return next === cur ? cur : next;
      });
    },
    [pageCount],
  );

  const commitPageInput = useCallback(() => {
    const parsed = Number(pageInput);
    if (!pageInput.trim() || !Number.isInteger(parsed) || parsed < 1) {
      setPageInput(String(currentPage));
      return;
    }
    goToPage(parsed);
  }, [pageInput, currentPage, goToPage]);

  const saveSelection = useCallback(async () => {
    if (!selection || savingSelection) return;
    const savedRange = window.getSelection()?.rangeCount ? window.getSelection()!.getRangeAt(0).cloneRange() : null;
    setSavingSelection(true);
    try {
      const ok = await onSaveExcerpt(selection.text, currentPage);
      if (ok) {
        toast.success("摘录已保存");
        const current = window.getSelection();
        const range = current?.rangeCount ? current.getRangeAt(0) : null;
        if (savedRange && range && savedRange.startContainer.isConnected &&
            range.startContainer === savedRange.startContainer && range.startOffset === savedRange.startOffset &&
            range.endContainer === savedRange.endContainer && range.endOffset === savedRange.endOffset) {
          setSelection(null);
          current?.removeAllRanges();
        }
      }
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "摘录保存失败，请重试。");
    } finally {
      setSavingSelection(false);
    }
  }, [selection, savingSelection, onSaveExcerpt, currentPage, toast]);

  // P11.4: 逐页取归一化文本（带缓存），按 quote 前缀尽力定位页码。
  const findPageByText = useCallback(async (quote: string, request: number): Promise<number | null> => {
    const doc = docRef.current;
    const cache = textCacheRef.current;
    if (!doc || !cache) return null;
    const needle = quote.replace(/\s+/g, "").slice(0, 40);
    if (!needle) return null;
    for (let p = 1; p <= doc.numPages; p++) {
      if (request !== excerptSearchSeq.current) return null;
      let text = cache.get(p);
      if (text === undefined) {
        const page = await doc.getPage(p);
        const content = await page.getTextContent();
        if (request !== excerptSearchSeq.current) return null;
        text = content.items.map((item) => ("str" in item ? item.str : "")).join("").replace(/\s+/g, "");
        cache.set(p, text);
      }
      if (text.includes(needle)) return p;
    }
    return null;
  }, []);

  // 点击摘录：有页码直接跳页；无页码全文搜索尽力定位，搜不到留在原页并提示。
  const jumpToExcerpt = useCallback(
    async (excerpt: PaperExcerpt) => {
      if (excerpt.page != null) {
        goToPage(excerpt.page);
        return;
      }
      const request = ++excerptSearchSeq.current;
      setLocatingExcerpt(true);
      try {
        const found = await findPageByText(excerpt.quote, request);
        if (request !== excerptSearchSeq.current) return;
        if (found != null) goToPage(found);
        else toast.info("未能在正文中定位该摘录，已保留当前页。");
      } catch (err: unknown) {
        if (request === excerptSearchSeq.current) toast.error(err instanceof Error ? err.message : "摘录定位失败，请重试。");
      } finally {
        if (request === excerptSearchSeq.current) setLocatingExcerpt(false);
      }
    },
    [goToPage, findPageByText, toast],
  );

  // T4：展开某条摘录的备注编辑框（带入现有 note，切换目标时清掉旧错误）。
  const beginExcerptNoteEdit = useCallback(async (excerpt: PaperExcerpt) => {
    if (excerptNoteSaving) return;
    if (editingExcerptId !== null && excerptNoteDraft !== (excerpts.find(e => e.id === editingExcerptId)?.note ?? "") &&
        !await confirm({ title: "当前备注尚未保存", message: "切换会丢弃当前备注的修改。", confirmText: "丢弃并切换", variant: "danger" })) return;
    setEditingExcerptId(excerpt.id);
    setExcerptNoteDraft(excerpt.note ?? "");
    setExcerptNoteError(null);
  }, [excerptNoteSaving, editingExcerptId, excerptNoteDraft, excerpts, confirm]);

  // T4：保存摘录备注；失败保留草稿并显示错误，不丢用户输入。
  const commitExcerptNote = useCallback(async () => {
    if (editingExcerptId == null || excerptNoteSaving) return;
    setExcerptNoteSaving(true);
    setExcerptNoteError(null);
    try {
      const ok = await onSaveExcerptNote(editingExcerptId, buildExcerptNotePayload(excerptNoteDraft));
      if (ok) {
        if (excerptEditRef.current.id === editingExcerptId && excerptEditRef.current.draft === excerptNoteDraft) {
          setEditingExcerptId(null);
          setExcerptNoteDraft("");
        }
        toast.success("摘录备注已保存");
      } else {
        setExcerptNoteError("保存失败，草稿已保留，请重试。");
      }
    } catch (err: unknown) {
      setExcerptNoteError(err instanceof Error ? err.message : "保存失败，草稿已保留。");
    } finally {
      setExcerptNoteSaving(false);
    }
  }, [editingExcerptId, excerptNoteDraft, excerptNoteSaving, onSaveExcerptNote, toast]);

  // T4：在阅读器内新建笔记；成功清空草稿，失败保留内容与错误。
  const commitReaderNote = useCallback(async () => {
    if (noteSaving) return;
    const validation = readerNoteDraftError(noteDraft);
    if (validation) {
      setNoteError(validation);
      return;
    }
    const payload: Record<string, unknown> = {
      kind: noteDraft.kind,
      content: noteDraft.content.trim(),
      tags: noteDraft.tags.split(",").map((item) => item.trim()).filter(Boolean),
    };
    setNoteSaving(true);
    setNoteError(null);
    try {
      const ok = await onCreateNote(payload);
      if (ok) {
        setNoteDraft(current => current === noteDraft ? emptyReaderNoteDraft() : current);
        toast.success("笔记已保存");
      } else {
        setNoteError("保存失败，草稿已保留，请重试。");
      }
    } catch (err: unknown) {
      setNoteError(err instanceof Error ? err.message : "保存失败，草稿已保留。");
    } finally {
      setNoteSaving(false);
    }
  }, [noteDraft, noteSaving, onCreateNote, toast]);

  const zoomIn = useCallback(() => {
    setScale((cur) => Math.min(MAX_SCALE, Math.round(cur * 1.2 * 100) / 100));
  }, []);
  const zoomOut = useCallback(() => {
    setScale((cur) => Math.max(MIN_SCALE, Math.round(cur / 1.2 * 100) / 100));
  }, []);
  const resetZoom = useCallback(() => setScale(DEFAULT_SCALE), []);

  return (
    <div className="fixed inset-0 z-40 flex flex-col" style={{ backgroundColor: "var(--bg)" }} role="dialog" aria-modal="true" aria-label="阅读 PDF">
      <header
        className="flex shrink-0 flex-wrap items-center gap-2 border-b px-4 py-2"
        style={{ borderColor: "var(--border)", backgroundColor: "var(--surface)" }}
      >
        <div className="min-w-0 flex-1 truncate text-sm font-medium">{title ?? "PDF 阅读"}</div>
        <div className="flex flex-wrap items-center gap-1">
          <button className="btn-ghost py-1 text-xs" onClick={() => goToPage(currentPage - 1)} disabled={currentPage <= 1 || loading}>
            上一页
          </button>
          <span className="flex items-center gap-1 text-xs text-muted">
            <input
              className="input w-14 py-1 text-center text-xs"
              value={pageInput}
              aria-label="页码"
              disabled={loading || !!errorMsg}
              onChange={(e) => setPageInput(e.target.value)}
              onKeyDown={(e) => {
                if (shouldSubmitOnEnter(e.key, false, e.nativeEvent.isComposing))
                  (e.target as HTMLInputElement).blur();
              }}
              onBlur={commitPageInput}
            />
            / {pageCount || "?"} 页
          </span>
          <button className="btn-ghost py-1 text-xs" onClick={() => goToPage(currentPage + 1)} disabled={pageCount === 0 || currentPage >= pageCount || loading}>
            下一页
          </button>
          <span className="mx-1 h-5 w-px" style={{ backgroundColor: "var(--border)" }} aria-hidden />
          <button className="btn-ghost py-1 text-xs" onClick={zoomOut} disabled={scale <= MIN_SCALE || loading} aria-label="缩小">
            −
          </button>
          <span className="w-12 text-center text-xs tabular-nums text-muted">{Math.round(scale * 100)}%</span>
          <button className="btn-ghost py-1 text-xs" onClick={zoomIn} disabled={scale >= MAX_SCALE || loading} aria-label="放大">
            ＋
          </button>
          <button className="btn-ghost py-1 text-xs" onClick={resetZoom} disabled={loading}>
            重置
          </button>
        </div>
        <span className="max-w-40 truncate text-xs text-muted" role="status" title={preparation.message}>{preparation.message}</span>
        {preparation.status === 'error' && <button className="btn-ghost text-xs" onClick={() => setPrepareAttempt(n => n + 1)}>重试加载</button>}
        <button className="btn-ghost shrink-0 text-xs" onClick={() => { setTranslationSelection(null); setProcessingOpen(true); }}>OCR / Markdown</button>
        <button className="btn-ghost shrink-0 py-1 text-xs" aria-expanded={notesOpen} aria-controls="pdf-reader-notes" onClick={() => setNotesOpen((open) => !open)}>
          {notesOpen ? "收起侧栏" : "AI 伴读 / 笔记"}
        </button>
        <button className="btn-subtle shrink-0 px-2" onClick={() => void leaveReader(onClose)} aria-label="退出阅读">
          <X size={18} />
        </button>
      </header>
      <div className="relative flex min-h-0 flex-1">
        <div
          ref={scrollRef}
          className="min-w-0 flex-1 overflow-auto"
          onPointerDown={() => { selectingRef.current = true; setSelection(null); }}
          onScroll={handleTextSelection}
        >
          {loading && (
            <p className="p-8 text-center text-sm text-muted">正在加载 PDF…</p>
          )}
          {!loading && errorMsg && (
            <div className="p-8 text-center text-sm" role="alert">
              <p style={{ color: "var(--danger)" }}>{errorMsg}</p>
              <button className="btn-ghost mt-2" onClick={() => setLoadAttempt(n => n + 1)}>重新打开 PDF</button>
            </div>
          )}
          {!loading && pageError && (
            <div className="p-4 text-center text-sm" role="alert">
              <p style={{ color: "var(--danger)" }}>{pageError}</p>
              <button className="btn-ghost mt-2" onClick={() => setRenderAttempt(n => n + 1)}>重试当前页</button>
            </div>
          )}
          {!loading && !errorMsg && (
            <div className={`flex w-max min-w-full justify-center p-4 ${pageError ? "invisible" : ""}`}>
              <div
                ref={wrapperRef}
                className="pdf-reader-page relative shadow-lg"
                style={{ backgroundColor: "white" }}
              >
                <canvas ref={canvasRef} className="block" />
                <div ref={textLayerRef} className="textLayer" />
              </div>
            </div>
          )}
        </div>
        <aside
          id="pdf-reader-notes"
          className={`${notesOpen ? "flex" : "hidden"} flex-col min-h-0 w-[420px] max-w-[90vw] max-md:absolute max-md:right-0 max-md:top-0 max-md:bottom-0 max-md:z-20 shrink-0 overflow-hidden border-l`}
          style={{ borderColor: "var(--border)", backgroundColor: "var(--surface)" }}
          aria-label="阅读侧栏"
        >
          <div className="reader-tabs flex shrink-0 gap-2 border-b p-2">
            <button className="btn-ghost text-xs" aria-pressed={tab === 'ai'} onClick={() => setTab('ai')}>AI 伴读</button>
            <button className="btn-ghost text-xs" aria-pressed={tab === 'notes'} onClick={() => { setTab('notes'); void onRefreshNotes(); }}>笔记与摘录</button>
            <button className="btn-ghost ml-auto text-xs md:hidden" onClick={() => setNotesOpen(false)}>收起</button>
          </div>
          <div className={tab === 'ai' ? 'min-h-0 flex-1' : 'hidden'}>
            <ReadingCompanion key={paperId} paperId={paperId} title={title} selection={readingSelection} preparation={preparation} onOpenPaper={id => { void leaveReader(() => onOpenPaper(id)); }} />
          </div>
          <div className={tab === 'notes' ? 'min-h-0 flex-1 overflow-auto p-3' : 'hidden'}>
            <h4 className="mb-2 text-sm font-semibold">笔记与摘录</h4>
            <section className="mb-4">
              <h5 className="mb-1.5 text-xs font-medium text-muted">摘录（{excerpts.length}）</h5>
              {locatingExcerpt && <p role="status" className="mb-2 text-xs text-muted">正在定位摘录…</p>}
              {excerpts.length === 0 && (
                <p className="text-xs text-faint">还没有摘录。在正文中划选文本即可保存。</p>
              )}
              <ul className="space-y-2">
                {excerpts.map((excerpt) => (
                  <li key={excerpt.id}>
                    <button
                      className="w-full rounded-lg border p-2 text-left text-xs transition hover:border-[var(--accent)]"
                      style={{ borderColor: "var(--border)" }}
                      onClick={() => jumpToExcerpt(excerpt)}
                      title={excerpt.page != null ? `跳到第 ${excerpt.page} 页` : "点击在正文中定位"}
                    >
                      <div className="mb-1 flex items-center gap-1.5">
                        {excerpt.page != null ? (
                          <span className="chip">第 {excerpt.page} 页</span>
                        ) : (
                          <span className="chip text-muted">未记页码</span>
                        )}
                      </div>
                      <p className="line-clamp-4 whitespace-pre-wrap text-muted">{excerpt.quote}</p>
                      {excerpt.note && <p className="mt-1 line-clamp-2">{excerpt.note}</p>}
                    </button>
                    {editingExcerptId === excerpt.id ? (
                      <div className="mt-1 space-y-1 rounded-lg border p-2" style={{ borderColor: "var(--accent)", backgroundColor: "var(--surface-2)" }}>
                        <textarea
                          className="input h-16 w-full resize-none py-1 text-xs"
                          placeholder="为这条摘录添加备注（可留空清除）"
                          value={excerptNoteDraft}
                          autoFocus
                          onChange={(e) => setExcerptNoteDraft(e.target.value)}
                          onKeyDown={(e) => {
                            // Ctrl/Cmd+Enter 保存；纯 Enter 换行（多行备注）。
                            if (shouldSubmitOnEnter(e.key, !(e.ctrlKey || e.metaKey), e.nativeEvent.isComposing)) {
                              e.preventDefault();
                              void commitExcerptNote();
                            }
                          }}
                          aria-label="摘录备注"
                        />
                        {excerptNoteError && (
                          <p className="text-xs" style={{ color: "var(--danger)" }}>{excerptNoteError}</p>
                        )}
                        <div className="flex gap-1">
                          <button onClick={commitExcerptNote} disabled={excerptNoteSaving} className="btn-primary py-0.5 text-xs">
                            {excerptNoteSaving ? "保存中…" : "保存备注"}
                          </button>
                          <button
                            disabled={excerptNoteSaving}
                            onClick={() => {
                              setEditingExcerptId(null);
                              setExcerptNoteError(null);
                            }}
                            className="btn-ghost py-0.5 text-xs"
                          >
                            取消
                          </button>
                        </div>
                      </div>
                    ) : (
                      <button disabled={excerptNoteSaving} onClick={() => void beginExcerptNoteEdit(excerpt)} className="btn-ghost mt-1 py-0.5 text-xs">
                        {excerpt.note ? "编辑备注" : "添加备注"}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <h5 className="mb-1.5 text-xs font-medium text-muted">笔记（{notes.length}）</h5>
              <div className="mb-2 space-y-1 rounded-lg border p-2" style={{ borderColor: "var(--border)", backgroundColor: "var(--surface-2)" }}>
                <select
                  className="input w-full py-1 text-xs"
                  value={noteDraft.kind}
                  onChange={(e) => setNoteDraft({ ...noteDraft, kind: e.target.value })}
                  aria-label="笔记类型"
                >
                  {READER_NOTE_KINDS.map((kind) => (
                    <option key={kind} value={kind}>
                      {NOTE_KIND_LABELS[kind] ?? kind}
                    </option>
                  ))}
                </select>
                <textarea
                  className="input h-16 w-full resize-none py-1 text-xs"
                  placeholder="读到此处想到…（Ctrl+Enter 保存）"
                  value={noteDraft.content}
                  onChange={(e) => setNoteDraft({ ...noteDraft, content: e.target.value })}
                  onKeyDown={(e) => {
                    // Ctrl/Cmd+Enter 保存；纯 Enter 换行（多行笔记）。
                    if (shouldSubmitOnEnter(e.key, !(e.ctrlKey || e.metaKey), e.nativeEvent.isComposing)) {
                      e.preventDefault();
                      void commitReaderNote();
                    }
                  }}
                  aria-label="笔记内容"
                />
                <input
                  className="input w-full py-1 text-xs"
                  placeholder="标签（逗号分隔，可留空）"
                  value={noteDraft.tags}
                  onChange={(e) => setNoteDraft({ ...noteDraft, tags: e.target.value })}
                  aria-label="笔记标签"
                />
                {noteError && (
                  <p className="text-xs" style={{ color: "var(--danger)" }}>{noteError}</p>
                )}
                <button onClick={commitReaderNote} disabled={noteSaving} className="btn-primary w-full py-1 text-xs">
                  {noteSaving ? "保存中…" : "保存笔记"}
                </button>
              </div>
              {notes.length === 0 && (
                <p className="text-xs text-faint">还没有笔记。直接在上方添加，无需离开阅读器。</p>
              )}
              <ul className="space-y-2">
                {notes.map((note) => (
                  <li key={note.id} className="rounded-lg border p-2 text-xs" style={{ borderColor: "var(--border)" }}>
                    <div className="mb-1 flex items-center gap-1.5">
                      <span className="chip text-muted">{NOTE_KIND_LABELS[note.kind] ?? note.kind}</span>
                      {note.tags.length > 0 && <span className="truncate text-faint">{note.tags.join(", ")}</span>}
                    </div>
                    <p className="whitespace-pre-wrap text-muted">{note.content}</p>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </aside>
      </div>
      {selection && (
        <div
          ref={selectionToolbarRef}
          role="toolbar"
          aria-label="选文操作"
          className="fixed z-50 flex max-w-[calc(100vw-16px)] flex-wrap items-center gap-1 rounded-lg px-1.5 py-1"
          style={{
            left: Math.max(120, Math.min(window.innerWidth - 120, selection.x)),
            top: Math.max(selection.y - 44, 8),
            backgroundColor: "var(--surface)",
            boxShadow: "var(--shadow-lg)",
          }}
          onMouseDown={(e) => e.preventDefault()}
        >
          <button
            className="rounded-md px-2 py-1 text-xs"
            style={{ backgroundColor: "var(--accent)", color: "var(--accent-contrast)" }}
            onClick={saveSelection}
            disabled={savingSelection}
          >
            {savingSelection ? "保存中…" : "存为摘录"}
          </button>
          <button className="btn-ghost text-xs" onClick={() => useSelection('translate')}>翻译</button>
          <button className="btn-ghost text-xs" onClick={() => useSelection('ask')}>问 AI</button>
        </div>
      )}
      {translationSelection && <TranslationPopover paperId={paperId} selection={translationSelection}
        readingArea={scrollRef.current} onClose={() => setTranslationSelection(null)} />}
      {processingOpen && <DocumentProcessingPanel paperId={paperId} onClose={() => setProcessingOpen(false)} onReady={() => setPrepareAttempt(n => n + 1)} />}
      {rendering && (
        <div
          className="pointer-events-none fixed bottom-4 left-4 rounded-lg px-3 py-1.5 text-xs text-muted"
          style={{ backgroundColor: "var(--surface)", boxShadow: "var(--shadow-md)" }}
        >
          渲染中…
        </div>
      )}
    </div>
  );
}
