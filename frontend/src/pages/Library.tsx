import { useApi } from '../workspaceContext';
import { useEffect, useMemo, useRef, useState } from "react";
import {
  MatrixRow,
  Paper,
  PaperClaim,
  PaperCitations,
  PaperExcerpt,
  PaperNote,
  ReadingWorkspace,
  RelatedPaper,
  ThesisPaperLink,
  ThesisWorkspace,
  UserCollection,
  UserTag,
} from "../api";
import { BookOpen, Plus, RotateCw, X } from "../icons";
import { useToast } from "../components/ui/Toast";
import { useConfirm } from "../components/ui/ConfirmDialog";
import { Tabs } from "../components/ui/Tabs";
import { Shell } from "../components/layout/Shell";
import { Stat } from "../components/ui/Stat";
import { EmptyState } from "../components/ui/EmptyState";
import { shouldCloseOnEscape, shouldSubmitOnEnter } from "./keyGuardModel";
import { Drawer } from "../components/ui/Drawer";
import PdfReader from "../components/PdfReader";
import { usePaperDraft } from "../components/usePaperDraft";
import { CopyPaperPanel } from '../components/CopyPaperPanel';
import ThesisWorkspacePanel from "../components/ThesisWorkspacePanel";
import {
  buildExcerptPayload,
  buildNotePayload,
  mergeMatrixSuggestion,
  type ExcerptForm,
  type NoteForm,
} from "./readingWorkspaceModel";
import { buildThesisLinkPayload, type ThesisLinkForm } from "./thesisLinkModel";
import {
  buildCollectionPayload,
  buildTagPayload,
  matchesOrganizationFilter,
  type CollectionForm,
  type OrganizationFilter,
  type TagForm,
} from "./organizationModel";
import {
  buildManualPaperPayload,
  emptyManualPaperForm,
  type ManualPaperForm,
} from "./manualPaperModel";
import {
  buildPdfImportQueue,
  firstDonePdfItem,
  markPdfImportItem,
  summarizePdfImport,
  type PdfImportItem,
} from "./pdfBatchModel";
import { aiAnalysisHint, paperAnalysisView } from "./readinessModel";
import {
  libraryDeepLinkFromParams,
  libraryParamsFromState,
  type NavLocation,
} from "./navigationModel";
import {
  SEARCH_DEBOUNCE_MS,
  isServerSearchActive,
  mergeSearchPage,
  normalizeSearchQuery,
  searchScopeNotice,
} from "./librarySearchModel";
import {
  canQueueExternal,
  externalPaperPayload,
  queueSuccessLabel,
} from "./externalPaperModel";
import {
  buildBulkOrganizationPayload,
  replaceBulkPaperSelection,
  toggleBulkPaperSelection,
  type BulkOrganizationTargetType,
} from "./bulkOrganizationModel";

// 摘要字段键是固定的英文标识（由后端结构化），这里只做中文展示。
const SUMMARY_LABELS: Record<string, string> = {
  problem: "问题",
  method: "方法",
  dataset: "数据集",
  results: "结果",
  limitations: "局限",
  freeform: "概要",
};

const READING_STATUS_LABELS: Record<string, string> = {
  all: "全部",
  unread: "未读",
  queued: "待处理",
  reading: "阅读中",
  read: "已读",
  skipped: "跳过",
};

const READING_PRIORITY_LABELS: Record<string, string> = {
  low: "低",
  normal: "普通",
  high: "高优先级",
};

const PDF_IMPORT_STATUS_LABELS: Record<string, string> = {
  queued: "等待",
  importing: "导入中",
  done: "完成",
  failed: "失败",
};

// 论文详情 modal 的 Tab 分组——把原来单页 7 段塞进 7 个 Tab，减轻信息过载。
type DetailTab = "overview" | "reading" | "thesis" | "matrix" | "notes" | "citations" | "related";
const DETAIL_TABS: { key: DetailTab; label: string }[] = [
  { key: "overview", label: "概览" },
  { key: "reading", label: "阅读工作区" },
  { key: "thesis", label: "课题与章节" },
  { key: "matrix", label: "论文对照表" },
  { key: "notes", label: "笔记 & 摘录" },
  { key: "citations", label: "引用" },
  { key: "related", label: "相关研究" },
];

// 论文导入抽屉的入口 Tab。
type ImportTab = "manual" | "bibtex" | "ris" | "arxiv" | "pdf";
const IMPORT_TABS: { key: ImportTab; label: string }[] = [
  { key: "manual", label: "手动" },
  { key: "bibtex", label: "BibTeX" },
  { key: "ris", label: "RIS" },
  { key: "arxiv", label: "ArXiv" },
  { key: "pdf", label: "PDF" },
];

// Library 顶层视图：论文库（列表为主）。研究仪表板（诊断面板集中）已随研究
// 主页上线迁移到一级页面「研究主页」。

const NOTE_KIND_LABELS: Record<string, string> = {
  note: "笔记",
  question: "问题",
  idea: "想法",
  critique: "批注",
  todo: "待办",
};

const THESIS_LINK_ROLE_LABELS: Record<string, string> = {
  background: "背景",
  method: "方法",
  comparison: "对比",
  evidence: "证据",
  limitation: "局限",
  inspiration: "启发",
  related: "相关",
  to_read: "待读",
};

const READING_STATUS = ["all", "unread", "queued", "reading", "read", "skipped"] as const;

// 论文列表增量加载：后端 /papers 支持 limit/offset/total，首次只拉一页，
// 「加载更多」按页追加；筛选条件命中完整性依赖已加载范围（见提示条）。
const PAPER_PAGE_SIZE = 100;
const MATRIX_FIELDS = [
  "problem",
  "method",
  "dataset",
  "metrics",
  "results",
  "limitations",
  "novelty",
  "relation_to_thesis",
  "future_work",
  "notes",
] as const;

type MatrixField = (typeof MATRIX_FIELDS)[number];
type ThesisFilter = "all" | `project:${number}` | `chapter:${number}`;

interface ThesisIndex {
  paperLinks: Map<number, ThesisPaperLink[]>;
  projectLabels: Map<number, string>;
  chapterLabels: Map<number, string>;
  projectOptions: { id: number; label: string }[];
  chapterOptions: { id: number; label: string }[];
  projectSubtreeIds: Map<number, Set<number>>;
  chapterProjectIds: Map<number, number>;
  chapterSubtreeIds: Map<number, Set<number>>;
}

interface MetadataDraft {
  citation_key: string;
  title: string;
  authors: string;
  year: string;
  venue: string;
  doi: string;
  arxiv_id: string;
  abstract: string;
}

const MATRIX_LABELS: Record<MatrixField, string> = {
  problem: "问题",
  method: "方法",
  dataset: "数据集",
  metrics: "指标",
  results: "结果",
  limitations: "局限",
  novelty: "创新点",
  relation_to_thesis: "与论文关系",
  future_work: "未来工作",
  notes: "备注",
};

function buildThesisIndex(workspace: ThesisWorkspace | null): ThesisIndex {
  const paperLinks = new Map<number, ThesisPaperLink[]>();
  const projectLabels = new Map<number, string>();
  const chapterLabels = new Map<number, string>();
  const projectOptions: { id: number; label: string }[] = [];
  const chapterOptions: { id: number; label: string }[] = [];
  const projectSubtreeIds = new Map<number, Set<number>>();
  const chapterProjectIds = new Map<number, number>();
  const chapterSubtreeIds = new Map<number, Set<number>>();

  workspace?.papers.forEach((paper) => {
    paperLinks.set(paper.id, paper.links);
  });

  function walkChapters(projectId: number, chapters: ThesisWorkspace["projects"][number]["chapters"], prefix: string[]) {
    const ids = new Set<number>();
    for (const chapter of chapters) {
      const path = [...prefix, chapter.title];
      const label = path.join(" / ");
      const subtree = new Set<number>([chapter.id]);
      chapterLabels.set(chapter.id, label);
      chapterProjectIds.set(chapter.id, projectId);
      chapterOptions.push({ id: chapter.id, label });
      for (const childId of walkChapters(projectId, chapter.children, path)) {
        subtree.add(childId);
      }
      chapterSubtreeIds.set(chapter.id, subtree);
      for (const id of subtree) ids.add(id);
    }
    return ids;
  }

  function walkProjects(projects: NonNullable<ThesisWorkspace["projects"]>, prefix: string[]) {
    const ids = new Set<number>();
    for (const project of projects) {
      const path = [...prefix, project.name];
      const label = path.join(" / ");
      const subtree = new Set<number>([project.id]);
      projectLabels.set(project.id, label);
      projectOptions.push({ id: project.id, label });
      walkChapters(project.id, project.chapters, path);
      for (const childId of walkProjects(project.children, path)) {
        subtree.add(childId);
      }
      projectSubtreeIds.set(project.id, subtree);
      for (const id of subtree) ids.add(id);
    }
    return ids;
  }

  walkProjects(workspace?.projects ?? [], []);
  return { paperLinks, projectLabels, chapterLabels, projectOptions, chapterOptions, projectSubtreeIds, chapterProjectIds, chapterSubtreeIds };
}

function matchesThesisFilter(paperId: number, filter: ThesisFilter, index: ThesisIndex) {
  if (filter === "all") return true;
  const links = index.paperLinks.get(paperId) ?? [];
  if (links.length === 0) return false;
  const [kind, rawId] = filter.split(":");
  const id = Number(rawId);
  if (kind === "chapter") {
    const chapterIds = index.chapterSubtreeIds.get(id) ?? new Set([id]);
    return links.some((link) => link.chapter_id != null && chapterIds.has(link.chapter_id));
  }
  const projectIds = index.projectSubtreeIds.get(id) ?? new Set([id]);
  return links.some((link) => {
    if (link.project_id != null && projectIds.has(link.project_id)) return true;
    if (link.chapter_id == null) return false;
    const chapterProjectId = index.chapterProjectIds.get(link.chapter_id);
    return chapterProjectId != null && projectIds.has(chapterProjectId);
  });
}

function thesisLinkTarget(link: ThesisPaperLink, index: ThesisIndex) {
  if (link.chapter_id != null) {
    return index.chapterLabels.get(link.chapter_id) ?? `章节 #${link.chapter_id}`;
  }
  if (link.project_id != null) {
    return index.projectLabels.get(link.project_id) ?? `项目 #${link.project_id}`;
  }
  return "未知目标";
}

function metadataDraftFromPaper(paper: Paper): MetadataDraft {
  return {
    citation_key: paper.citation_key ?? "",
    title: paper.title ?? "",
    authors: paper.authors.join("\n"),
    year: paper.year == null ? "" : String(paper.year),
    venue: paper.venue ?? "",
    doi: paper.doi ?? "",
    arxiv_id: paper.arxiv_id ?? "",
    abstract: paper.abstract ?? "",
  };
}

// BibTeX / RIS 文本导入的结果列表：每条成功结果都可以直接打开。
function ImportResultList({
  results,
  onOpen,
}: {
  results: { id: number; title: string | null }[];
  onOpen: (id: number) => void;
}) {
  return (
    <div className="space-y-1 text-xs" aria-live="polite">
      <div className="rounded-lg px-2 py-1" style={{ backgroundColor: "var(--surface-2)" }}>
        导入完成：共 {results.length} 篇。
      </div>
      {results.map((result) => (
        <div
          key={result.id}
          className="flex items-center justify-between gap-2 rounded-lg border px-2 py-1.5"
          style={{ borderColor: "var(--border)", backgroundColor: "var(--surface-2)" }}
        >
          <span className="min-w-0 truncate font-medium">{result.title ?? `论文 #${result.id}`}</span>
          <button onClick={() => onOpen(result.id)} className="btn-ghost shrink-0 py-0.5 text-xs">
            打开
          </button>
        </div>
      ))}
    </div>
  );
}

