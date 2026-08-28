import { useEffect, useMemo, useState } from "react";
import {
  api,
  MatrixRow,
  Paper,
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
import { Drawer } from "../components/ui/Drawer";
import LibraryDiagnosticsPanel from "../components/LibraryDiagnosticsPanel";
import ReadinessPanel from "../components/ReadinessPanel";
import ResearchProgressPanel from "../components/ResearchProgressPanel";
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
  markPdfImportItem,
  type PdfImportItem,
} from "./pdfBatchModel";
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

// 论文详情 modal 的 Tab 分组——把原来单页 7 段塞进 6 个 Tab，减轻信息过载。
type DetailTab = "overview" | "reading" | "thesis" | "matrix" | "notes" | "related";
const DETAIL_TABS: { key: DetailTab; label: string }[] = [
  { key: "overview", label: "概览" },
  { key: "reading", label: "阅读工作区" },
  { key: "thesis", label: "论文规划" },
  { key: "matrix", label: "审阅矩阵" },
  { key: "notes", label: "笔记 & 摘录" },
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

// Library 顶层双视图：论文库（列表为主）⇄ 研究仪表板（诊断面板集中）。
type LibView = "library" | "dashboard";

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

export default function Library({
  openPaperId,
  onConsumedOpen,
  onNavigate,
}: {
  openPaperId: number | null;
  onConsumedOpen: () => void;
  onNavigate?: (page: string) => void;
}) {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();
  const confirm = useConfirm();
  const [bibtex, setBibtex] = useState("");
  const [ris, setRis] = useState("");
  const [arxivId, setArxivId] = useState("");
  const [manualDraft, setManualDraft] = useState<ManualPaperForm>(emptyManualPaperForm());
  const [pdfImportQueue, setPdfImportQueue] = useState<PdfImportItem<File>[]>([]);
  const [selected, setSelected] = useState<Paper | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");
  const [libView, setLibView] = useState<LibView>("library");
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
  const [relatedError, setRelatedError] = useState(false);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"year_desc" | "year_asc" | "title">("year_desc");
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
  const [noteDraft, setNoteDraft] = useState<NoteForm>({ kind: "note", content: "", tags: "" });
  const [editingNoteId, setEditingNoteId] = useState<number | null>(null);
  const [noteEditDraft, setNoteEditDraft] = useState<NoteForm>({ kind: "note", content: "", tags: "" });
  const [excerptDraft, setExcerptDraft] = useState<ExcerptForm>({ quote: "", page: "", section: "", locator: "", note: "", tags: "" });
  const [editingExcerptId, setEditingExcerptId] = useState<number | null>(null);
  const [excerptEditDraft, setExcerptEditDraft] = useState<ExcerptForm>({ quote: "", page: "", section: "", locator: "", note: "", tags: "" });
  const [matrixSuggesting, setMatrixSuggesting] = useState(false);
  const [detailLinkForm, setDetailLinkForm] = useState<ThesisLinkForm>({
    target_type: "project",
    project_id: "",
    chapter_id: "",
    role: "related",
    note: "",
  });
  const [detailLinkBusy, setDetailLinkBusy] = useState(false);
  const [matrixDraft, setMatrixDraft] = useState<Record<MatrixField, string>>({
    problem: "",
    method: "",
    dataset: "",
    metrics: "",
    results: "",
    limitations: "",
    novelty: "",
    relation_to_thesis: "",
    future_work: "",
    notes: "",
  });
  const thesisIndex = useMemo(() => buildThesisIndex(thesisWorkspace), [thesisWorkspace]);
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

  async function load() {
    setLoading(true);
    try {
      const [nextPapers, nextTags, nextCollections] = await Promise.all([
        api.listPapers(),
        api.listTags(),
        api.listCollections(),
      ]);
      setPapers(nextPapers);
      setTags(nextTags);
      setCollections(nextCollections);
      setError(null);
      await loadThesisWorkspace();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadReadingWorkspace(id: number) {
    setWorkspaceLoading(true);
    try {
      const next = await api.getReadingWorkspace(id);
      setWorkspace(next);
      const nextMatrix = { ...matrixDraft };
      for (const field of MATRIX_FIELDS) {
        nextMatrix[field] = (next.matrix?.[field] as string | null) ?? "";
      }
      setMatrixDraft(nextMatrix);
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
          q: query.trim() || undefined,
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
      api.listPapers(),
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
  }, [selected?.id]);

  useEffect(() => {
    const activePaperIds = new Set(papers.map((paper) => paper.id));
    setBulkSelectedPaperIds((ids) => ids.filter((id) => activePaperIds.has(id)));
  }, [papers]);

  useEffect(() => {
    if (view === "matrix") loadMatrix();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, readingStatus, highPriorityOnly, minRelevance]);

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

  // Close the detail modal on Escape (keyboard parity with the overlay click).
  useEffect(() => {
    if (!selected) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setSelected(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected]);

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
        const nextMatrix = { ...matrixDraft };
        for (const field of MATRIX_FIELDS) nextMatrix[field] = (r.matrix?.[field] as string | null) ?? "";
        setMatrixDraft(nextMatrix);
        setRelated(null);
        setRelatedError(false);
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
      await api.ingestBibtex(bibtex);
      setBibtex("");
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
      await api.ingestRis(ris);
      setRis("");
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
      await api.ingestArxiv(arxivId.trim());
      setArxivId("");
      await load();
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
    setLoading(true);
    let imported = false;
    try {
      for (const item of queue) {
        if (item.status !== "queued") continue;
        setPdfImportQueue((current) => markPdfImportItem(current, item.id, { status: "importing" }));
        try {
          const paper = await api.ingestPdf(item.file);
          imported = true;
          setPdfImportQueue((current) =>
            markPdfImportItem(current, item.id, { status: "done", paperId: paper.id }),
          );
        } catch (err: any) {
          setPdfImportQueue((current) =>
            markPdfImportItem(current, item.id, {
              status: "failed",
              error: err?.message ?? "导入失败",
            }),
          );
        }
      }
      if (imported) await load();
    } finally {
      setLoading(false);
    }
  }

  async function createManualPaper() {
    const payload = buildManualPaperPayload(manualDraft);
    if (!payload) {
      setError("手动录入至少需要标题，年份必须是非负整数。");
      return;
    }
    setLoading(true);
    try {
      const created = await api.createManualPaper(payload);
      setManualDraft(emptyManualPaperForm());
      await load();
      await open(created);
    } catch (e: any) {
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
    const nextMatrix = { ...matrixDraft };
    for (const field of MATRIX_FIELDS) nextMatrix[field] = (reading.matrix?.[field] as string | null) ?? "";
    setMatrixDraft(nextMatrix);
    setRelated(null);
  }

  async function open(p: Paper) {
    await openById(p.id);
  }

  async function findRelated(id: number) {
    setRelatedLoading(true);
    setRelatedError(false);
    try {
      setRelated(await api.relatedPapers(id));
    } catch {
      setRelated(null);
      setRelatedError(true);
    } finally {
      setRelatedLoading(false);
    }
  }

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
    try {
      const matrix = await api.saveReviewMatrix(selected.id, matrixDraft);
      setWorkspace((prev) => (prev ? { ...prev, matrix } : prev));
      setWorkspaceMsg("审阅矩阵已保存。");
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
      setWorkspace((prev) => (prev ? { ...prev, notes: [note, ...prev.notes] } : prev));
      setNoteDraft({ kind: "note", content: "", tags: "" });
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
      setWorkspace((prev) => (prev ? { ...prev, excerpts: [...prev.excerpts, excerpt] } : prev));
      setExcerptDraft({ quote: "", page: "", section: "", locator: "", note: "", tags: "" });
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
      message: "将删除这条论文规划链接，此操作不可撤销。",
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

  // Client-side filter + sort — the library is local and small; a round-trip
  // per keystroke would be wasteful.
  const visible = papers
    .filter((p) => {
      const q = query.trim().toLowerCase();
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
      if (sort === "title") return (a.title ?? "").localeCompare(b.title ?? "");
      const dy = (b.year ?? 0) - (a.year ?? 0);
      return sort === "year_asc" ? -dy : dy;
    });

  return (
    <Shell max="wide">
      <Tabs
        tabs={[{ key: "library", label: "论文库" }, { key: "dashboard", label: "研究仪表板" }]}
        value={libView}
        onChange={(v) => setLibView(v as LibView)}
        className="mb-4"
      />
      {libView === "dashboard" ? (
        <div className="space-y-4">
          <ReadinessPanel onNavigate={onNavigate} />
          <ResearchProgressPanel onNavigate={onNavigate} />
          <LibraryDiagnosticsPanel onOpenPaper={openById} onNavigate={onNavigate} onLibraryChanged={load} />
        </div>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="论文总数" value={papers.length} />
            <Stat
              label="已总结"
              value={papers.filter((p) => p.has_summary).length}
              accent="var(--accent)"
            />
            <Stat
              label="待读"
              value={papers.filter((p) =>
                ["unread", "queued"].includes(p.reading?.status ?? "unread"),
              ).length}
            />
            <Stat
              label="高优先级"
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
              矩阵
            </button>
            <button
              className={view === "thesis" ? "btn-primary py-1 text-xs" : "btn-ghost py-1 text-xs"}
              onClick={() => setView("thesis")}
            >
              论文规划
            </button>
          </div>
          {view !== "thesis" && (
            <>
          <input
            className="input max-w-xs"
            placeholder="搜索标题、作者、概念…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            className="input max-w-[10rem]"
            value={sort}
            onChange={(e) => setSort(e.target.value as typeof sort)}
          >
            <option value="year_desc">最新优先</option>
            <option value="year_asc">最旧优先</option>
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
              <option value="all">全部论文规划目标</option>
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
            {visible.length} / {papers.length}
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
            <h3 className="font-semibold">审阅矩阵</h3>
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
                  <th className="py-2 pr-3">论文规划</th>
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
            const nextMatrix = { ...matrixDraft };
            for (const field of MATRIX_FIELDS) nextMatrix[field] = (reading.matrix?.[field] as string | null) ?? "";
            setMatrixDraft(nextMatrix);
            setRelated(null);
          }}
        />
      )}

      {view !== "thesis" && (
        <div className="space-y-2">
        {bulkSelectedPaperIds.length > 0 && (
          <div
            className="rounded-lg border px-3 py-2 border-[var(--border)] bg-[var(--surface-2)]"
            
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">已选 {bulkSelectedPaperIds.length} 篇论文</span>
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
        {papers.length === 0 && !loading && (
          <EmptyState
            icon={<BookOpen size={20} />}
            title="论文库还是空的"
            hint="导入你的第一篇论文，系统会自动解析、总结并生成图谱。"
            action={
              <button onClick={() => setImportOpen(true)} className="btn-primary">
                <Plus size={14} /> 导入论文
              </button>
            }
          />
        )}
        {visible.length === 0 && papers.length > 0 && (
          <div className="card text-center text-muted">
            没有匹配“{query}”的论文。
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
        </div>
      )}
        </>
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
                <button
                  onClick={() => setSelected(null)}
                  className="btn-subtle shrink-0 px-2"
                  aria-label="关闭"
                >
                  <X size={18} />
                </button>
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
                  文本提取质量较低（{Math.round(selected.parse_confidence * 100)}%）。这看起来是扫描版
                  PDF，AI 摘要与全文检索会受限。
                </div>
              )}
            </div>
            <div className="shrink-0 px-6">
              <Tabs tabs={DETAIL_TABS} value={detailTab} onChange={(t) => setDetailTab(t as DetailTab)} />
            </div>
            <div className="flex-1 overflow-y-auto p-6 pt-4">
            {detailTab === "overview" && (
              <>
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
                <h4 className="font-semibold">论文规划链接</h4>
                <span className="text-xs text-faint">
                  {selectedThesisLinks.length} 条链接
                </span>
              </div>
              {thesisIndex.projectOptions.length === 0 ? (
                <p className="mb-3 text-sm text-muted">
                  还没有项目。先在“论文规划”视图中新建研究方向或章节，再把这篇论文归入对应位置。
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
            )}
            {detailTab === "matrix" && (
              <section className="rounded-lg border p-4 border-[var(--border)]">
                {workspace ? (
                  <div>
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <h5 className="text-sm font-semibold">审阅矩阵</h5>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={suggestMatrix}
                          disabled={matrixSuggesting || workspaceLoading}
                          className="btn-ghost py-1 text-xs disabled:opacity-50"
                        >
                          {matrixSuggesting ? "生成中..." : "AI 草稿"}
                        </button>
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
                  <p className="text-sm text-faint">{workspaceLoading ? "加载中…" : "暂无审阅矩阵。"}</p>
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
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  {selected.analysis?.status === "failed" ? (
                    <p className="text-sm text-[var(--danger)]">
                      上次分析失败{selected.analysis.error ? `：${selected.analysis.error}` : ""}。
                    </p>
                  ) : (
                    <p className="text-sm text-faint">
                      暂无 AI 摘要（请在“设置”中为某个模型分配 LLM 角色）。
                    </p>
                  )}
                  <button onClick={reanalyze} disabled={analyzing} className="btn-ghost px-2.5 py-1 text-xs">
                    {analyzing
                      ? "分析中…"
                        : selected.analysis?.status === "failed"
                          ? (<><RotateCw size={12} /> 重试分析</>)
                          : (<><RotateCw size={12} /> 立即分析</>)}
                  </button>
                </div>
              </div>
            ))}

            {detailTab === "related" && (
            <div className="mt-6 border-t pt-4 border-[var(--border)]">
              <div className="mb-2 flex items-center gap-3">
                <h4 className="font-semibold">相关研究</h4>
                <button onClick={() => findRelated(selected.id)} disabled={relatedLoading} className="btn-ghost">
                  {relatedLoading ? "搜索中…" : "查找相关（库外）"}
                </button>
              </div>
              <p className="mb-2 text-xs text-faint">
                通过 OpenAlex 发现库外研究。网络错误时返回空列表。
              </p>
              {relatedError && !relatedLoading && (
                <p className="text-sm text-[var(--danger)]">
                  发现失败（网络 / API 错误）。请重试。
                </p>
              )}
              {related !== null && related.length === 0 && !relatedLoading && !relatedError && (
                <p className="text-sm text-faint">
                  未找到相关研究。
                </p>
              )}
              {related && related.length > 0 && (
                <ul className="space-y-2">
                  {related.map((r) => (
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
                      <div className="mt-0.5 text-xs text-muted">
                        {r.authors.slice(0, 3).join(", ")}
                        {r.authors.length > 3 ? " 等" : ""} {r.year ? `· ${r.year}` : ""}
                        {r.cited_by_count ? ` · 被引 ${r.cited_by_count}` : ""}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            )}
            </div>
          </div>
        </div>
      )}

      <Drawer
        open={importOpen}
        onClose={() => setImportOpen(false)}
        title="导入论文"
        width="max-w-xl"
      >
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
                通过 PyMuPDF 在本地提取文本。扫描版 / 纯图片 PDF 提取效果有限。
              </p>
              {pdfImportQueue.length > 0 && (
                <div className="space-y-1 text-xs">
                  {pdfImportQueue.map((item) => (
                    <div
                      key={item.id}
                      className="rounded-lg border px-2 py-1.5"
                      style={{ borderColor: "var(--border)", backgroundColor: "var(--surface-2)" }}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="min-w-0 truncate font-medium">{item.name}</span>
                        <span className="chip shrink-0">{PDF_IMPORT_STATUS_LABELS[item.status]}</span>
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
