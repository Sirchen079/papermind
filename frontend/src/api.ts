const BASE = "/api";

async function req<T = any>(path: string, opts?: RequestInit): Promise<T> {
  // Let the browser set the multipart boundary for FormData; force JSON otherwise.
  const isForm = typeof FormData !== "undefined" && opts?.body instanceof FormData;
  const res = await fetch(BASE + path, {
    ...opts,
    headers: {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      ...opts?.headers,
    },
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  if (res.status === 204) return null as T;
  return res.json();
}

export interface SseEvent {
  event: string;
  data: any;
}

/** POST to an SSE endpoint and yield parsed {event, data} frames as they arrive. */
export async function* sseStream(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<SseEvent> {
  const res = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`${res.status} ${await res.text()}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? ""; // keep the trailing partial frame
    for (const frame of frames) {
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) {
        try {
          yield { event, data: JSON.parse(data) };
        } catch {
          /* skip malformed frame */
        }
      }
    }
  }
}

export interface PaperTagRef {
  id: number;
  name: string;
  color: string | null;
}

export interface PaperCollectionRef {
  id: number;
  name: string;
}

export interface UserTag extends PaperTagRef {
  user_created: boolean;
  paper_count: number;
}

export interface UserCollection extends PaperCollectionRef {
  description: string | null;
  paper_count: number;
}

export interface Paper {
  id: number;
  source: string;
  source_ref: string | null;
  citation_key: string | null;
  title: string | null;
  authors: string[];
  abstract: string | null;
  year: number | null;
  venue: string | null;
  doi: string | null;
  arxiv_id: string | null;
  parse_confidence: number | null;
  has_summary?: boolean;
  summary?: Record<string, string> | null;
  full_text?: string | null;
  concepts?: { name: string; type: string | null }[];
  analysis?: { status: string; error: string | null; model: string | null } | null;
  reading?: ReadingStateSummary;
  tags?: PaperTagRef[];
  collections?: PaperCollectionRef[];
}

export interface GraphData {
  nodes: { id: number; title?: string; name?: string; year?: number; type?: string; count?: number }[];
  edges: { source: number; target: number; weight: number; edge_type?: string }[];
}

export interface RelatedPaper {
  title: string | null;
  authors: string[];
  year: number | null;
  doi: string | null;
  cited_by_count: number;
  openalex_id: string | null;
}

export interface Suggestion {
  id: number;
  kind: string;
  title: string;
  detail: Record<string, any>;
  status: "new" | "seen" | "dismissed" | "accepted";
  weight: number;
  created_at: string | null;
  paper?: { id: number; title: string | null } | null;
  related_paper?: { id: number; title: string | null } | null;
}

export interface Provider {
  id: number;
  name: string;
  type: string;
  base_url: string | null;
  enabled: boolean;
}

export interface Model {
  id: number;
  model_id: string;
  display_name: string | null;
  context_window: number | null;
  role_default: string | null;
}

export interface Source {
  paper_id: number;
  title: string;
  snippet: string;
}

export interface ReadingStateSummary {
  status: "unread" | "queued" | "reading" | "read" | "skipped";
  priority: "low" | "normal" | "high";
  rating: number | null;
  relevance: number | null;
}

export interface ReadingState extends ReadingStateSummary {
  id: number | null;
  paper_id: number;
  started_at: string | null;
  finished_at: string | null;
  last_read_at: string | null;
  updated_at: string | null;
}

export interface PaperNote {
  id: number;
  paper_id: number;
  kind: "note" | "question" | "idea" | "critique" | "todo";
  content: string;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface PaperExcerpt {
  id: number;
  paper_id: number;
  quote: string;
  page: number | null;
  section: string | null;
  locator: string | null;
  note: string | null;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface ReviewMatrixEntry {
  id: number | null;
  paper_id: number;
  problem: string | null;
  method: string | null;
  dataset: string | null;
  metrics: string | null;
  results: string | null;
  limitations: string | null;
  novelty: string | null;
  relation_to_thesis: string | null;
  future_work: string | null;
  notes: string | null;
  updated_at: string | null;
}

export interface ReviewMatrixSuggestion {
  configured: boolean;
  model: string | null;
  draft: Record<string, string>;
  error: string | null;
}

export interface ReadingWorkspace {
  state: ReadingState;
  matrix: ReviewMatrixEntry | null;
  notes: PaperNote[];
  excerpts: PaperExcerpt[];
}

export interface MatrixRow {
  paper: { id: number; title: string | null; authors: string[]; year: number | null; venue: string | null };
  state: ReadingStateSummary;
  matrix: ReviewMatrixEntry | null;
}

export interface ReadinessCheck {
  id: string;
  label: string;
  status: "done" | "warning" | "action";
  detail: string;
  action: string;
  route: string;
}

export interface ReadinessReport {
  score: number;
  level: "setup" | "usable" | "ready";
  summary: string;
  stats: {
    papers: number;
    papers_with_text: number;
    summaries: number;
    concepts: number;
    concept_edges: number;
    indexed_chunks: number;
    reading_states: number;
    review_matrices: number;
    projects: number;
    chapters: number;
    paper_links: number;
  };
  capabilities: Record<string, boolean>;
  checks: ReadinessCheck[];
}

export interface LibraryDiagnosticIssue {
  id: string;
  severity: "critical" | "warning";
  label: string;
  detail: string;
  action: string;
  route: string;
}

export interface LibraryDiagnosticPaper {
  paper: {
    id: number;
    title: string | null;
    authors: string[];
    year: number | null;
    venue: string | null;
    source: string;
    citation_key: string | null;
  };
  severity: "critical" | "warning" | "ok";
  issues: LibraryDiagnosticIssue[];
  signals: {
    has_text: boolean;
    has_summary: boolean;
    has_concepts: boolean;
    indexed: boolean;
    parse_confidence: number | null;
    analysis_status: string | null;
  };
}

export interface LibraryDiagnosticsReport {
  summary: {
    total: number;
    healthy: number;
    warning: number;
    critical: number;
    needs_action: number;
  };
  issue_counts: Record<string, number>;
  papers: LibraryDiagnosticPaper[];
}

export interface LibraryDiagnosticsRepairResult {
  action: "citation_keys" | "reanalyze";
  configured: boolean;
  processed: number;
  changed: number;
  failed: { paper_id: number; title: string | null; error: string | null }[];
  error: string | null;
}

export interface ResearchProgressAction {
  id: string;
  label: string;
  detail: string;
  route: string;
  priority: "high" | "normal" | "low";
}

export interface ResearchProgressReport {
  reading: {
    total_papers: number;
    status_counts: Record<"unread" | "queued" | "reading" | "read" | "skipped", number>;
    high_priority: number;
    high_relevance: number;
    review_matrices: number;
    read_without_matrix: number;
  };
  writing: {
    projects: number;
    chapters: number;
    linked_papers: number;
    read_unlinked_papers: number;
    draft_chapters: number;
    review_chapters: number;
    done_chapters: number;
  };
  quality: {
    total: number;
    healthy: number;
    warning: number;
    critical: number;
    needs_action: number;
  };
  actions: ResearchProgressAction[];
}

export interface ThesisProject {
  id: number;
  parent_project_id: number | null;
  kind: string;
  name: string;
  description: string | null;
  status: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
  children: ThesisProject[];
  chapters: ThesisChapter[];
}

export interface ThesisChapter {
  id: number;
  project_id: number;
  parent_chapter_id: number | null;
  title: string;
  outline: string | null;
  sort_order: number;
  status: string;
  created_at: string;
  updated_at: string;
  children: ThesisChapter[];
}

export interface ThesisPaperLink {
  id: number;
  paper_id: number;
  project_id: number | null;
  chapter_id: number | null;
  role: string;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface ThesisPaper {
  id: number;
  title: string | null;
  year: number | null;
  authors: string[];
  links: ThesisPaperLink[];
}

export interface ThesisWorkspace {
  projects: ThesisProject[];
  papers: ThesisPaper[];
}

export interface BackupInfo {
  filename: string;
  size_bytes: number;
  modified_at: string;
  manifest?: Record<string, any> | null;
  error?: string | null;
}

export interface BackupVerification {
  ok: boolean;
  filename: string;
  archive_type: string | null;
  database: {
    present: boolean;
    sha256_ok: boolean;
    integrity_ok: boolean;
  };
  master_key: {
    present: boolean;
    expected: boolean;
    sha256_ok: boolean;
  };
  pdfs: {
    expected_count: number;
    verified_count: number;
    missing_count: number;
    failed_count: number;
  };
  errors: string[];
}

export interface BackupRestoreGuide {
  filename: string;
  can_restore: boolean;
  summary: string;
  paths: {
    backup_path: string;
    data_dir: string;
    database_path: string;
    master_key_path: string;
    pdf_dir: string;
  };
  warnings: string[];
  steps: { title: string; detail: string }[];
  verification: BackupVerification;
}

export interface ArchiveStatus {
  data_dir: string;
  database_path: string;
  database_exists: boolean;
  database_size_bytes: number;
  master_key_exists: boolean;
  pdf_dir: string;
  pdf_dir_exists: boolean;
  pdf_count: number;
  pdf_total_bytes: number;
  paper_count: number;
  summary_count: number;
  concept_count: number;
  chunk_count: number;
  provider_count: number;
  latest_backup: BackupInfo | null;
}

export const api = {
  // papers
  listPapers: () => req<Paper[]>("/papers"),
  getPaper: (id: number) => req<Paper>(`/papers/${id}`),
  patchPaper: (id: number, body: Record<string, unknown>) =>
    req<Paper>(`/papers/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deletePaper: (id: number) => req(`/papers/${id}`, { method: "DELETE" }),
  reanalyzePaper: (id: number) =>
    req<{ id: number; summary: Record<string, string> | null; concepts: { name: string; type: string | null }[] }>(
      `/papers/${id}/analyze`,
      { method: "POST" },
    ),
  relatedPapers: (id: number) => req<RelatedPaper[]>(`/papers/${id}/related`),
  readiness: () => req<ReadinessReport>("/readiness"),
  researchProgress: () => req<ResearchProgressReport>("/research/progress"),
  libraryDiagnostics: () => req<LibraryDiagnosticsReport>("/library/diagnostics"),
  repairLibraryDiagnostics: (action: "citation_keys" | "reanalyze") =>
    req<LibraryDiagnosticsRepairResult>("/library/diagnostics/repair", {
      method: "POST",
      body: JSON.stringify({ action }),
    }),
  getReadingWorkspace: (id: number) => req<ReadingWorkspace>(`/papers/${id}/reading`),
  patchReadingState: (id: number, body: Record<string, unknown>) =>
    req<ReadingState>(`/papers/${id}/reading/state`, { method: "PATCH", body: JSON.stringify(body) }),
  saveReviewMatrix: (id: number, body: Record<string, unknown>) =>
    req<ReviewMatrixEntry>(`/papers/${id}/reading/matrix`, { method: "PUT", body: JSON.stringify(body) }),
  suggestReviewMatrix: (id: number) =>
    req<ReviewMatrixSuggestion>(`/papers/${id}/reading/matrix/suggest`, { method: "POST" }),
  createNote: (id: number, body: Record<string, unknown>) =>
    req<PaperNote>(`/papers/${id}/reading/notes`, { method: "POST", body: JSON.stringify(body) }),
  patchNote: (id: number, noteId: number, body: Record<string, unknown>) =>
    req<PaperNote>(`/papers/${id}/reading/notes/${noteId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteNote: (id: number, noteId: number) => req(`/papers/${id}/reading/notes/${noteId}`, { method: "DELETE" }),
  createExcerpt: (id: number, body: Record<string, unknown>) =>
    req<PaperExcerpt>(`/papers/${id}/reading/excerpts`, { method: "POST", body: JSON.stringify(body) }),
  patchExcerpt: (id: number, excerptId: number, body: Record<string, unknown>) =>
    req<PaperExcerpt>(`/papers/${id}/reading/excerpts/${excerptId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteExcerpt: (id: number, excerptId: number) =>
    req(`/papers/${id}/reading/excerpts/${excerptId}`, { method: "DELETE" }),
  thesisWorkspace: () => req<ThesisWorkspace>("/thesis/workspace"),
  createThesisProject: (body: Record<string, unknown>) =>
    req<ThesisProject>("/thesis/projects", { method: "POST", body: JSON.stringify(body) }),
  patchThesisProject: (id: number, body: Record<string, unknown>) =>
    req<ThesisProject>(`/thesis/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteThesisProject: (id: number) => req(`/thesis/projects/${id}`, { method: "DELETE" }),
  createThesisChapter: (projectId: number, body: Record<string, unknown>) =>
    req<ThesisChapter>(`/thesis/projects/${projectId}/chapters`, { method: "POST", body: JSON.stringify(body) }),
  patchThesisChapter: (id: number, body: Record<string, unknown>) =>
    req<ThesisChapter>(`/thesis/chapters/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteThesisChapter: (id: number) => req(`/thesis/chapters/${id}`, { method: "DELETE" }),
  linkThesisPaper: (paperId: number, body: Record<string, unknown>) =>
    req<ThesisPaperLink>(`/papers/${paperId}/thesis-links`, { method: "POST", body: JSON.stringify(body) }),
  patchThesisLink: (paperId: number, linkId: number, body: Record<string, unknown>) =>
    req<ThesisPaperLink>(`/papers/${paperId}/thesis-links/${linkId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteThesisLink: (paperId: number, linkId: number) =>
    req(`/papers/${paperId}/thesis-links/${linkId}`, { method: "DELETE" }),
  exportThesisMarkdownUrl: (target: { project_id?: number; chapter_id?: number }) => {
    const qs = new URLSearchParams();
    if (target.project_id != null) qs.set("project_id", String(target.project_id));
    if (target.chapter_id != null) qs.set("chapter_id", String(target.chapter_id));
    return `${BASE}/thesis/export/markdown?${qs.toString()}`;
  },
  reviewMatrix: (params?: { status?: string; q?: string; min_relevance?: number; high_priority?: boolean }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.q) qs.set("q", params.q);
    if (params?.min_relevance) qs.set("min_relevance", String(params.min_relevance));
    if (params?.high_priority) qs.set("high_priority", "true");
    return req<MatrixRow[]>(`/reading/matrix${qs.size ? `?${qs.toString()}` : ""}`);
  },
  listTags: () => req<UserTag[]>("/tags"),
  createTag: (body: { name: string; color: string | null }) =>
    req<UserTag>("/tags", { method: "POST", body: JSON.stringify(body) }),
  deleteTag: (id: number) => req(`/tags/${id}`, { method: "DELETE" }),
  attachTag: (paperId: number, tagId: number) =>
    req<UserTag>(`/papers/${paperId}/tags/${tagId}`, { method: "POST" }),
  removeTag: (paperId: number, tagId: number) =>
    req(`/papers/${paperId}/tags/${tagId}`, { method: "DELETE" }),
  listCollections: () => req<UserCollection[]>("/collections"),
  createCollection: (body: { name: string; description: string | null }) =>
    req<UserCollection>("/collections", { method: "POST", body: JSON.stringify(body) }),
  deleteCollection: (id: number) => req(`/collections/${id}`, { method: "DELETE" }),
  addPaperToCollection: (collectionId: number, paperId: number) =>
    req<UserCollection>(`/collections/${collectionId}/papers/${paperId}`, { method: "POST" }),
  removePaperFromCollection: (collectionId: number, paperId: number) =>
    req(`/collections/${collectionId}/papers/${paperId}`, { method: "DELETE" }),
  reindexLibrary: () =>
    req<{
      configured: boolean;
      papers: number;
      indexed_papers: number;
      chunks: number;
      skipped_no_text: number;
      error: string | null;
    }>("/papers/reindex", { method: "POST" }),
  createManualPaper: (body: Record<string, unknown>) =>
    req<Paper>("/papers/manual", { method: "POST", body: JSON.stringify(body) }),
  ingestPdf: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return req<Paper>("/papers/pdf", { method: "POST", body: form });
  },
  ingestBibtex: (bibtex: string) =>
    req<Paper[]>("/papers/bibtex", { method: "POST", body: JSON.stringify({ bibtex }) }),
  ingestRis: (ris: string) =>
    req<Paper[]>("/papers/ris", { method: "POST", body: JSON.stringify({ ris }) }),
  ingestArxiv: (arxiv_id: string) =>
    req<Paper>("/papers/arxiv", { method: "POST", body: JSON.stringify({ arxiv_id }) }),
  // graph
  graph: (kind: "paper" | "concept", minPapers = 1) =>
    req<GraphData>(`/graph/${kind}?min_papers=${minPapers}`),
  // chat
  listConversations: () => req<{ id: number; title: string }[]>("/chat/conversations"),
  createConversation: () => req<{ id: number; title: string }>("/chat/conversations", { method: "POST" }),
  renameConversation: (id: number, title: string) =>
    req<{ id: number; title: string }>(`/chat/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteConversation: (id: number) => req(`/chat/conversations/${id}`, { method: "DELETE" }),
  getConversation: (id: number) =>
    req<{
      id: number;
      title: string;
      messages: { role: string; content: string; model: string; sources: Source[] }[];
    }>(`/chat/conversations/${id}`),
  sendMessage: (id: number, content: string) =>
    req<{ role: string; content: string; model: string; tokens: number }>(
      `/chat/conversations/${id}/messages`,
      { method: "POST", body: JSON.stringify({ content }) }
    ),
  streamMessage: (id: number, content: string, signal?: AbortSignal) =>
    sseStream(`/chat/conversations/${id}/messages/stream`, { content }, signal),
  // providers / models
  listProviders: () => req<Provider[]>("/providers"),
  createProvider: (body: Record<string, unknown>) =>
    req<Provider>("/providers", { method: "POST", body: JSON.stringify(body) }),
  patchProvider: (id: number, body: Record<string, unknown>) =>
    req<Provider>(`/providers/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteProvider: (id: number) => req(`/providers/${id}`, { method: "DELETE" }),
  refreshModels: (id: number) => req<{ count: number }>(`/providers/${id}/models/refresh`, { method: "POST" }),
  addModel: (pid: number, body: { model_id: string; display_name?: string; role_default?: string }) =>
    req<Model>(`/providers/${pid}/models`, { method: "POST", body: JSON.stringify(body) }),
  providerModels: (id: number) => req<Model[]>(`/providers/${id}/models`),
  setModelRole: (id: number, role_default: string) =>
    req(`/models/${id}`, { method: "PATCH", body: JSON.stringify({ role_default }) }),
  // usage
  usage: (days = 30) =>
    req<{
      total_tokens: number;
      by_kind: Record<string, number>;
      by_model: Record<string, number>;
      by_day: { day: string; tokens: number }[];
    }>(
      `/usage?days=${days}`
    ),
  // archive / export
  archiveStatus: () => req<ArchiveStatus>("/archive/status"),
  createBackup: () => req<BackupInfo>("/archive/backup", { method: "POST" }),
  listBackups: () => req<BackupInfo[]>("/archive/backups"),
  verifyBackup: (filename: string) =>
    req<BackupVerification>(`/archive/backups/${encodeURIComponent(filename)}/verify`, { method: "POST" }),
  restoreGuide: (filename: string) =>
    req<BackupRestoreGuide>(`/archive/backups/${encodeURIComponent(filename)}/restore-guide`),
  downloadBackupUrl: (filename: string) => `${BASE}/archive/backups/${encodeURIComponent(filename)}`,
  exportJsonUrl: () => `${BASE}/archive/export/json`,
  exportBibtexUrl: () => `${BASE}/archive/export/bibtex`,
  exportRisUrl: () => `${BASE}/archive/export/ris`,
  // skills
  listSkills: () =>
    req<
      {
        id: number;
        name: string;
        type: string;
        trigger: string;
        keywords: string[];
        description: string | null;
        body: string | null;
        enabled: boolean;
        source: string;
      }[]
    >("/skills"),
  upsertSkill: (body: Record<string, unknown>) =>
    req("/skills", { method: "POST", body: JSON.stringify(body) }),
  deleteSkill: (id: number) => req(`/skills/${id}`, { method: "DELETE" }),
  reloadSkills: () => req<{ loaded: number }>("/skills/reload", { method: "POST" }),
  runSkill: (id: number, input = "") =>
    req<{ ok: boolean; stdout: string; stderr: string; exit_code: number; duration_ms: number }>(
      `/skills/${id}/run`,
      { method: "POST", body: JSON.stringify({ input }) },
    ),
  // suggestions
  listSuggestions: (status?: string) =>
    req<Suggestion[]>(`/suggestions${status ? `?status=${status}` : ""}`),
  patchSuggestion: (id: number, status: string) =>
    req<Suggestion>(`/suggestions/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  generateSuggestions: () => req<{ created: number }>("/suggestions/generate", { method: "POST" }),
};