export default function Library({
  openPaperId,
  onConsumedOpen,
  onNavigate,
  deepParams,
  onDeepParamsChange,
  onAskAboutPaper,
  onDiscussPapers,
}: {
  openPaperId: number | null;
  onConsumedOpen: () => void;
  onNavigate?: (target: NavLocation | string) => void;
  deepParams: Record<string, string>;
  onDeepParamsChange?: (params: Record<string, string>) => void;
  onAskAboutPaper?: (paperId: number, paperTitle: string | null, selectedText?: string) => void;
  onDiscussPapers?: (papers: {id: number; title: string | null}[]) => Promise<void>;
}) {
  const api = useApi();
  const [discussionOpening, setDiscussionOpening] = useState(false);
  const [papers, setPapers] = useState<Paper[]>([]);
  const [papersTotal, setPapersTotal] = useState(0);
  const [papersLoadingMore, setPapersLoadingMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  const confirm = useConfirm();
  const [bibtex, setBibtex] = useState("");
  const [ris, setRis] = useState("");
  const [arxivId, setArxivId] = useState("");
  const [manualDraft, setManualDraft] = useState<ManualPaperForm>(emptyManualPaperForm());
  const [manualError, setManualError] = useState<string | null>(null);
  const [pdfImportQueue, setPdfImportQueue] = useState<PdfImportItem<File>[]>([]);
  // 导入抽屉的结果列表（BibTeX / RIS 文本导入）；每个成功结果可打开。
  const [textImportResults, setTextImportResults] = useState<{ id: number; title: string | null }[]>([]);
  // 模型是否已配置（readiness capabilities.llm）；null = 尚未加载。
  const [llmConfigured, setLlmConfigured] = useState<boolean | null>(null);
  const [selected, setSelected] = useState<Paper | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");
  // P11: 内置 PDF 阅读器覆盖层（全屏），从详情弹窗的「阅读」按钮进入。
  const [readerOpen, setReaderOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importTab, setImportTab] = useState<ImportTab>("manual");
  const [metadataDraft, setMetadataDraft] = useState<MetadataDraft>({
    citation_key: "",
    title: "",
    authors: "",
    year: "",
    venue: "",
    doi: "",
    arxiv_id: "",
    abstract: "",
  });
  const [metadataSaving, setMetadataSaving] = useState(false);
  const [metadataMsg, setMetadataMsg] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<ReadingWorkspace | null>(null);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [workspaceMsg, setWorkspaceMsg] = useState<string | null>(null);
  const [related, setRelated] = useState<RelatedPaper[] | null>(null);
  const [relatedLoading, setRelatedLoading] = useState(false);
  const [relatedError, setRelatedError] = useState<string | null>(null);
  // T10：库外论文加入待读的逐项状态（key → busy / 已加入的论文 id）。
  const [queueingExternal, setQueueingExternal] = useState<Record<string, boolean>>({});
  const [queuedExternalPapers, setQueuedExternalPapers] = useState<Record<string, number>>({});
  const [citations, setCitations] = useState<PaperCitations | null>(null);
  const [citationsLoading, setCitationsLoading] = useState(false);
  // T9：全库搜索。searchInput 是输入框即时值；serverQuery 是防抖后发给后端的值。
  const [query, setQuery] = useState("");
  const [serverQuery, setServerQuery] = useState("");
  const searchSeqRef = useRef(0);
  const searchFirstRunRef = useRef(true);
  const [sort, setSort] = useState<"imported" | "year_desc" | "year_asc" | "title">("imported");
  const [analyzing, setAnalyzing] = useState(false);
  const [view, setView] = useState<"library" | "matrix" | "thesis">("library");
  const [readingStatus, setReadingStatus] = useState<(typeof READING_STATUS)[number]>("all");
  const [highPriorityOnly, setHighPriorityOnly] = useState(false);
  const [minRelevance, setMinRelevance] = useState(0);
  const [thesisFilter, setThesisFilter] = useState<ThesisFilter>("all");
  const [matrixRows, setMatrixRows] = useState<MatrixRow[]>([]);
  const [matrixLoading, setMatrixLoading] = useState(false);
  const [thesisWorkspace, setThesisWorkspace] = useState<ThesisWorkspace | null>(null);
  const [thesisLoading, setThesisLoading] = useState(false);
  const [tags, setTags] = useState<UserTag[]>([]);
  const [collections, setCollections] = useState<UserCollection[]>([]);
  const [organizationFilter, setOrganizationFilter] = useState<OrganizationFilter>("all");
  const [tagForm, setTagForm] = useState<TagForm>({ name: "", color: "" });
  const [collectionForm, setCollectionForm] = useState<CollectionForm>({ name: "", description: "" });
  const [selectedTagId, setSelectedTagId] = useState("");
  const [selectedCollectionId, setSelectedCollectionId] = useState("");
  const [organizationBusy, setOrganizationBusy] = useState(false);
  const [organizationMsg, setOrganizationMsg] = useState<string | null>(null);
  const [bulkSelectedPaperIds, setBulkSelectedPaperIds] = useState<number[]>([]);
  const [bulkTargetType, setBulkTargetType] = useState<BulkOrganizationTargetType>("tag");
  const [bulkTargetId, setBulkTargetId] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkMsg, setBulkMsg] = useState<string | null>(null);
  const [noteDraft, setNoteDraft, clearSavedNote, noteStorageError] = usePaperDraft<NoteForm>(selected?.id, { kind: "note", content: "", tags: "" }, "note");
  const [editingNoteId, setEditingNoteId] = useState<number | null>(null);
  const [noteEditDraft, setNoteEditDraft] = useState<NoteForm>({ kind: "note", content: "", tags: "" });
  const [excerptDraft, setExcerptDraft, clearSavedExcerpt, excerptStorageError] = usePaperDraft<ExcerptForm>(selected?.id, { quote: "", page: "", section: "", locator: "", note: "", tags: "" }, "excerpt");
  const [editingExcerptId, setEditingExcerptId] = useState<number | null>(null);
  const [excerptEditDraft, setExcerptEditDraft] = useState<ExcerptForm>({ quote: "", page: "", section: "", locator: "", note: "", tags: "" });
  const [matrixSuggesting, setMatrixSuggesting] = useState(false);
  // P12 论断：详情弹窗展示 + 手动添加（AI 抽取由设置开关控制）。
  const [claims, setClaims] = useState<PaperClaim[]>([]);
  const [claimDraft, setClaimDraft] = useState("");
  const [detailLinkForm, setDetailLinkForm] = useState<ThesisLinkForm>({
    target_type: "project",
    project_id: "",
    chapter_id: "",
    role: "related",
    note: "",
  });
  const [detailLinkBusy, setDetailLinkBusy] = useState(false);
  const savedMatrix = Object.fromEntries(MATRIX_FIELDS.map(field => [field,
    workspace?.state.paper_id === selected?.id ? (workspace?.matrix?.[field] ?? "") : "",
  ])) as Record<MatrixField, string>;
  const [matrixDraft, setMatrixDraft, clearSavedMatrix, matrixStorageError] = usePaperDraft(selected?.id, savedMatrix, "matrix");
  const thesisIndex = useMemo(() => buildThesisIndex(thesisWorkspace), [thesisWorkspace]);
  // P11.5: 阅读进度节流写回（2s 防抖，关闭阅读器时立即冲刷）。
  const readerProgressTimer = useRef<number | null>(null);
  const readerPendingProgress = useRef<{ paperId: number; page: number } | null>(null);
  const selectedThesisLinks = selected ? thesisIndex.paperLinks.get(selected.id) ?? [] : [];
  const selectedTagIds = useMemo(() => new Set((selected?.tags ?? []).map((tag) => tag.id)), [selected?.tags]);
  const selectedCollectionIds = useMemo(
    () => new Set((selected?.collections ?? []).map((collection) => collection.id)),
    [selected?.collections],
  );
  const bulkSelectedPaperIdSet = useMemo(() => new Set(bulkSelectedPaperIds), [bulkSelectedPaperIds]);
  const availableTags = tags.filter((tag) => !selectedTagIds.has(tag.id));
  const availableCollections = collections.filter((collection) => !selectedCollectionIds.has(collection.id));
  const detailChapterOptions = useMemo(() => {
    const projectId = Number(detailLinkForm.project_id);
    if (!projectId) return [];
    return thesisIndex.chapterOptions.filter((option) => thesisIndex.chapterProjectIds.get(option.id) === projectId);
  }, [detailLinkForm.project_id, thesisIndex]);

  // 拉取前 target 篇论文（受库内 total 约束，单请求上限 500，超出自动续拉）。
  // 每页至少请求 PAPER_PAGE_SIZE 条，所以 target=0 时也会取回完整第一页。
  // T9：q 非空时走服务端全库搜索（total 为过滤后总数）。
  async function fetchPapersUpTo(target: number, q?: string): Promise<Paper[]> {
    const query = q && q.trim() ? q.trim() : undefined;
    let items: Paper[] = [];
    for (;;) {
      const limit = Math.min(Math.max(target - items.length, PAPER_PAGE_SIZE), 500);
      const page = await api.listPapers(limit, items.length, query);
      setPapersTotal(page.total);
      if (page.items.length === 0) return items;
      const seen = new Set(items.map((paper) => paper.id));
      items = [...items, ...page.items.filter((paper) => !seen.has(paper.id))];
      if (items.length >= page.total || items.length >= target) return items;
    }
  }

  async function loadMorePapers(target: number) {
    if (papersLoadingMore) return;
    setPapersLoadingMore(true);
    try {
      if (isServerSearchActive(serverQuery)) {
        // 搜索态：按 offset 追加下一页（全库匹配结果），并按 id 去重。
        const page = await api.listPapers(PAPER_PAGE_SIZE, papers.length, serverQuery);
        setPapers((prev) => mergeSearchPage(prev, page.items, papers.length));
        setPapersTotal(page.total);
      } else {
        setPapers(await fetchPapersUpTo(target));
      }
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setPapersLoadingMore(false);
    }
  }

  async function load() {
    setLoading(true);
    // 与搜索请求共用序号防护：更新（导入/刷新）与搜索并发时，后发起者胜出，
    // 避免慢的 load() 用旧列表覆盖新的搜索结果（反之亦然）。
    const seq = ++searchSeqRef.current;
    try {
      // 刷新时保持当前已加载范围，避免增量视图被截断回第一页。
      const [nextPapers, nextTags, nextCollections, readiness] = await Promise.all([
        fetchPapersUpTo(papers.length, serverQuery),
        api.listTags(),
        api.listCollections(),
        api.readiness().catch(() => null),
      ]);
      if (seq !== searchSeqRef.current) return;
      setPapers(nextPapers);
      setTags(nextTags);
      setCollections(nextCollections);
      if (readiness) setLlmConfigured(readiness.capabilities.llm);
      setError(null);
      await loadThesisWorkspace();
    } catch (e: any) {
      if (seq !== searchSeqRef.current) return;
      // 加载失败必须与"论文库为空"区分开，否则用户会误以为需要重新导入。
      setError(e.message);
    } finally {
      if (seq === searchSeqRef.current) setLoading(false);
    }
  }

  // T9：输入防抖 → serverQuery。
  useEffect(() => {
    const timer = window.setTimeout(
      () => setServerQuery(normalizeSearchQuery(query)),
      SEARCH_DEBOUNCE_MS,
    );
    return () => window.clearTimeout(timer);
  }, [query]);

  // T9：serverQuery 变化 → 服务端全库搜索第一页；seq 防竞态（旧响应直接丢弃）。
  // 首次挂载且无查询时跳过（初始加载由 load() 负责，避免重复请求）。
  useEffect(() => {
    if (searchFirstRunRef.current) {
      searchFirstRunRef.current = false;
      if (!serverQuery) return;
    }
    const seq = ++searchSeqRef.current;
    setLoading(true);
    api
      .listPapers(PAPER_PAGE_SIZE, 0, serverQuery || undefined)
      .then((page) => {
        if (seq !== searchSeqRef.current) return;
        setPapers(page.items);
        setPapersTotal(page.total);
        setError(null);
      })
      .catch((e: any) => {
        if (seq !== searchSeqRef.current) return;
        setError(e.message);
      })
      .finally(() => {
        if (seq === searchSeqRef.current) setLoading(false);
      });
  }, [serverQuery]);

  async function loadReadingWorkspace(id: number) {
    setWorkspaceLoading(true);
    try {
      const next = await api.getReadingWorkspace(id);
      setWorkspace(next);
      setWorkspaceMsg(null);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setWorkspaceLoading(false);
    }
  }

  async function loadMatrix() {
    setMatrixLoading(true);
    try {
      setMatrixRows(
        await api.reviewMatrix({
          status: readingStatus === "all" ? undefined : readingStatus,
          q: serverQuery.trim() || undefined,
          min_relevance: minRelevance || undefined,
          high_priority: highPriorityOnly || undefined,
        }),
      );
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setMatrixLoading(false);
    }
  }

  async function loadThesisWorkspace() {
    setThesisLoading(true);
    try {
      setThesisWorkspace(await api.thesisWorkspace());
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setThesisLoading(false);
    }
  }

  async function refreshOrganization(paperId?: number) {
    const [nextPapers, nextTags, nextCollections, nextSelected] = await Promise.all([
      fetchPapersUpTo(papers.length, serverQuery),
      api.listTags(),
      api.listCollections(),
      paperId ? api.getPaper(paperId) : Promise.resolve(null),
    ]);
    setPapers(nextPapers);
    setTags(nextTags);
    setCollections(nextCollections);
    if (nextSelected) setSelected(nextSelected);
  }

  useEffect(() => {
    load();
  }, []);

  // 打开另一篇论文时回到「概览」Tab——同一篇的数据更新不会触发（id 不变）。
  useEffect(() => {
    setDetailTab("overview");
    setReaderOpen(false);
    setClaimDraft("");
    setEditingNoteId(null);
    setEditingExcerptId(null);
  }, [selected?.id]);

  // P12: 论断随选中论文加载（失败静默为空，不阻塞详情弹窗）。
  useEffect(() => {
    if (!selected) {
      setClaims([]);
      return;
    }
    let alive = true;
    api
      .listPaperClaims(selected.id)
      .then((next) => {
        if (alive) setClaims(next);
      })
      .catch(() => {
        if (alive) setClaims([]);
      });
    return () => {
      alive = false;
    };
  }, [selected?.id]);

  useEffect(() => {
    const activePaperIds = new Set(papers.map((paper) => paper.id));
    setBulkSelectedPaperIds((ids) => ids.filter((id) => activePaperIds.has(id)));
  }, [papers]);

  useEffect(() => {
    if (view === "matrix") loadMatrix();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, readingStatus, highPriorityOnly, minRelevance, serverQuery]);

  useEffect(() => {
    if (view === "thesis") loadThesisWorkspace();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  useEffect(() => {
    if (thesisFilter === "all") return;
    const [kind, rawId] = thesisFilter.split(":");
    const id = Number(rawId);
    if (kind === "project" && !thesisIndex.projectLabels.has(id)) setThesisFilter("all");
    if (kind === "chapter" && !thesisIndex.chapterLabels.has(id)) setThesisFilter("all");
  }, [thesisFilter, thesisIndex]);

  useEffect(() => {
    if (organizationFilter === "all") return;
    const [kind, rawId] = organizationFilter.split(":");
    const id = Number(rawId);
    if (kind === "tag" && !tags.some((tag) => tag.id === id)) setOrganizationFilter("all");
    if (kind === "collection" && !collections.some((collection) => collection.id === id)) {
      setOrganizationFilter("all");
    }
  }, [organizationFilter, tags, collections]);

  // A navigation can change props before local state catches up. Do not publish
  // that old state back to the parent in the same effect pass.
  const applyingLocation = useRef(false);
  useEffect(() => {
    applyingLocation.current = true;
    const link = libraryDeepLinkFromParams(deepParams);
    setView(link.view);
    setImportOpen(link.importOpen);
    setImportTab(link.importTab);
    setReadingStatus(link.readingStatus);
  }, [deepParams]);

  // 内层状态 → 深链参数：视图级变化回写 hash（默认值省略，保持规范 hash 干净）。
  // 与当前参数语义一致时不回推，避免 params ↔ state 来回震荡。
  useEffect(() => {
    if (applyingLocation.current) { applyingLocation.current = false; return; }
    if (!onDeepParamsChange) return;
    const next = libraryParamsFromState({ view, importOpen, importTab, readingStatus });
    if (JSON.stringify(next) !== JSON.stringify(deepParams)) onDeepParamsChange(next);
  }, [view, importOpen, importTab, readingStatus, deepParams, onDeepParamsChange]);

  useEffect(() => {
    if (!selected) return;
    const firstProject = thesisIndex.projectOptions[0]?.id;
    if (!firstProject) return;
    setDetailLinkForm((prev) => ({
      ...prev,
      project_id: prev.project_id || String(firstProject),
      chapter_id:
        prev.chapter_id && thesisIndex.chapterLabels.has(Number(prev.chapter_id))
          ? prev.chapter_id
          : "",
    }));
  }, [selected?.id, thesisIndex]);

  // Close the reader first on Escape, then the detail modal (keyboard parity).
  // 确认弹窗（[role="alertdialog"]，如 ConfirmDialog）在前时，Escape 交给它处理，
  // 不关闭底层的阅读器/详情弹窗。
  useEffect(() => {
    if (!selected) return;
    function onKey(e: KeyboardEvent) {
      const hasOpenAlertDialog = document.querySelector('[role="alertdialog"]') !== null;
      if (!shouldCloseOnEscape(e.key, hasOpenAlertDialog)) return;
      if (readerOpen) return; // Reader owns Escape, including unsaved-draft confirmation.
      else setSelected(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, readerOpen]);

  // Open a specific paper when navigated to from elsewhere (e.g. a Chat source).
  useEffect(() => {
    if (openPaperId == null) return;
    let alive = true;
    Promise.all([api.getPaper(openPaperId), api.getReadingWorkspace(openPaperId)])
      .then(([p, r]) => {
        if (!alive) return;
        setSelected(p);
        setMetadataDraft(metadataDraftFromPaper(p));
        setMetadataMsg(null);
        setOrganizationMsg(null);
        setSelectedTagId("");
        setSelectedCollectionId("");
        setWorkspace(r);
        setRelated(null);
        setRelatedError(null);
      })
      .catch(() => {})
      .finally(onConsumedOpen);
    return () => {
      alive = false;
    };
  }, [openPaperId, onConsumedOpen]);

  async function ingestBibtex() {
    if (!bibtex.trim()) return;
    setLoading(true);
    try {
      const created = await api.ingestBibtex(bibtex);
      if (created.length === 0) throw new Error("未识别到有效 BibTeX，输入已保留，请检查格式。");
      toast.success(`已导入 ${created.length} 条文献。`);
      setBibtex("");
      setTextImportResults(created.map((paper: Paper) => ({ id: paper.id, title: paper.title })));
      await load();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function ingestRis() {
    if (!ris.trim()) return;
    setLoading(true);
    try {
      const created = await api.ingestRis(ris);
      if (created.length === 0) throw new Error("未识别到有效 RIS，输入已保留，请检查格式。");
      toast.success(`已导入 ${created.length} 条文献。`);
      setRis("");
      setTextImportResults(created.map((paper: Paper) => ({ id: paper.id, title: paper.title })));
      await load();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function ingestArxiv() {
    if (!arxivId.trim()) return;
    setLoading(true);
    try {
      const paper = await api.ingestArxiv(arxivId.trim());
      setArxivId("");
      await load();
      // 单篇 ArXiv 导入成功后直接打开论文详情。
      setImportOpen(false);
      await openById(paper.id);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function importPdfFiles(files: FileList | null) {
    const queue = buildPdfImportQueue(Array.from(files ?? []));
    if (queue.length === 0) return;
    setPdfImportQueue(queue);
    setTextImportResults([]);
    setLoading(true);
    let imported = false;
    // 单一数据源：本地维护队列快照，避免在 setState updater 里做副作用。
    let latest = queue;
    try {
      for (const item of queue) {
        if (item.status !== "queued") continue;
        latest = markPdfImportItem(latest, item.id, { status: "importing" });
        setPdfImportQueue(latest);
        try {
          const paper = await api.ingestPdf(item.file);
          imported = true;
          latest = markPdfImportItem(latest, item.id, { status: "done", paperId: paper.id });
          setPdfImportQueue(latest);
        } catch (err: any) {
          latest = markPdfImportItem(latest, item.id, {
            status: "failed",
            error: err?.message ?? "导入失败",
          });
          setPdfImportQueue(latest);
        }
      }
      if (imported) {
        await load();
        // 单篇成功直接打开详情并收起抽屉；批量保留结果列表并默认打开第一篇成功论文。
        const firstDone = firstDonePdfItem(latest);
        if (firstDone?.paperId != null) await openById(firstDone.paperId);
        if (queue.length === 1) setImportOpen(false);
      }
    } finally {
      setLoading(false);
    }
  }

  async function createManualPaper() {
    setManualError(null);
    const payload = buildManualPaperPayload(manualDraft);
    if (!payload) {
      setManualError("手动录入至少需要标题，年份必须是非负整数。");
      return;
    }
    setLoading(true);
    try {
      const created = await api.createManualPaper(payload);
      setManualDraft(emptyManualPaperForm());
      setImportOpen(false);
      toast.success("已添加到论文库。");
      await load();
      await open(created);
    } catch (e: any) {
      setManualError(e.message);
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function openById(paperId: number) {
    const [paper, reading] = await Promise.all([api.getPaper(paperId), api.getReadingWorkspace(paperId)]);
    setSelected(paper);
    setMetadataDraft(metadataDraftFromPaper(paper));
    setMetadataMsg(null);
    setOrganizationMsg(null);
    setSelectedTagId("");
    setSelectedCollectionId("");
    setWorkspace(reading);
    setRelated(null);
  }

  async function open(p: Paper) {
    await openById(p.id);
  }

  async function findRelated(id: number) {
    setRelatedLoading(true);
    setRelatedError(null);
    try {
      setRelated(await api.relatedPapers(id));
    } catch (error: any) {
      setRelated(null);
      setRelatedError(error?.message ?? "发现失败，请检查网络后重试。");
    } finally {
      setRelatedLoading(false);
    }
  }

  // T10：库外论文一键加入待读。key 用于逐项 busy/已加入状态；成功后刷新
  // 引用匹配与论文列表；失败保留外链降级（只 toast，不隐藏条目）。
  async function queueExternalPaper(
    key: string,
    item: {
      title?: string | null;
      doi?: string | null;
      arxiv_id?: string | null;
      year?: number | null;
      venue?: string | null;
      authors?: string[];
    },
    { refreshCitations = false, refreshRelated = false } = {},
  ) {
    if (!selected || queueingExternal[key]) return;
    const payload = externalPaperPayload(item);
    if (!payload) {
      toast.error("元数据不足：该条目没有标题、DOI 或 arXiv ID，请用外部链接自行查找。");
      return;
    }
    setQueueingExternal((prev) => ({ ...prev, [key]: true }));
    try {
      const { paper, created } = await api.addExternalPaper(payload);
      setQueuedExternalPapers((prev) => ({ ...prev, [key]: paper.id }));
      toast.success(queueSuccessLabel(created));
      await load();
      if (refreshCitations) {
        try {
          setCitations(await api.paperCitations(selected.id));
        } catch {
          /* 刷新失败不影响加入结果 */
        }
      }
      if (refreshRelated) await findRelated(selected.id);
    } catch (e: any) {
      toast.error(e?.message ?? "加入待读失败，请稍后重试或使用外部链接。");
    } finally {
      setQueueingExternal((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    }
  }

  // 引用 tab 懒加载：只在切到该 tab 且有选中论文时请求。
  useEffect(() => {
    if (detailTab !== "citations" || !selected) return;
    let alive = true;
    setCitationsLoading(true);
    api
      .paperCitations(selected.id)
      .then((next) => {
        if (alive) setCitations(next);
      })
      .catch((e: any) => {
        if (alive) toast.error(e.message);
      })
      .finally(() => {
        if (alive) setCitationsLoading(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailTab, selected?.id]);

  async function removePaper(p: Paper) {
    const ok = await confirm({
      title: "移除论文？",
      message: `将从论文库移除「${p.title ?? "该论文"}」，此操作不可撤销。`,
      variant: "danger",
      confirmText: "移除",
    });
    if (!ok) return;
    try {
      await api.deletePaper(p.id);
      if (selected?.id === p.id) setSelected(null);
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function reanalyze() {
    if (!selected || analyzing) return;
    setAnalyzing(true);
    try {
      const res = await api.reanalyzePaper(selected.id);
      setSelected({ ...selected, summary: res.summary, concepts: res.concepts });
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setAnalyzing(false);
    }
  }

  async function saveMetadata() {
    if (!selected || metadataSaving) return;
    const yearText = metadataDraft.year.trim();
    let year: number | null = null;
    if (yearText) {
      const parsedYear = Number(yearText);
      if (!Number.isInteger(parsedYear) || parsedYear < 0) {
        setError("年份必须是非负整数。");
        return;
      }
      year = parsedYear;
    }
    setMetadataSaving(true);
    try {
      const updated = await api.patchPaper(selected.id, {
        citation_key: metadataDraft.citation_key.trim() || null,
        title: metadataDraft.title.trim() || null,
        authors: metadataDraft.authors
          .split("\n")
          .map((author) => author.trim())
          .filter(Boolean),
        year,
        venue: metadataDraft.venue.trim() || null,
        doi: metadataDraft.doi.trim() || null,
        arxiv_id: metadataDraft.arxiv_id.trim() || null,
        abstract: metadataDraft.abstract.trim() || null,
      });
      const merged = { ...selected, ...updated };
      setSelected(merged);
      setMetadataDraft(metadataDraftFromPaper(merged));
      setMetadataMsg("元数据已保存。");
      setPapers((prev) => prev.map((paper) => (paper.id === updated.id ? { ...paper, ...updated } : paper)));
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setMetadataSaving(false);
    }
  }

  // P12: 手动添加/删除论断。
  async function addClaim() {
    if (!selected || !claimDraft.trim()) return;
    try {
      const claim = await api.createClaim(selected.id, { text: claimDraft.trim() });
      setClaims((prev) => [...prev, claim]);
      setClaimDraft("");
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function removeClaim(claim: PaperClaim) {
    if (!selected) return;
    try {
      await api.deleteClaim(claim.id);
      setClaims((prev) => prev.filter((item) => item.id !== claim.id));
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  // P11.5: 阅读器翻页 → 节流写回 last_page；关闭阅读器时立即冲刷待写进度。
  function commitReaderProgress(page: number) {
    if (!selected) return;
    readerPendingProgress.current = { paperId: selected.id, page };
    if (readerProgressTimer.current != null) return;
    readerProgressTimer.current = window.setTimeout(() => {
      readerProgressTimer.current = null;
      void flushReaderProgress();
    }, 2000);
  }

  async function flushReaderProgress() {
    const pending = readerPendingProgress.current;
    readerPendingProgress.current = null;
    if (!pending) return;
    try {
      const state = await api.patchReadingState(pending.paperId, { last_page: pending.page });
      setWorkspace((prev) => (prev && prev.state.paper_id === pending.paperId ? { ...prev, state } : prev));
    } catch {
      /* 进度写回失败不打扰阅读 */
    }
  }

  async function closeReader() {
    if (readerProgressTimer.current != null) {
      window.clearTimeout(readerProgressTimer.current);
      readerProgressTimer.current = null;
    }
    await flushReaderProgress();
    setReaderOpen(false);
  }

  // P11.3: 阅读器内划选保存为摘录（quote=选中文本，page=当前页）。
  async function saveReaderExcerpt(quote: string, page: number): Promise<boolean> {
    if (!selected) return false;
    try {
      const excerpt = await api.createExcerpt(selected.id, { quote, page });
      setWorkspace((prev) => (prev?.state.paper_id === selected.id ? { ...prev, excerpts: [...prev.excerpts, excerpt] } : prev));
      return true;
    } catch (e: any) {
      toast.error(e.message);
      return false;
    }
  }

  // T4: 阅读器侧栏就地编辑摘录备注（复用 patchExcerpt，就地刷新工作区）。
  async function saveReaderExcerptNote(excerptId: number, note: string): Promise<boolean> {
    if (!selected) return false;
    try {
      const updated = await api.patchExcerpt(selected.id, excerptId, { note });
      setWorkspace((prev) =>
        prev?.state.paper_id === selected.id
          ? { ...prev, excerpts: prev.excerpts.map((item) => (item.id === excerptId ? updated : item)) }
          : prev,
      );
      return true;
    } catch (e: any) {
      toast.error(e.message);
      return false;
    }
  }

  // T4: 阅读器侧栏新建 PaperNote（复用 createNote，就地刷新工作区）。
  async function createReaderNote(payload: Record<string, unknown>): Promise<boolean> {
    if (!selected) return false;
    try {
      const note = await api.createNote(selected.id, payload);
      setWorkspace((prev) => (prev?.state.paper_id === selected.id ? { ...prev, notes: [...prev.notes, note] } : prev));
      return true;
    } catch (e: any) {
      toast.error(e.message);
      return false;
    }
  }

  async function updateReadingState(body: Record<string, unknown>) {
    if (!selected) return;
    try {
      const state = await api.patchReadingState(selected.id, body);
      setWorkspace((prev) => (prev ? { ...prev, state } : prev));
      setSelected({ ...selected, reading: state });
      setPapers((prev) =>
        prev.map((paper) =>
          paper.id === selected.id
            ? { ...paper, reading: { status: state.status, priority: state.priority, rating: state.rating, relevance: state.relevance } }
            : paper,
        ),
      );
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function saveMatrix() {
    if (!selected) return;
    const paperId = selected.id;
    try {
      const matrix = await api.saveReviewMatrix(paperId, matrixDraft);
      setWorkspace((prev) => (prev?.state.paper_id === paperId ? { ...prev, matrix } : prev));
      clearSavedMatrix(matrixDraft);
      setWorkspaceMsg("论文对照表已保存。");
      if (view === "matrix") await loadMatrix();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function suggestMatrix() {
    if (!selected) return;
    setMatrixSuggesting(true);
    setWorkspaceMsg(null);
    try {
      const suggestion = await api.suggestReviewMatrix(selected.id);
      if (!suggestion.configured) {
        setWorkspaceMsg(suggestion.error ?? "未配置可用的 LLM，请先在设置中配置对话模型。");
        return;
      }
      if (suggestion.error) {
        setWorkspaceMsg(suggestion.error);
        return;
      }
      const merged = mergeMatrixSuggestion(matrixDraft, suggestion.draft, MATRIX_FIELDS);
      setMatrixDraft(merged.draft);
      if (merged.applied > 0) {
        const skippedText = merged.skipped > 0 ? `，${merged.skipped} 个已有字段未覆盖` : "";
        setWorkspaceMsg(`AI 草稿已填入 ${merged.applied} 个空白字段${skippedText}，请核对后保存。`);
      } else if (merged.skipped > 0) {
        setWorkspaceMsg(`AI 草稿返回了 ${merged.skipped} 个已有字段，未覆盖当前内容。`);
      } else {
        setWorkspaceMsg("AI 暂未生成可用字段，请确认论文已有摘要或全文。");
      }
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setMatrixSuggesting(false);
    }
  }

  async function addNote() {
    if (!selected || !noteDraft.content.trim()) return;
    const payload = buildNotePayload(noteDraft);
    if (!payload) {
      setError("笔记内容不能为空。");
      return;
    }
    try {
      const note = await api.createNote(selected.id, payload);
      setWorkspace((prev) => (prev?.state.paper_id === selected.id ? { ...prev, notes: [note, ...prev.notes] } : prev));
      clearSavedNote(noteDraft);
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  function beginEditNote(note: PaperNote) {
    setEditingNoteId(note.id);
    setNoteEditDraft({
      kind: note.kind,
      content: note.content,
      tags: note.tags.join(", "),
    });
  }

  async function saveNoteEdit(note: PaperNote) {
    if (!selected) return;
    const payload = buildNotePayload(noteEditDraft);
    if (!payload) {
      setError("笔记内容不能为空。");
      return;
    }
    try {
      const updated = await api.patchNote(selected.id, note.id, payload);
      setWorkspace((prev) =>
        prev
          ? {
              ...prev,
              notes: prev.notes.map((item) => (item.id === updated.id ? updated : item)),
            }
          : prev,
      );
      setEditingNoteId(null);
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function removeNote(note: PaperNote) {
    if (!selected) return;
    try {
      await api.deleteNote(selected.id, note.id);
      setWorkspace((prev) => (prev ? { ...prev, notes: prev.notes.filter((item) => item.id !== note.id) } : prev));
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function addExcerpt() {
    if (!selected || !excerptDraft.quote.trim()) return;
    const payload = buildExcerptPayload(excerptDraft);
    if (!payload) {
      setError("摘录原文不能为空，页码必须是正整数。");
      return;
    }
    try {
      const excerpt = await api.createExcerpt(selected.id, payload);
      setWorkspace((prev) => (prev?.state.paper_id === selected.id ? { ...prev, excerpts: [...prev.excerpts, excerpt] } : prev));
      clearSavedExcerpt(excerptDraft);
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  function beginEditExcerpt(excerpt: PaperExcerpt) {
    setEditingExcerptId(excerpt.id);
    setExcerptEditDraft({
      quote: excerpt.quote,
      page: excerpt.page == null ? "" : String(excerpt.page),
      section: excerpt.section ?? "",
      locator: excerpt.locator ?? "",
      note: excerpt.note ?? "",
      tags: excerpt.tags.join(", "),
    });
  }

  async function saveExcerptEdit(excerpt: PaperExcerpt) {
    if (!selected) return;
    const payload = buildExcerptPayload(excerptEditDraft);
    if (!payload) {
      setError("摘录原文不能为空，页码必须是正整数。");
      return;
    }
    try {
      const updated = await api.patchExcerpt(selected.id, excerpt.id, payload);
      setWorkspace((prev) =>
        prev
          ? {
              ...prev,
              excerpts: prev.excerpts.map((item) => (item.id === updated.id ? updated : item)),
            }
          : prev,
      );
      setEditingExcerptId(null);
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function removeExcerpt(excerpt: PaperExcerpt) {
    if (!selected) return;
    try {
      await api.deleteExcerpt(selected.id, excerpt.id);
      setWorkspace((prev) => (prev ? { ...prev, excerpts: prev.excerpts.filter((item) => item.id !== excerpt.id) } : prev));
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function addSelectedThesisLink() {
    if (!selected || detailLinkBusy) return;
    const payload = buildThesisLinkPayload(detailLinkForm);
    if (!payload) {
      setError("请选择要关联的项目或章节。");
      return;
    }
    setDetailLinkBusy(true);
    try {
      await api.linkThesisPaper(selected.id, payload);
      setDetailLinkForm((prev) => ({ ...prev, note: "" }));
      await loadThesisWorkspace();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setDetailLinkBusy(false);
    }
  }

  async function removeSelectedThesisLink(link: ThesisPaperLink) {
    if (!selected || detailLinkBusy) return;
    const ok = await confirm({
      title: "删除链接？",
      message: "将删除这条课题与章节链接，此操作不可撤销。",
      variant: "danger",
      confirmText: "删除",
    });
    if (!ok) return;
    setDetailLinkBusy(true);
    try {
      await api.deleteThesisLink(selected.id, link.id);
      await loadThesisWorkspace();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setDetailLinkBusy(false);
    }
  }

  async function createAndAttachTag() {
    if (!selected || organizationBusy) return;
    const payload = buildTagPayload(tagForm);
    if (!payload) {
      setError("标签名称不能为空。");
      return;
    }
    setOrganizationBusy(true);
    try {
      const tag = await api.createTag(payload);
      await api.attachTag(selected.id, tag.id);
      setTagForm({ name: "", color: "" });
      setOrganizationMsg("标签已添加。");
      await refreshOrganization(selected.id);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setOrganizationBusy(false);
    }
  }

  async function attachExistingTag() {
    if (!selected || organizationBusy || !selectedTagId) return;
    setOrganizationBusy(true);
    try {
      await api.attachTag(selected.id, Number(selectedTagId));
      setSelectedTagId("");
      setOrganizationMsg("标签已添加。");
      await refreshOrganization(selected.id);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setOrganizationBusy(false);
    }
  }

  async function removeSelectedTag(tagId: number) {
    if (!selected || organizationBusy) return;
    setOrganizationBusy(true);
    try {
      await api.removeTag(selected.id, tagId);
      setOrganizationMsg("标签已移除。");
      await refreshOrganization(selected.id);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setOrganizationBusy(false);
    }
  }

  async function createAndAddCollection() {
    if (!selected || organizationBusy) return;
    const payload = buildCollectionPayload(collectionForm);
    if (!payload) {
      setError("合集名称不能为空。");
      return;
    }
    setOrganizationBusy(true);
    try {
      const collection = await api.createCollection(payload);
      await api.addPaperToCollection(collection.id, selected.id);
      setCollectionForm({ name: "", description: "" });
      setOrganizationMsg("合集已添加。");
      await refreshOrganization(selected.id);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setOrganizationBusy(false);
    }
  }

  async function addExistingCollection() {
    if (!selected || organizationBusy || !selectedCollectionId) return;
    setOrganizationBusy(true);
    try {
      await api.addPaperToCollection(Number(selectedCollectionId), selected.id);
      setSelectedCollectionId("");
      setOrganizationMsg("合集已添加。");
      await refreshOrganization(selected.id);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setOrganizationBusy(false);
    }
  }

  async function removeSelectedCollection(collectionId: number) {
    if (!selected || organizationBusy) return;
    setOrganizationBusy(true);
    try {
      await api.removePaperFromCollection(collectionId, selected.id);
      setOrganizationMsg("合集已移除。");
      await refreshOrganization(selected.id);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setOrganizationBusy(false);
    }
  }

  async function applyBulkOrganization() {
    if (bulkBusy) return;
    const payload = buildBulkOrganizationPayload(bulkSelectedPaperIds, bulkTargetId);
    if (!payload) {
      setError("请先勾选论文，并选择要应用的标签或合集。");
      return;
    }

    setBulkBusy(true);
    setBulkMsg(null);
    setError(null);
    const failedPaperIds: number[] = [];
    let succeeded = 0;
    try {
      for (const paperId of payload.paperIds) {
        try {
          if (bulkTargetType === "tag") {
            await api.attachTag(paperId, payload.targetId);
          } else {
            await api.addPaperToCollection(payload.targetId, paperId);
          }
          succeeded += 1;
        } catch {
          failedPaperIds.push(paperId);
        }
      }
      if (succeeded > 0) await refreshOrganization(selected?.id);
      setBulkSelectedPaperIds(failedPaperIds);
      if (failedPaperIds.length === 0) setBulkTargetId("");
      const targetName = bulkTargetType === "tag" ? "标签" : "合集";
      setBulkMsg(
        failedPaperIds.length > 0 && succeeded === 0
          ? `${failedPaperIds.length} 篇论文应用${targetName}失败，已保留勾选。`
          : failedPaperIds.length > 0
          ? `已为 ${succeeded} 篇论文应用${targetName}，${failedPaperIds.length} 篇失败，失败项已保留勾选。`
          : `已为 ${succeeded} 篇论文应用${targetName}。`,
      );
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setBulkBusy(false);
    }
  }

  // T9：文本搜索已交给服务端（全库匹配）；这里的客户端筛选只保留阅读状态/
  // 优先级/相关度/写作链接/组织等复杂条件，且只作用于已加载范围（见提示条）。
  const serverSearchActive = isServerSearchActive(serverQuery);
  const visible = papers
    .filter((p) => {
      const q = serverSearchActive ? "" : query.trim().toLowerCase();
      if (readingStatus !== "all" && (p.reading?.status ?? "unread") !== readingStatus) return false;
      if (highPriorityOnly && p.reading?.priority !== "high") return false;
      if (minRelevance > 0 && (p.reading?.relevance ?? 0) < minRelevance) return false;
      if (!matchesThesisFilter(p.id, thesisFilter, thesisIndex)) return false;
      if (!matchesOrganizationFilter(p, organizationFilter)) return false;
      if (!q) return true;
      const hay = [
        p.citation_key ?? "",
        p.title ?? "",
        p.authors.join(" "),
        p.venue ?? "",
        p.doi ?? "",
        p.arxiv_id ?? "",
        (p.concepts ?? []).map((c) => c.name).join(" "),
        (p.tags ?? []).map((tag) => tag.name).join(" "),
        (p.collections ?? []).map((collection) => collection.name).join(" "),
        p.abstract ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    })
    .sort((a, b) => {
      if (sort === "imported") return b.id - a.id;
      if (sort === "title") return (a.title ?? "").localeCompare(b.title ?? "");
      const dy = (b.year ?? 0) - (a.year ?? 0);
      return sort === "year_asc" ? -dy : dy;
    });

  // 增量加载下，客户端筛选只作用于已加载的论文；有筛选时提醒用户结果可能不完整。
  const papersIncomplete = papers.length < papersTotal;
  const hasActiveFilter =
    readingStatus !== "all" ||
    highPriorityOnly ||
    minRelevance > 0 ||
    thesisFilter !== "all" ||
    organizationFilter !== "all";
  const searchNotice = searchScopeNotice({
    serverActive: serverSearchActive,
    loaded: papers.length,
    total: papersTotal,
  });

  return (
    <Shell max="wide"><div className="mb-6"><h1 className="page-title">论文库</h1><p className="page-subtitle mt-2">导入论文后，点击标题开始阅读。需要比较方法时用论文对照表，开始写作时再组织课题与章节。</p></div>
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label={serverSearchActive ? "搜索匹配数" : "论文总数"} value={papersTotal} />
            <Stat
              label={papersIncomplete ? `已总结（已加载 ${papers.length}/${papersTotal}）` : "已总结"}
              value={papers.filter((p) => p.has_summary).length}
              accent="var(--accent)"
            />
            <Stat
              label={papersIncomplete ? `待读（已加载 ${papers.length}/${papersTotal}）` : "待读"}
              value={papers.filter((p) =>
                ["unread", "queued"].includes(p.reading?.status ?? "unread"),
              ).length}
            />
            <Stat
              label={papersIncomplete ? `高优先级（已加载 ${papers.length}/${papersTotal}）` : "高优先级"}
              value={papers.filter((p) => p.reading?.priority === "high").length}
              accent="var(--warning)"
            />
          </div>

      {/* 导入入口已移至底部「导入」抽屉（Drawer），见 Shell 末尾 */}

      {error && (
        <div
          className="mb-4 rounded-lg px-3 py-2 text-sm"
          style={{ backgroundColor: "color-mix(in srgb, var(--danger) 12%, transparent)", color: "var(--danger)" }}
        >
          {error}
        </div>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-2">
          <div className="flex rounded-lg border p-1 border-[var(--border)]">
            <button
              className={view === "library" ? "btn-primary py-1 text-xs" : "btn-ghost py-1 text-xs"}
              onClick={() => setView("library")}
            >
              论文库
            </button>
            <button
              className={view === "matrix" ? "btn-primary py-1 text-xs" : "btn-ghost py-1 text-xs"}
              onClick={() => setView("matrix")}
            >
              论文对照表
            </button>
            <button
              className={view === "thesis" ? "btn-primary py-1 text-xs" : "btn-ghost py-1 text-xs"}
              onClick={() => setView("thesis")}
            >
              课题与章节
            </button>
          </div>
          {view !== "thesis" && (
            <>
          <input
            className="input max-w-xs"
            placeholder="搜索全库：标题、作者、DOI、摘要、概念、标签…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="搜索论文库"
          />
          {!serverSearchActive && sort === "imported" && (
            <span className="chip text-muted" title="未搜索时按导入时间倒序展示">
              最近导入
            </span>
          )}
          {serverSearchActive && (
            <button
              className="btn-ghost py-1 text-xs"
              onClick={() => { setQuery(""); setSort("imported"); }}
              title="清空搜索，恢复最近导入列表"
            >
              清空搜索
            </button>
          )}
          <select
            className="input max-w-[10rem]"
            value={sort}
            onChange={(e) => setSort(e.target.value as typeof sort)}
          >
            <option value="imported">最近导入</option>
            <option value="year_desc">发表年份从新到旧</option>
            <option value="year_asc">发表年份从旧到新</option>
            <option value="title">按标题字母序</option>
          </select>
          <select
            className="input max-w-[9rem]"
            value={readingStatus}
            onChange={(e) => setReadingStatus(e.target.value as typeof readingStatus)}
          >
            {READING_STATUS.map((status) => (
              <option key={status} value={status}>
                {READING_STATUS_LABELS[status] ?? status}
              </option>
            ))}
          </select>
          <select
            className="input max-w-[9rem]"
            value={minRelevance}
            onChange={(e) => setMinRelevance(Number(e.target.value))}
          >
            <option value={0}>不限相关度</option>
            {[1, 2, 3, 4, 5].map((score) => (
              <option key={score} value={score}>
                相关度 {score}+
              </option>
            ))}
          </select>
          {view === "library" && (
            <select
              className="input max-w-[14rem]"
              value={thesisFilter}
              onChange={(e) => setThesisFilter(e.target.value as ThesisFilter)}
            >
              <option value="all">全部课题与章节目标</option>
              {thesisIndex.projectOptions.length > 0 && (
                <optgroup label="项目">
                  {thesisIndex.projectOptions.map((option) => (
                    <option key={option.id} value={`project:${option.id}`}>
                      {option.label}
                    </option>
                  ))}
                </optgroup>
              )}
              {thesisIndex.chapterOptions.length > 0 && (
                <optgroup label="章节">
                  {thesisIndex.chapterOptions.map((option) => (
                    <option key={option.id} value={`chapter:${option.id}`}>
                      {option.label}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          )}
          {view === "library" && (
            <select
              className="input max-w-[12rem]"
              value={organizationFilter}
              onChange={(e) => setOrganizationFilter(e.target.value as OrganizationFilter)}
            >
              <option value="all">全部标签/合集</option>
              {tags.length > 0 && (
                <optgroup label="标签">
                  {tags.map((tag) => (
                    <option key={tag.id} value={`tag:${tag.id}`}>
                      {tag.name}（{tag.paper_count}）
                    </option>
                  ))}
                </optgroup>
              )}
              {collections.length > 0 && (
                <optgroup label="合集">
                  {collections.map((collection) => (
                    <option key={collection.id} value={`collection:${collection.id}`}>
                      {collection.name}（{collection.paper_count}）
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          )}
          <label className="flex items-center gap-1 text-xs text-muted">
            <input
              type="checkbox"
              checked={highPriorityOnly}
              onChange={(e) => setHighPriorityOnly(e.target.checked)}
            />
            高优先级
          </label>
          {visible.length > 0 && (
            <button
              onClick={() => {
                setBulkSelectedPaperIds(replaceBulkPaperSelection(visible.map((paper) => paper.id)));
                setBulkMsg(null);
              }}
              className="btn-ghost min-h-9 py-1 text-xs"
            >
              选择当前结果
            </button>
          )}
          {bulkSelectedPaperIds.length > 0 && (
            <button
              onClick={() => {
                setBulkSelectedPaperIds([]);
                setBulkMsg(null);
              }}
              className="btn-ghost min-h-9 py-1 text-xs"
            >
              清空选择
            </button>
          )}
              {view === "matrix" && (
            <button onClick={loadMatrix} disabled={matrixLoading} className="btn-ghost py-1 text-xs">
              {matrixLoading ? "加载中…" : "刷新矩阵"}
            </button>
          )}
          <span className="text-xs text-faint">
            {visible.length} / {papersTotal}
          </span>
          <button
            onClick={() => setImportOpen(true)}
            className="btn-primary ml-auto py-1 text-xs"
          >
            <Plus size={13} /> 导入
          </button>
            </>
          )}
          {view === "thesis" && (
            <button onClick={loadThesisWorkspace} disabled={thesisLoading} className="btn-ghost py-1 text-xs">
              {thesisLoading ? "加载中…" : "刷新规划"}
            </button>
          )}
      </div>

      {view === "matrix" && (
        <section className="card mb-4 overflow-x-auto">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="font-semibold">论文对照表</h3>
            <span className="text-xs text-faint">
              {matrixRows.length} 行
            </span>
          </div>
          {matrixRows.length === 0 && !matrixLoading && (
            <p className="text-sm text-muted">
              当前筛选下没有匹配的矩阵记录。
            </p>
          )}
          {matrixRows.length > 0 && (
            <table className="w-full min-w-[980px] text-left text-xs text-muted">
              <thead >
                <tr>
                  <th className="py-2 pr-3">论文</th>
                  <th className="py-2 pr-3">状态</th>
                  <th className="py-2 pr-3">相关度</th>
                  <th className="py-2 pr-3">问题</th>
                  <th className="py-2 pr-3">方法</th>
                  <th className="py-2 pr-3">结果</th>
                  <th className="py-2 pr-3">局限</th>
                  <th className="py-2 pr-3">课题与章节</th>
                </tr>
              </thead>
              <tbody>
                {matrixRows.map((row) => (
                  <tr key={row.paper.id} className="border-t border-[var(--border)]">
                    <td className="max-w-[14rem] py-2 pr-3 font-medium">{row.paper.title ?? "无标题"}</td>
                    <td className="py-2 pr-3">{READING_STATUS_LABELS[row.state.status] ?? row.state.status}</td>
                    <td className="py-2 pr-3">{row.state.relevance ?? "-"}</td>
                    <td className="max-w-[12rem] py-2 pr-3">{row.matrix?.problem ?? ""}</td>
                    <td className="max-w-[12rem] py-2 pr-3">{row.matrix?.method ?? ""}</td>
                    <td className="max-w-[12rem] py-2 pr-3">{row.matrix?.results ?? ""}</td>
                    <td className="max-w-[12rem] py-2 pr-3">{row.matrix?.limitations ?? ""}</td>
                    <td className="max-w-[12rem] py-2 pr-3">{row.matrix?.relation_to_thesis ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {view === "thesis" && (
        <ThesisWorkspacePanel
          papers={papers}
          workspace={thesisWorkspace}
          loading={thesisLoading}
          onRefresh={loadThesisWorkspace}
          onOpenPaper={async (paperId) => {
            const [paper, reading] = await Promise.all([api.getPaper(paperId), api.getReadingWorkspace(paperId)]);
            setSelected(paper);
            setMetadataDraft(metadataDraftFromPaper(paper));
            setMetadataMsg(null);
            setOrganizationMsg(null);
            setSelectedTagId("");
            setSelectedCollectionId("");
            setWorkspace(reading);
            setRelated(null);
          }}
        />
      )}

      {view !== "thesis" && (
        <div className="space-y-2">
        {searchNotice && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-muted" role="status">
            <span>{searchNotice}</span>
            <button
              onClick={() => loadMorePapers(papers.length + PAPER_PAGE_SIZE)}
              disabled={papersLoadingMore}
              className="btn-ghost py-1 text-xs"
            >
              {papersLoadingMore ? "加载中…" : "加载更多"}
            </button>
          </div>
        )}
        {papersIncomplete && hasActiveFilter && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-muted">
            <span>筛选仅覆盖已加载 {papers.length} / 共 {papersTotal} 篇论文，结果可能不完整。</span>
            <button
              onClick={() => loadMorePapers(Number.MAX_SAFE_INTEGER)}
              disabled={papersLoadingMore}
              className="btn-ghost py-1 text-xs"
            >
              {papersLoadingMore ? "加载中…" : "加载全部"}
            </button>
          </div>
        )}
        {bulkSelectedPaperIds.length > 0 && (
          <div
            className="rounded-lg border px-3 py-2 border-[var(--border)] bg-[var(--surface-2)]"
            
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">已选 {bulkSelectedPaperIds.length} 篇论文</span>
              <button className="btn-primary min-h-9 py-1 text-xs" disabled={discussionOpening || bulkSelectedPaperIds.length > 100} onClick={async () => {
                setDiscussionOpening(true);
                try { await onDiscussPapers?.(bulkSelectedPaperIds.map(id => ({id, title: papers.find(p => p.id === id)?.title ?? null}))); }
                finally { setDiscussionOpening(false); }
              }}>{discussionOpening ? '正在打开讨论…' : bulkSelectedPaperIds.length > 100 ? '基于所选论文讨论（最多 100 篇）' : '基于所选论文讨论'}</button>
              <button className="btn-primary min-h-9 py-1 text-xs" disabled={bulkSelectedPaperIds.length>5} onClick={()=>onNavigate?.({page:'research',params:{papers:bulkSelectedPaperIds.join(',')}})}>围绕问题比较{bulkSelectedPaperIds.length>5?'（最多 5 篇）':''}</button>
              <select
                className="input min-h-9 w-28 py-1 text-xs"
                value={bulkTargetType}
                onChange={(e) => {
                  setBulkTargetType(e.target.value as BulkOrganizationTargetType);
                  setBulkTargetId("");
                  setBulkMsg(null);
                }}
              >
                <option value="tag">添加标签</option>
                <option value="collection">加入合集</option>
              </select>
              <select
                className="input min-h-9 min-w-[12rem] max-w-[18rem] py-1 text-xs"
                value={bulkTargetId}
                onChange={(e) => setBulkTargetId(e.target.value)}
              >
                <option value="">{bulkTargetType === "tag" ? "选择标签" : "选择合集"}</option>
                {bulkTargetType === "tag"
                  ? tags.map((tag) => (
                      <option key={tag.id} value={tag.id}>
                        {tag.name}
                      </option>
                    ))
                  : collections.map((collection) => (
                      <option key={collection.id} value={collection.id}>
                        {collection.name}
                      </option>
                    ))}
              </select>
              <button
                onClick={applyBulkOrganization}
                disabled={bulkBusy || !bulkTargetId}
                className="btn-primary min-h-9 py-1 text-xs"
              >
                {bulkBusy ? "处理中…" : "批量应用"}
              </button>
              <button
                onClick={() => {
                  setBulkSelectedPaperIds([]);
                  setBulkMsg(null);
                }}
                disabled={bulkBusy}
                className="btn-ghost min-h-9 py-1 text-xs"
              >
                取消选择
              </button>
            </div>
            <div className="mt-1 text-xs text-faint" aria-live="polite">
              {bulkMsg ??
                (bulkTargetType === "tag"
                  ? tags.length === 0
                    ? "还没有标签，先在论文详情里创建标签。"
                    : "会把所选论文加入同一个标签。"
                  : collections.length === 0
                    ? "还没有合集，先在论文详情里创建合集。"
                    : "会把所选论文加入同一个合集。")}
            </div>
          </div>
        )}
        {papers.length === 0 && !loading && !error && !serverSearchActive && (
          <EmptyState
            icon={<BookOpen size={20} />}
            title="论文库还是空的"
            hint="先导入手头的一篇 PDF，马上就能阅读和记笔记。需要 AI 摘要时再配置模型。"
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <button
                  onClick={() => {
                    setImportTab("pdf");
                    setImportOpen(true);
                  }}
                  className="btn-primary"
                >
                  <Plus size={14} /> 直接导入
                </button>
              </div>
            }
          />
        )}
        {papers.length === 0 && !loading && error && (
          <div className="card text-center">
            <p className="text-sm text-[var(--danger)]">论文列表加载失败：{error}</p>
            <p className="mt-1 text-xs text-faint">这不是"论文库为空"——请检查后端服务后重试。</p>
            <button onClick={() => load()} className="btn-ghost mt-2 py-1 text-xs">
              重试
            </button>
          </div>
        )}
        {visible.length === 0 && !loading && !error && (papers.length > 0 || serverSearchActive) && (
          <div className="card text-center text-muted">
            {serverSearchActive ? `没有匹配“${serverQuery}”的论文。` : "当前筛选下没有论文。"}
            {serverSearchActive && <button className="btn-ghost mt-2" onClick={() => { setQuery(""); setServerQuery(""); }}>清除搜索</button>}
          </div>
        )}
        {visible.map((p) => (
          <div
            key={p.id}
            className="card-tight group flex items-center gap-2 transition hover:translate-y-[-1px]"
            style={{ boxShadow: "var(--shadow)" }}
          >
            <label
              className="flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-lg border transition"
              style={{
                borderColor: bulkSelectedPaperIdSet.has(p.id) ? "var(--accent)" : "var(--border)",
                backgroundColor: bulkSelectedPaperIdSet.has(p.id)
                  ? "color-mix(in srgb, var(--accent) 10%, transparent)"
                  : "transparent",
              }}
              title="选择论文"
            >
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={bulkSelectedPaperIdSet.has(p.id)}
                onChange={() => {
                  setBulkSelectedPaperIds((ids) => toggleBulkPaperSelection(ids, p.id));
                  setBulkMsg(null);
                }}
                aria-label={`选择论文：${p.title ?? "无标题"}`}
              />
            </label>
            <button onClick={() => open(p)} className="block min-w-0 flex-1 text-left">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 break-words font-medium leading-snug">{p.title ?? "（无标题）"}</div>
                <div className="flex shrink-0 flex-wrap gap-1 sm:max-w-[45%] sm:justify-end">
                  {p.has_summary && <span className="chip">已总结</span>}
                  <span className="chip">{READING_STATUS_LABELS[p.reading?.status ?? "unread"] ?? "未读"}</span>
                  {p.reading?.priority && (
                    <span className="chip">{READING_PRIORITY_LABELS[p.reading.priority] ?? p.reading.priority}</span>
                  )}
                  {p.reading?.relevance && <span className="chip">相关度 {p.reading.relevance}</span>}
                  {(p.tags ?? []).slice(0, 2).map((tag) => (
                    <span key={`tag-${tag.id}`} className="chip">
                      {tag.name}
                    </span>
                  ))}
                  {(p.collections ?? []).slice(0, 1).map((collection) => (
                    <span key={`collection-${collection.id}`} className="chip">
                      {collection.name}
                    </span>
                  ))}
                </div>
              </div>
              <div className="mt-1 text-sm text-muted">
                {p.authors.slice(0, 3).join("，")}
                {p.authors.length > 3 ? " 等" : ""} {p.year ? `· ${p.year}` : ""}
              </div>
            </button>
            <button
              onClick={() => removePaper(p)}
              className="shrink-0 rounded-lg px-2 py-1 text-xs opacity-0 transition-opacity group-hover:opacity-100 text-faint"
              
              title="从库中移除"
              aria-label={`从库中移除${p.title ?? "该论文"}`}
            >
              <X size={14} />
            </button>
          </div>
        ))}
        {papersIncomplete && (
          <button
            onClick={() => loadMorePapers(papers.length + PAPER_PAGE_SIZE)}
            disabled={papersLoadingMore}
            className="btn-ghost w-full py-2 text-sm"
          >
            {papersLoadingMore
              ? "加载中…"
              : `加载更多（已加载 ${papers.length} / 共 ${papersTotal} 篇）`}
          </button>
        )}
        </div>
      )}

      {selected && (
        <div
          className="fixed inset-0 flex items-center justify-center p-6 modal-overlay"
          onClick={() => setSelected(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label={selected.title ?? "论文详情"}
            className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl"
            style={{ backgroundColor: "var(--surface)", boxShadow: "var(--shadow-md)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="shrink-0 border-b border-[var(--border)] p-6 pb-4">
              <div className="mb-2 flex items-start justify-between gap-4">
                <h3 className="text-xl font-bold leading-snug">{selected.title ?? "（无标题）"}</h3>
                <div className="flex shrink-0 items-center gap-2">
                  {selected.has_pdf && (
                    <button onClick={() => setReaderOpen(true)} className="btn-primary px-2.5 py-1.5 text-xs">
                      阅读
                    </button>
                  )}
                  <button
                    onClick={() => onAskAboutPaper?.(selected.id, selected.title)}
                    className="btn-ghost px-2.5 py-1.5 text-xs"
                    title="带上这篇论文的摘要、论文对照表、你的笔记与摘录去对话"
                  >
                    就这篇论文提问
                  </button>
                  <span className="text-xs text-muted" role="status">{noteStorageError || excerptStorageError || matrixStorageError ? "本机草稿存储不可用，请保存后再关闭窗口。" : "新笔记、摘录和对照表草稿会保留在本机，提交后才计入成果。"}</span>
                  <button onClick={() => setSelected(null)} className="btn-subtle px-2" aria-label="关闭">
                    <X size={18} />
                  </button>
                </div>
              </div>
              <p className="mb-3 text-sm text-muted">
                {selected.authors.join(", ")} {selected.year ? `· ${selected.year}` : ""}
              </p>
              {selected.abstract && <p className="mb-3 text-sm leading-relaxed">{selected.abstract}</p>}
              {selected.concepts && selected.concepts.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {selected.concepts.map((c, i) => (
                    <span key={i} className="chip">
                      {c.name}
                    </span>
                  ))}
                </div>
              )}
              {selected.parse_confidence != null && selected.parse_confidence < 0.3 && (
                <div className="alert-danger mt-3">
                  提取到的文字较少，可能是篇幅较短、图表较多或扫描版 PDF。请核对原文，确认可供 AI 分析和全文检索的资料是否完整。
                </div>
              )}
            </div>
            <div className="shrink-0 px-6">
              <Tabs tabs={DETAIL_TABS} value={detailTab} onChange={(t) => setDetailTab(t as DetailTab)} />
            </div>
            <div className="flex-1 overflow-y-auto p-6 pt-4">
            {detailTab === "overview" && (
              <>
            {selected.copied_from&&<p className="text-sm text-muted mb-3">复制自“{selected.copied_from.source_name}”的论文 #{selected.copied_from.source_paper_id}。{selected.copied_from.include_notes?'同时携带了当时的笔记与摘录。':''}</p>}
            <CopyPaperPanel key={selected.id} paper={selected}/>
            <section className="mb-5 rounded-lg border p-3 border-[var(--border)]">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h4 className="font-semibold">引文与元数据</h4>
                <button onClick={saveMetadata} disabled={metadataSaving} className="btn-ghost py-1 text-xs">
                  {metadataSaving ? "保存中…" : "保存元数据"}
                </button>
              </div>
              {metadataMsg && (
                <p className="mb-2 text-xs text-[var(--success)]">
                  {metadataMsg}
                </p>
              )}
              <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                <input
                  className="input py-1 text-xs"
                  placeholder="引文键"
                  value={metadataDraft.citation_key}
                  onChange={(e) => setMetadataDraft({ ...metadataDraft, citation_key: e.target.value })}
                />
                <input
                  className="input py-1 text-xs"
                  placeholder="年份"
                  value={metadataDraft.year}
                  onChange={(e) => setMetadataDraft({ ...metadataDraft, year: e.target.value })}
                />
                <input
                  className="input py-1 text-xs md:col-span-2"
                  placeholder="标题"
                  value={metadataDraft.title}
                  onChange={(e) => setMetadataDraft({ ...metadataDraft, title: e.target.value })}
                />
                <textarea
                  className="input min-h-20 resize-y text-xs md:col-span-2"
                  placeholder="作者"
                  value={metadataDraft.authors}
                  onChange={(e) => setMetadataDraft({ ...metadataDraft, authors: e.target.value })}
                />
                <input
                  className="input py-1 text-xs"
                  placeholder="发表来源"
                  value={metadataDraft.venue}
                  onChange={(e) => setMetadataDraft({ ...metadataDraft, venue: e.target.value })}
                />
                <input
                  className="input py-1 text-xs"
                  placeholder="DOI"
                  value={metadataDraft.doi}
                  onChange={(e) => setMetadataDraft({ ...metadataDraft, doi: e.target.value })}
                />
                <input
                  className="input py-1 text-xs"
                  placeholder="arXiv 编号"
                  value={metadataDraft.arxiv_id}
                  onChange={(e) => setMetadataDraft({ ...metadataDraft, arxiv_id: e.target.value })}
                />
                <textarea
                  className="input min-h-24 resize-y text-xs md:col-span-2"
                  placeholder="摘要"
                  value={metadataDraft.abstract}
                  onChange={(e) => setMetadataDraft({ ...metadataDraft, abstract: e.target.value })}
                />
              </div>
            </section>
            <section className="mb-5 rounded-lg border p-3 border-[var(--border)]">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h4 className="font-semibold">标签与合集</h4>
                {organizationMsg && (
                  <span className="text-xs text-[var(--success)]">
                    {organizationMsg}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <h5 className="mb-2 text-sm font-semibold">标签</h5>
                  <div className="mb-3 flex flex-wrap gap-1.5">
                    {(selected.tags ?? []).length === 0 && (
                      <span className="text-xs text-muted">
                        暂无标签
                      </span>
                    )}
                    {(selected.tags ?? []).map((tag) => (
                      <span key={tag.id} className="chip inline-flex items-center gap-1">
                        {tag.color && (
                          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: tag.color }} />
                        )}
                        {tag.name}
                        <button
                          onClick={() => removeSelectedTag(tag.id)}
                          disabled={organizationBusy}
                          className="text-[10px] text-faint"
                          
                        >
                          删除
                        </button>
                      </span>
                    ))}
                  </div>
                  <div className="mb-2 flex gap-2">
                    <select
                      className="input min-w-0 flex-1 py-1 text-xs"
                      value={selectedTagId}
                      onChange={(e) => setSelectedTagId(e.target.value)}
                    >
                      <option value="">选择已有标签</option>
                      {availableTags.map((tag) => (
                        <option key={tag.id} value={tag.id}>
                          {tag.name}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={attachExistingTag}
                      disabled={organizationBusy || !selectedTagId}
                      className="btn-ghost shrink-0 py-1 text-xs"
                    >
                      添加
                    </button>
                  </div>
                  <div className="grid grid-cols-[1fr_6rem] gap-2">
                    <input
                      className="input py-1 text-xs"
                      placeholder="新标签"
                      value={tagForm.name}
                      onChange={(e) => setTagForm({ ...tagForm, name: e.target.value })}
                    />
                    <input
                      className="input py-1 text-xs"
                      placeholder="#2563eb"
                      value={tagForm.color}
                      onChange={(e) => setTagForm({ ...tagForm, color: e.target.value })}
                    />
                    <button
                      onClick={createAndAttachTag}
                      disabled={organizationBusy}
                      className="btn-ghost py-1 text-xs md:col-span-2"
                    >
                      新建并添加标签
                    </button>
                  </div>
                </div>
                <div>
                  <h5 className="mb-2 text-sm font-semibold">合集</h5>
                  <div className="mb-3 flex flex-wrap gap-1.5">
                    {(selected.collections ?? []).length === 0 && (
                      <span className="text-xs text-muted">
                        暂无合集
                      </span>
                    )}
                    {(selected.collections ?? []).map((collection) => (
                      <span key={collection.id} className="chip inline-flex items-center gap-1">
                        {collection.name}
                        <button
                          onClick={() => removeSelectedCollection(collection.id)}
                          disabled={organizationBusy}
                          className="text-[10px] text-faint"
                          
                        >
                          移除
                        </button>
                      </span>
                    ))}
                  </div>
                  <div className="mb-2 flex gap-2">
                    <select
                      className="input min-w-0 flex-1 py-1 text-xs"
                      value={selectedCollectionId}
                      onChange={(e) => setSelectedCollectionId(e.target.value)}
                    >
                      <option value="">选择已有合集</option>
                      {availableCollections.map((collection) => (
                        <option key={collection.id} value={collection.id}>
                          {collection.name}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={addExistingCollection}
                      disabled={organizationBusy || !selectedCollectionId}
                      className="btn-ghost shrink-0 py-1 text-xs"
                    >
                      加入
                    </button>
                  </div>
                  <div className="space-y-2">
                    <input
                      className="input py-1 text-xs"
                      placeholder="新合集"
                      value={collectionForm.name}
                      onChange={(e) => setCollectionForm({ ...collectionForm, name: e.target.value })}
                    />
                    <input
                      className="input py-1 text-xs"
                      placeholder="合集说明"
                      value={collectionForm.description}
                      onChange={(e) => setCollectionForm({ ...collectionForm, description: e.target.value })}
                    />
                    <button
                      onClick={createAndAddCollection}
                      disabled={organizationBusy}
                      className="btn-ghost py-1 text-xs"
                    >
                      新建并加入合集
                    </button>
                  </div>
                </div>
              </div>
            </section>
              </>
            )}
            {detailTab === "thesis" && (
            <section className="mb-5 rounded-lg border p-3 border-[var(--border)]">
              <div className="mb-2 flex items-center justify-between gap-3">
                <h4 className="font-semibold">课题与章节链接</h4>
                <span className="text-xs text-faint">
                  {selectedThesisLinks.length} 条链接
                </span>
              </div>
              {thesisIndex.projectOptions.length === 0 ? (
                <p className="mb-3 text-sm text-muted">
                  还没有项目。先在“课题与章节”视图中新建研究方向或章节，再把这篇论文归入对应位置。
                </p>
              ) : (
                <div className="mb-3 grid grid-cols-1 gap-2 md:grid-cols-2">
                  <select
                    className="input py-1 text-xs"
                    value={detailLinkForm.target_type}
                    onChange={(e) =>
                      setDetailLinkForm({
                        ...detailLinkForm,
                        target_type: e.target.value as ThesisLinkForm["target_type"],
                        chapter_id: e.target.value === "chapter" ? detailLinkForm.chapter_id : "",
                      })
                    }
                  >
                    <option value="project">关联到项目</option>
                    <option value="chapter">关联到章节</option>
                  </select>
                  <select
                    className="input py-1 text-xs"
                    value={detailLinkForm.role}
                    onChange={(e) => setDetailLinkForm({ ...detailLinkForm, role: e.target.value })}
                  >
                    {Object.entries(THESIS_LINK_ROLE_LABELS).map(([role, label]) => (
                      <option key={role} value={role}>
                        {label}
                      </option>
                    ))}
                  </select>
                  <select
                    className="input py-1 text-xs"
                    value={detailLinkForm.project_id}
                    onChange={(e) =>
                      setDetailLinkForm({
                        ...detailLinkForm,
                        project_id: e.target.value,
                        chapter_id: "",
                      })
                    }
                  >
                    <option value="">选择项目</option>
                    {thesisIndex.projectOptions.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <select
                    className="input py-1 text-xs"
                    value={detailLinkForm.chapter_id}
                    onChange={(e) => setDetailLinkForm({ ...detailLinkForm, chapter_id: e.target.value })}
                    disabled={detailLinkForm.target_type !== "chapter" || !detailLinkForm.project_id}
                  >
                    <option value="">选择章节</option>
                    {detailChapterOptions.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <input
                    className="input py-1 text-xs md:col-span-2"
                    placeholder="链接备注，例如：相关工作第 2.1 节背景"
                    value={detailLinkForm.note}
                    onChange={(e) => setDetailLinkForm({ ...detailLinkForm, note: e.target.value })}
                  />
                  <button onClick={addSelectedThesisLink} disabled={detailLinkBusy} className="btn-ghost py-1 text-xs md:col-span-2">
                    {detailLinkBusy ? "处理中…" : "添加规划链接"}
                  </button>
                </div>
              )}
              {selectedThesisLinks.length === 0 ? (
                <p className="text-sm text-muted">
                  还没有规划链接。
                </p>
              ) : (
                <div className="space-y-2">
                  {selectedThesisLinks.map((link) => (
                    <div
                      key={link.id}
                      className="flex flex-col gap-2 rounded-lg border px-3 py-2 text-sm md:flex-row md:items-center border-[var(--border)]"
                      
                    >
                      <div className="min-w-0 flex-1">
                        <div className="font-medium">{thesisLinkTarget(link, thesisIndex)}</div>
                        <div className="text-xs text-muted">
                          {THESIS_LINK_ROLE_LABELS[link.role] ?? link.role}
                          {link.note ? ` · ${link.note}` : ""}
                        </div>
                      </div>
                      <button
                        onClick={() => removeSelectedThesisLink(link)}
                        disabled={detailLinkBusy}
                        className="btn-ghost shrink-0 py-1 text-xs text-[var(--danger)]"
                        
                      >
                        删除
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </section>
            )}
            {detailTab === "reading" && (
              <>
              <section className="rounded-lg border p-4 border-[var(--border)]">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h4 className="font-semibold">阅读状态</h4>
                  {workspaceLoading && (
                    <span className="text-xs text-faint">
                      加载中…
                    </span>
                  )}
                </div>
                {workspace ? (
                <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                    <select
                      className="input py-1 text-xs"
                      value={workspace.state.status}
                      onChange={(e) => updateReadingState({ status: e.target.value })}
                    >
                      {READING_STATUS.filter((status) => status !== "all").map((status) => (
                        <option key={status} value={status}>
                          {READING_STATUS_LABELS[status] ?? status}
                        </option>
                      ))}
                    </select>
                    <select
                      className="input py-1 text-xs"
                      value={workspace.state.priority}
                      onChange={(e) => updateReadingState({ priority: e.target.value })}
                    >
                      {["low", "normal", "high"].map((priority) => (
                        <option key={priority} value={priority}>
                          {READING_PRIORITY_LABELS[priority] ?? priority}
                        </option>
                      ))}
                    </select>
                    <select
                      className="input py-1 text-xs"
                      value={workspace.state.rating ?? ""}
                      onChange={(e) => updateReadingState({ rating: e.target.value ? Number(e.target.value) : null })}
                    >
                      <option value="">未评分</option>
                      {[1, 2, 3, 4, 5].map((score) => (
                        <option key={score} value={score}>
                          评分 {score}
                        </option>
                      ))}
                    </select>
                    <select
                      className="input py-1 text-xs"
                      value={workspace.state.relevance ?? ""}
                      onChange={(e) => updateReadingState({ relevance: e.target.value ? Number(e.target.value) : null })}
                    >
                      <option value="">暂无相关度</option>
                      {[1, 2, 3, 4, 5].map((score) => (
                        <option key={score} value={score}>
                          相关度 {score}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : (
                  <p className="text-sm text-faint">{workspaceLoading ? "加载中…" : "暂无阅读工作区数据。"}</p>
                )}
              </section>
              <section className="mt-4 rounded-lg border p-4 border-[var(--border)]">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <h4 className="font-semibold">论断（{claims.length}）</h4>
                </div>
                <p className="mb-2 text-xs text-faint">
                  这篇论文断言的核心结论。在「设置」开启论断抽取后由 AI 自动提炼，也可手动添加；
                  论断汇聚到「图谱 → 论断图」，矛盾关系会进入建议中心。
                </p>
                <div className="mb-2 flex gap-2">
                  <input
                    className="input flex-1 py-1 text-xs"
                    placeholder="添加一条论断，例如：该方法在低资源场景下依然有效"
                    value={claimDraft}
                    onChange={(e) => setClaimDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (shouldSubmitOnEnter(e.key, false, e.nativeEvent.isComposing)) void addClaim();
                    }}
                  />
                  <button onClick={addClaim} disabled={!claimDraft.trim()} className="btn-ghost shrink-0 py-1 text-xs">
                    添加论断
                  </button>
                </div>
                <div className="space-y-2">
                  {claims.map((claim) => (
                    <div key={claim.id} className="rounded-lg border p-2 text-xs border-[var(--border)]">
                      <div className="mb-1 flex items-center gap-1.5">
                        <span className="chip">{claim.kind === "supporting" ? "支撑论断" : "主论断"}</span>
                        <span className="chip text-muted">{claim.source === "ai" ? "AI 抽取" : "手动添加"}</span>
                        <button onClick={() => removeClaim(claim)} className="btn-ghost ml-auto py-0.5 text-xs">
                          删除
                        </button>
                      </div>
                      <p className="whitespace-pre-wrap">{claim.text}</p>
                    </div>
                  ))}
                  {claims.length === 0 && <p className="text-xs text-faint">还没有论断。</p>}
                </div>
              </section>
              </>
            )}
            {detailTab === "matrix" && (
              <section className="rounded-lg border p-4 border-[var(--border)]">
                {workspace ? (
                  <div>
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <h5 className="text-sm font-semibold">论文对照表</h5>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={suggestMatrix}
                          disabled={matrixSuggesting || workspaceLoading}
                          className="btn-ghost py-1 text-xs disabled:opacity-50"
                        >
                          {matrixSuggesting ? "生成中..." : "AI 草稿"}
                        </button>
                        <button onClick={() => clearSavedMatrix(matrixDraft)} className="btn-ghost py-1 text-xs">放弃本机草稿</button>
                        <button onClick={saveMatrix} className="btn-ghost py-1 text-xs">
                          保存矩阵
                        </button>
                      </div>
                    </div>
                    {workspaceMsg && (
                      <p className="mb-2 text-xs text-[var(--success)]">
                        {workspaceMsg}
                      </p>
                    )}
                    <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                      {MATRIX_FIELDS.map((field) => (
                        <textarea
                          key={field}
                          className="input min-h-16 resize-y text-xs"
                          placeholder={MATRIX_LABELS[field]}
                          value={matrixDraft[field]}
                          onChange={(e) => setMatrixDraft({ ...matrixDraft, [field]: e.target.value })}
                        />
                      ))}
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-faint">{workspaceLoading ? "加载中…" : "暂无论文对照表。"}</p>
                )}
              </section>
            )}
            {detailTab === "notes" && (
              <div className="space-y-4">
                {workspace ? (
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <div>
                      <h5 className="mb-2 text-sm font-semibold">笔记</h5>
                      <div className="mb-2 space-y-2">
                        <div className="flex gap-2">
                          <select
                            className="input w-28 py-1 text-xs"
                            value={noteDraft.kind}
                            onChange={(e) => setNoteDraft({ ...noteDraft, kind: e.target.value })}
                          >
                            {["note", "question", "idea", "critique", "todo"].map((kind) => (
                              <option key={kind} value={kind}>
                                {NOTE_KIND_LABELS[kind] ?? kind}
                              </option>
                            ))}
                          </select>
                          <input
                            className="input flex-1 py-1 text-xs"
                            placeholder="标签"
                            value={noteDraft.tags}
                            onChange={(e) => setNoteDraft({ ...noteDraft, tags: e.target.value })}
                          />
                        </div>
                        <textarea
                          className="input min-h-20 resize-y text-xs"
                          placeholder="添加阅读笔记"
                          value={noteDraft.content}
                          onChange={(e) => setNoteDraft({ ...noteDraft, content: e.target.value })}
                        />
                        <button onClick={addNote} className="btn-ghost py-1 text-xs">
                          添加笔记
                        </button>
                      </div>
                      <div className="space-y-2">
                        {workspace.notes.map((note) => (
                          <div key={note.id} className="rounded-lg border p-2 text-xs border-[var(--border)]">
                            {editingNoteId === note.id ? (
                              <div className="space-y-2">
                                <div className="flex gap-2">
                                  <select
                                    className="input w-28 py-1 text-xs"
                                    value={noteEditDraft.kind}
                                    onChange={(e) => setNoteEditDraft({ ...noteEditDraft, kind: e.target.value })}
                                  >
                                    {["note", "question", "idea", "critique", "todo"].map((kind) => (
                                      <option key={kind} value={kind}>
                                        {NOTE_KIND_LABELS[kind] ?? kind}
                                      </option>
                                    ))}
                                  </select>
                                  <input
                                    className="input flex-1 py-1 text-xs"
                                    placeholder="标签"
                                    value={noteEditDraft.tags}
                                    onChange={(e) => setNoteEditDraft({ ...noteEditDraft, tags: e.target.value })}
                                  />
                                </div>
                                <textarea
                                  className="input min-h-20 resize-y text-xs"
                                  value={noteEditDraft.content}
                                  onChange={(e) => setNoteEditDraft({ ...noteEditDraft, content: e.target.value })}
                                />
                                <div className="flex gap-2">
                                  <button onClick={() => saveNoteEdit(note)} className="btn-primary py-1 text-xs">
                                    保存
                                  </button>
                                  <button onClick={() => setEditingNoteId(null)} className="btn-ghost py-1 text-xs">
                                    取消
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <>
                                <div className="mb-1 flex items-center gap-2">
                                  <span className="chip text-muted">{NOTE_KIND_LABELS[note.kind] ?? note.kind}</span>
                                  <span >{note.tags.join(", ")}</span>
                                  <button onClick={() => beginEditNote(note)} className="btn-ghost ml-auto py-0.5 text-xs">
                                    编辑
                                  </button>
                                  <button onClick={() => removeNote(note)} className="btn-ghost py-0.5 text-xs">
                                    删除
                                  </button>
                                </div>
                                <p className="whitespace-pre-wrap">{note.content}</p>
                              </>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>

                    <div>
                      <h5 className="mb-2 text-sm font-semibold">摘录</h5>
                      <div className="mb-2 space-y-2">
                        <textarea
                          className="input min-h-20 resize-y text-xs"
                          placeholder="摘录原文"
                          value={excerptDraft.quote}
                          onChange={(e) => setExcerptDraft({ ...excerptDraft, quote: e.target.value })}
                        />
                        <div className="grid grid-cols-2 gap-2">
                          <input
                            className="input py-1 text-xs"
                            placeholder="页码"
                            value={excerptDraft.page}
                            onChange={(e) => setExcerptDraft({ ...excerptDraft, page: e.target.value })}
                          />
                          <input
                            className="input py-1 text-xs"
                            placeholder="章节"
                            value={excerptDraft.section}
                            onChange={(e) => setExcerptDraft({ ...excerptDraft, section: e.target.value })}
                          />
                          <input
                            className="input py-1 text-xs"
                            placeholder="定位"
                            value={excerptDraft.locator}
                            onChange={(e) => setExcerptDraft({ ...excerptDraft, locator: e.target.value })}
                          />
                          <input
                            className="input py-1 text-xs"
                            placeholder="标签"
                            value={excerptDraft.tags}
                            onChange={(e) => setExcerptDraft({ ...excerptDraft, tags: e.target.value })}
                          />
                        </div>
                        <textarea
                          className="input min-h-16 resize-y text-xs"
                          placeholder="这段摘录为什么重要"
                          value={excerptDraft.note}
                          onChange={(e) => setExcerptDraft({ ...excerptDraft, note: e.target.value })}
                        />
                        <button onClick={addExcerpt} className="btn-ghost py-1 text-xs">
                          添加摘录
                        </button>
                      </div>
                      <div className="space-y-2">
                        {workspace.excerpts.map((excerpt) => (
                          <div key={excerpt.id} className="rounded-lg border p-2 text-xs border-[var(--border)]">
                            {editingExcerptId === excerpt.id ? (
                              <div className="space-y-2">
                                <textarea
                                  className="input min-h-20 resize-y text-xs"
                                  value={excerptEditDraft.quote}
                                  onChange={(e) => setExcerptEditDraft({ ...excerptEditDraft, quote: e.target.value })}
                                />
                                <div className="grid grid-cols-2 gap-2">
                                  <input
                                    className="input py-1 text-xs"
                                    placeholder="页码"
                                    value={excerptEditDraft.page}
                                    onChange={(e) => setExcerptEditDraft({ ...excerptEditDraft, page: e.target.value })}
                                  />
                                  <input
                                    className="input py-1 text-xs"
                                    placeholder="章节"
                                    value={excerptEditDraft.section}
                                    onChange={(e) => setExcerptEditDraft({ ...excerptEditDraft, section: e.target.value })}
                                  />
                                  <input
                                    className="input py-1 text-xs"
                                    placeholder="定位"
                                    value={excerptEditDraft.locator}
                                    onChange={(e) => setExcerptEditDraft({ ...excerptEditDraft, locator: e.target.value })}
                                  />
                                  <input
                                    className="input py-1 text-xs"
                                    placeholder="标签"
                                    value={excerptEditDraft.tags}
                                    onChange={(e) => setExcerptEditDraft({ ...excerptEditDraft, tags: e.target.value })}
                                  />
                                </div>
                                <textarea
                                  className="input min-h-16 resize-y text-xs"
                                  placeholder="这段摘录为什么重要"
                                  value={excerptEditDraft.note}
                                  onChange={(e) => setExcerptEditDraft({ ...excerptEditDraft, note: e.target.value })}
                                />
                                <div className="flex gap-2">
                                  <button onClick={() => saveExcerptEdit(excerpt)} className="btn-primary py-1 text-xs">
                                    保存
                                  </button>
                                  <button onClick={() => setEditingExcerptId(null)} className="btn-ghost py-1 text-xs">
                                    取消
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <>
                                <div className="mb-1 flex items-center gap-2">
                                  {excerpt.page && <span className="chip">第 {excerpt.page} 页</span>}
                                  {excerpt.section && <span className="chip text-muted">{excerpt.section}</span>}
                                  <span >{excerpt.tags.join(", ")}</span>
                                  <button onClick={() => beginEditExcerpt(excerpt)} className="btn-ghost ml-auto py-0.5 text-xs">
                                    编辑
                                  </button>
                                  <button onClick={() => removeExcerpt(excerpt)} className="btn-ghost py-0.5 text-xs">
                                    删除
                                  </button>
                                </div>
                                <blockquote className="mb-1 whitespace-pre-wrap border-l-2 pl-2 text-muted border-[var(--accent)]">
                                  {excerpt.quote}
                                </blockquote>
                                {excerpt.note && <p >{excerpt.note}</p>}
                              </>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-faint">{workspaceLoading ? "加载中…" : "暂无笔记或摘录。"}</p>
                )}
              </div>
            )}

            {detailTab === "overview" && (selected.summary ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <h4 className="font-semibold">AI 摘要</h4>
                  <button onClick={reanalyze} disabled={analyzing} className="btn-ghost px-2.5 py-1 text-xs">
                    {analyzing ? "重新分析中…" : (<><RotateCw size={12} /> 重新分析</>)}
                  </button>
                </div>
                {Object.entries(selected.summary).map(([k, v]) => (
                  <div key={k} className="text-sm">
                    <span className="font-medium">{SUMMARY_LABELS[k] ?? k}：</span>
                    {v}
                  </div>
                ))}
              </div>
            ) : (
              (() => {
                const analysisView = paperAnalysisView({
                  hasSummary: false,
                  analysisStatus: selected.analysis?.status ?? null,
                  analysisError: selected.analysis?.error ?? null,
                  // readiness 尚未返回时（null）按已配置处理，避免误报“已跳过”。
                  llmConfigured: llmConfigured !== false,
                });
                const headingColor =
                  analysisView.state === "failed"
                    ? "var(--danger)"
                    : analysisView.state === "skipped"
                      ? "var(--accent)"
                      : undefined;
                return (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm" style={headingColor ? { color: headingColor } : undefined}>
                          {analysisView.label}
                        </p>
                        <p className="mt-0.5 text-xs leading-relaxed text-muted">{analysisView.detail}</p>
                      </div>
                      <div className="flex shrink-0 gap-2">
                        {analysisView.state === "skipped" && (
                          <button onClick={() => onNavigate?.("settings")} className="btn-ghost py-1 text-xs">
                            去设置配置模型
                          </button>
                        )}
                        {analysisView.canRetry && (
                          <button onClick={reanalyze} disabled={analyzing} className="btn-ghost px-2.5 py-1 text-xs">
                            {analyzing
                              ? "分析中…"
                              : (<><RotateCw size={12} /> {analysisView.state === "failed" ? "重试分析" : "立即分析"}</>)}
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })()
            ))}

            {detailTab === "citations" && (
            <div className="mt-6 border-t pt-4 border-[var(--border)]">
              <div className="mb-2 flex items-center gap-3">
                <h4 className="font-semibold">
                  引用
                  <span className="ml-2 text-xs font-normal text-faint">
                    本文引用 {citations?.outgoing.length ?? 0} 条 · 被库内引用 {citations?.incoming.length ?? 0} 条
                  </span>
                </h4>
              </div>
              <p className="mb-2 text-xs text-faint">
                从入库全文的参考文献章节自动抽取；「库外」条目可按标题搜索后入库，入库时会自动回填匹配。
              </p>
              {citationsLoading && <p className="text-sm text-faint">加载中…</p>}
              {!citationsLoading && citations && citations.outgoing.length === 0 && citations.incoming.length === 0 && (
                <p className="text-sm text-faint">暂无引用数据。导入带参考文献全文的 PDF 后自动抽取。</p>
              )}
              {citations && citations.outgoing.length > 0 && (
                <>
                  <div className="mb-1 text-xs font-medium text-muted">本文引用</div>
                  <ul className="mb-3 space-y-1.5">
                    {citations.outgoing.map((c) => (
                      <li key={c.id} className="rounded-lg p-2.5 text-sm bg-[var(--surface-2)]">
                        <div className="font-medium">
                          {c.match_status === "matched" && c.target_paper_id ? (
                            <button
                              onClick={() => openById(c.target_paper_id!)}
                              className="text-[var(--accent)] hover:underline"
                            >
                              {c.ref_title || "（无标题）"} → 库内：{c.target_title}
                            </button>
                          ) : (
                            c.ref_title || "（无标题）"
                          )}
                        </div>
                        <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted">
                          {c.ref_authors.slice(0, 3).join(", ")}
                          {c.ref_authors.length > 3 ? " 等" : ""}
                          {c.ref_year ? ` · ${c.ref_year}` : ""}
                          {c.match_status === "matched" ? (
                            <span className="chip">已匹配库内</span>
                          ) : (
                            <span className="chip">库外</span>
                          )}
                          {c.match_status !== "matched" &&
                            canQueueExternal({
                              title: c.ref_title,
                              doi: c.ref_doi,
                              arxiv_id: c.ref_arxiv_id,
                            }) &&
                            (queuedExternalPapers[`cite:${c.id}`] != null ? (
                              <button
                                onClick={() => void openById(queuedExternalPapers[`cite:${c.id}`])}
                                className="text-[var(--accent)] hover:underline"
                              >
                                已加入待读 · 打开
                              </button>
                            ) : (
                              <button
                                onClick={() =>
                                  void queueExternalPaper(
                                    `cite:${c.id}`,
                                    {
                                      title: c.ref_title,
                                      doi: c.ref_doi,
                                      arxiv_id: c.ref_arxiv_id,
                                      year: c.ref_year,
                                      authors: c.ref_authors,
                                    },
                                    { refreshCitations: true },
                                  )
                                }
                                disabled={Boolean(queueingExternal[`cite:${c.id}`])}
                                className="btn-ghost py-0.5 text-xs"
                                title="入库（有 arXiv ID 优先走 arXiv）并加入待读"
                              >
                                {queueingExternal[`cite:${c.id}`] ? "加入中…" : "一键加入待读"}
                              </button>
                            ))}
                          {c.match_status !== "matched" && (c.ref_title || c.raw_ref) && (
                            <a
                              href={`https://arxiv.org/search/?query=${encodeURIComponent(c.ref_title || c.raw_ref.slice(0, 80))}&searchtype=all`}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[var(--accent)] hover:underline"
                              title="在 arXiv 按标题搜索，找到后用「导入 → ArXiv」入库即可自动关联"
                            >
                              按标题搜索入库
                            </a>
                          )}
                        </div>
                        <details className="mt-1">
                          <summary className="cursor-pointer text-xs text-faint">原文引用串</summary>
                          <p className="mt-1 break-words text-xs text-muted">{c.raw_ref}</p>
                        </details>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {citations && citations.incoming.length > 0 && (
                <>
                  <div className="mb-1 text-xs font-medium text-muted">被库内引用</div>
                  <ul className="space-y-1.5">
                    {citations.incoming.map((c) => (
                      <li key={c.id} className="rounded-lg p-2.5 text-sm bg-[var(--surface-2)]">
                        <button
                          onClick={() => openById(c.source_paper_id!)}
                          className="font-medium text-[var(--accent)] hover:underline"
                        >
                          {c.source_title ?? "（无标题）"}
                        </button>
                        {c.ref_year ? <span className="ml-2 text-xs text-muted">· {c.ref_year}</span> : null}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
            )}

            {detailTab === "related" && (
            <div className="mt-6 border-t pt-4 border-[var(--border)]">
              <div className="mb-2 flex items-center gap-3">
                <h4 className="font-semibold">相关研究</h4>
                <button onClick={() => findRelated(selected.id)} disabled={relatedLoading} className="btn-ghost">
                  {relatedLoading ? "搜索中…" : "查找相关（库外）"}
                </button>
              </div>
              <p className="mb-2 text-xs text-faint">
                通过 OpenAlex 发现库外研究；服务繁忙或网络失败时可重试。
              </p>
              {relatedError && !relatedLoading && (
                <p className="text-sm text-[var(--danger)]">
                  {relatedError}
                </p>
              )}
              {related !== null && related.length === 0 && !relatedLoading && !relatedError && (
                <p className="text-sm text-faint">
                  未找到相关研究。
                </p>
              )}
              {related && related.length > 0 && (
                <ul className="space-y-2">
                  {related.map((r) => {
                    const key = `rel:${r.openalex_id ?? r.title ?? ""}`;
                    const queuedId = queuedExternalPapers[key];
                    return (
                    <li
                      key={r.openalex_id ?? r.title ?? Math.random()}
                      className="rounded-lg p-2.5 text-sm bg-[var(--surface-2)]"

                    >
                      <div className="font-medium text-[var(--accent)]">
                        {r.doi ? (
                          <a
                            href={`https://doi.org/${r.doi}`}
                            target="_blank"
                            rel="noreferrer"

                            className="hover:underline"
                          >
                            {r.title ?? "（无标题）"}
                          </a>
                        ) : (
                          r.title ?? "（无标题）"
                        )}
                      </div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted">
                        <span>
                          {r.authors.slice(0, 3).join(", ")}
                          {r.authors.length > 3 ? " 等" : ""} {r.year ? `· ${r.year}` : ""}
                          {r.cited_by_count ? ` · 被引 ${r.cited_by_count}` : ""}
                        </span>
                        {canQueueExternal({ title: r.title, doi: r.doi }) &&
                          (queuedId != null ? (
                            <button
                              onClick={() => void openById(queuedId)}
                              className="btn-ghost py-0.5 text-xs"
                            >
                              已加入待读 · 打开
                            </button>
                          ) : (
                            <button
                              onClick={() =>
                                void queueExternalPaper(
                                  key,
                                  { title: r.title, doi: r.doi, year: r.year, authors: r.authors },
                                  { refreshRelated: true },
                                )
                              }
                              disabled={Boolean(queueingExternal[key])}
                              className="btn-ghost py-0.5 text-xs"
                              title="入库并加入待读（重复论文会定位到已有记录）"
                            >
                              {queueingExternal[key] ? "加入中…" : "一键加入待读"}
                            </button>
                          ))}
                      </div>
                    </li>
                    );
                  })}
                </ul>
              )}
            </div>
            )}
            </div>
          </div>
        </div>
      )}

      {selected && readerOpen && (
        <PdfReader
          key={selected.id}
          paperId={selected.id}
          title={selected.title}
          onSaveExcerpt={saveReaderExcerpt}
          onSaveExcerptNote={saveReaderExcerptNote}
          onCreateNote={createReaderNote}
          onRefreshNotes={async () => {
            const id = selected.id;
            try {
              const reading = await api.getReadingWorkspace(id);
              setWorkspace(current => current?.state.paper_id === id ? {...current, notes: reading.notes, excerpts: reading.excerpts} : current);
            } catch (e: any) { toast.error(e.message); }
          }}
          onAskAi={(text) => onAskAboutPaper?.(selected.id, selected.title, text)}
          notes={workspace?.notes ?? []}
          excerpts={workspace?.excerpts ?? []}
          initialPage={workspace?.state?.last_page ?? null}
          onProgress={commitReaderProgress}
          onClose={closeReader}
          onOpenPaper={async id => {
            try {
              const [paper, reading] = await Promise.all([api.getPaper(id), api.getReadingWorkspace(id)]);
              await closeReader(); setSelected(paper); setWorkspace(reading);
              setMetadataDraft(metadataDraftFromPaper(paper));
            } catch (e: any) { toast.error(e.message); }
          }}
        />
      )}

      <Drawer
        open={importOpen}
        onClose={() => setImportOpen(false)}
        title="导入论文"
        width="max-w-xl"
      >
        {llmConfigured != null && (
          <div
            className="mb-3 rounded-lg px-3 py-2 text-xs leading-relaxed"
            style={
              llmConfigured
                ? { backgroundColor: "color-mix(in srgb, var(--success) 10%, transparent)", color: "var(--success)" }
                : {
                    backgroundColor: "color-mix(in srgb, var(--accent) 10%, transparent)",
                    color: "var(--accent)",
                  }
            }
          >
            {aiAnalysisHint(llmConfigured)}
            {!llmConfigured && (
              <button
                onClick={() => onNavigate?.("settings")}
                className="btn-ghost ml-2 py-0.5 text-xs"
              >
                去设置
              </button>
            )}
          </div>
        )}
        <Tabs
          tabs={IMPORT_TABS}
          value={importTab}
          onChange={(t) => setImportTab(t as ImportTab)}
        />
        <div className="mt-4 space-y-2">
          {importTab === "manual" && (
            <>
              <input
                className="input"
                placeholder="标题"
                value={manualDraft.title}
                onChange={(e) => setManualDraft({ ...manualDraft, title: e.target.value })}
              />
              <textarea
                className="input h-20 resize-none"
                placeholder="作者，每行一位"
                value={manualDraft.authors}
                onChange={(e) => setManualDraft({ ...manualDraft, authors: e.target.value })}
              />
              <div className="grid grid-cols-2 gap-2">
                <input
                  className="input"
                  placeholder="年份"
                  value={manualDraft.year}
                  onChange={(e) => setManualDraft({ ...manualDraft, year: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="期刊/会议"
                  value={manualDraft.venue}
                  onChange={(e) => setManualDraft({ ...manualDraft, venue: e.target.value })}
                />
              </div>
              <input
                className="input"
                placeholder="Citation key"
                value={manualDraft.citation_key}
                onChange={(e) => setManualDraft({ ...manualDraft, citation_key: e.target.value })}
              />
              <textarea
                className="input h-20 resize-none"
                placeholder="摘要"
                value={manualDraft.abstract}
                onChange={(e) => setManualDraft({ ...manualDraft, abstract: e.target.value })}
              />
              <div className="grid grid-cols-2 gap-2">
                <input
                  className="input"
                  placeholder="DOI"
                  value={manualDraft.doi}
                  onChange={(e) => setManualDraft({ ...manualDraft, doi: e.target.value })}
                />
                <input
                  className="input"
                  placeholder="arXiv ID"
                  value={manualDraft.arxiv_id}
                  onChange={(e) => setManualDraft({ ...manualDraft, arxiv_id: e.target.value })}
                />
              </div>
              {manualError && <p role="alert" className="text-sm text-red-600">{manualError}</p>}
              <button onClick={createManualPaper} disabled={loading} className="btn-primary w-full">
                添加到论文库
              </button>
            </>
          )}
          {importTab === "bibtex" && (
            <>
              <textarea
                className="input h-40 font-mono resize-none"
                placeholder="@article{...}"
                value={bibtex}
                onChange={(e) => setBibtex(e.target.value)}
              />
              <button onClick={ingestBibtex} disabled={loading} className="btn-primary w-full">
                导入
              </button>
              {textImportResults.length > 0 && (
                <ImportResultList results={textImportResults} onOpen={(id) => void openById(id)} />
              )}
            </>
          )}
          {importTab === "ris" && (
            <>
              <textarea
                className="input h-40 resize-none font-mono"
                placeholder={"TY  - JOUR\nTI  - ...\nER  -"}
                value={ris}
                onChange={(e) => setRis(e.target.value)}
              />
              <button onClick={ingestRis} disabled={loading} className="btn-primary w-full">
                导入 RIS
              </button>
              <p className="text-xs text-faint">支持 Zotero / EndNote 导出的 RIS。</p>
              {textImportResults.length > 0 && (
                <ImportResultList results={textImportResults} onOpen={(id) => void openById(id)} />
              )}
            </>
          )}
          {importTab === "arxiv" && (
            <>
              <input
                className="input"
                placeholder="例如 1706.03762"
                value={arxivId}
                onChange={(e) => setArxivId(e.target.value)}
              />
              <button onClick={ingestArxiv} disabled={loading} className="btn-primary w-full">
                获取并导入
              </button>
            </>
          )}
          {importTab === "pdf" && (
            <>
              <label className={`btn-primary inline-block cursor-pointer ${loading ? "opacity-60" : ""}`}>
                选择 PDF（可多选）…
                <input
                  type="file"
                  accept="application/pdf"
                  multiple
                  className="hidden"
                  disabled={loading}
                  onChange={async (e) => {
                    await importPdfFiles(e.target.files);
                    e.target.value = "";
                  }}
                />
              </label>
              <p className="text-xs text-faint">
                文字版 PDF 可以提取原文。扫描版或纯图片 PDF 可能无法读取文字。
              </p>
              {pdfImportQueue.length > 0 && (
                <div className="space-y-1 text-xs">
                  {(() => {
                    const summary = summarizePdfImport(pdfImportQueue);
                    if (summary.remaining > 0) return null;
                    return (
                      <div className="rounded-lg px-2 py-1" style={{ backgroundColor: "var(--surface-2)" }} aria-live="polite">
                        导入完成：成功 {summary.done} 篇{summary.failed > 0 ? `，失败 ${summary.failed} 篇` : ""}。
                      </div>
                    );
                  })()}
                  {pdfImportQueue.map((item) => (
                    <div
                      key={item.id}
                      className="rounded-lg border px-2 py-1.5"
                      style={{ borderColor: "var(--border)", backgroundColor: "var(--surface-2)" }}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="min-w-0 truncate font-medium">{item.name}</span>
                        <div className="flex shrink-0 items-center gap-1">
                          <span className="chip">{PDF_IMPORT_STATUS_LABELS[item.status]}</span>
                          {item.status === "done" && item.paperId != null && (
                            <button
                              onClick={() => void openById(item.paperId as number)}
                              className="btn-ghost py-0.5 text-xs"
                            >
                              打开
                            </button>
                          )}
                        </div>
                      </div>
                      {item.error && (
                        <div className="mt-1 leading-relaxed text-[var(--danger)]">{item.error}</div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </Drawer>
    </Shell>
  );
}
