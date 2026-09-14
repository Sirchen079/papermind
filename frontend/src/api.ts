import { parseApiErrorMessage } from "./pages/apiErrorModel";

const BASE = "/api";

/**
 * 读取后端注入到首页 HTML 的本机令牌（<meta name="papermind-local-token">）。
 * 缺失时返回空串：开发模式下页面由 Vite dev server 提供，后端中间件不注入该
 * meta，此时请求不带 X-Local-Token 头、后端返回 403，走现有错误提示，可接受。
 */
export function localToken(): string {
  return document.querySelector('meta[name="papermind-local-token"]')?.getAttribute("content") ?? "";
}

export interface CacheSummary {
  calls: number;
  reported_calls: number;
  unknown_calls: number;
  invalid_usage_calls: number;
  reported_input_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  input_token_hit_rate: number | null;
  reporting_coverage: number | null;
  target: number;
  target_met: boolean | null;
}

export interface ClarificationResponse {
  message_id: number;
  answers?: Record<string, string>;
  free_text?: string;
  skipped?: boolean;
}
export interface Clarification {
  message_id: number;
  reason: string;
  questions: { id: string; question: string; options: string[] }[];
  status: "pending" | "answered" | "skipped";
  response?: Omit<ClarificationResponse, "message_id">;
}
export interface ChatMessageExtra {
  paper_id?: number;
  selected_text?: string;
  skill_ids?: number[];
  retry_message_id?: number;
  clarification_response?: ClarificationResponse;
}
export interface CacheDiagnostics extends CacheSummary {
  excluded_non_llm_calls: number;
  by_provider_model_kind: (CacheSummary & { provider_id: number; model: string; request_kind: string })[];
}

async function request<T = any>(BASE: string, path: string, opts?: RequestInit): Promise<T> {
  // Let the browser set the multipart boundary for FormData; force JSON otherwise.
  const isForm = typeof FormData !== "undefined" && opts?.body instanceof FormData;
  const res = await fetch(BASE + path, {
    ...opts,
    headers: {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      ...opts?.headers,
    },
  });
  if (!res.ok) throw new Error(parseApiErrorMessage(res.status, await res.text()));
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
  base: string = BASE,
): AsyncGenerator<SseEvent> {
  const res = await fetch(base + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(parseApiErrorMessage(res.status, await res.text()));
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
  created_at?: string | null;
  has_pdf?: boolean;
  has_summary?: boolean;
  summary?: Record<string, string> | null;
  full_text?: string | null;
  concepts?: { name: string; type: string | null }[];
  analysis?: { status: string; error: string | null; model: string | null } | null;
  reading?: ReadingStateSummary;
  tags?: PaperTagRef[];
  collections?: PaperCollectionRef[];
  copied_from?: { source_name:string; source_paper_id:number; created_at:string; include_notes:boolean } | null;
}

export interface PaperListResponse {
  items: Paper[];
  total: number;
  limit: number;
  offset: number;
}

export interface RecentlyReadPaper {
  id: number;
  title: string | null;
  authors: string[];
  year: number | null;
  venue: string | null;
  status: string;
  last_read_at: string | null;
  last_page: number | null;
}

export interface GraphData {
  nodes: {
    id: number;
    title?: string;
    name?: string;
    label?: string;
    year?: number;
    type?: string;
    count?: number;
    paper_id?: number;
    text?: string;
    paper_title?: string;
    kind?: string;
    source?: string;
  }[];
  edges: { source: number; target: number; weight: number; edge_type?: string; note?: string | null }[];
}

// P12 论断（Claim-Evidence 图谱）
export interface PaperClaim {
  id: number;
  paper_id: number;
  text: string;
  kind: "main" | "supporting";
  source: "ai" | "user";
  excerpt_id: number | null;
  created_at: string | null;
}

export interface PaperCitationEntry {
  id: number;
  raw_ref: string;
  ref_title: string | null;
  ref_doi: string | null;
  ref_arxiv_id: string | null;
  ref_year: number | null;
  ref_authors: string[];
  match_status: "unmatched" | "matched";
  match_confidence: number | null;
  target_paper_id?: number | null;
  target_title?: string | null;
  source_paper_id?: number | null;
  source_title?: string | null;
}

export interface PaperCitations {
  outgoing: PaperCitationEntry[];
  incoming: PaperCitationEntry[];
}

export interface IdeaPaperRef {
  paper_id: number;
  title: string | null;
  role: string;
  note: string | null;
}

export interface Idea {
  id: number;
  title: string;
  content: string;
  hypothesis: string | null;
  status: "proposed" | "refining" | "testing" | "adopted" | "dropped";
  priority: "low" | "normal" | "high";
  origin: "manual" | "matrix" | "suggestion" | "gap";
  project_id: number | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  papers: IdeaPaperRef[];
}

export interface ResearchGap {
  type: string;
  title: string;
  paper_ids: number[];
  rationale: string;
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

export interface ChapterDraft {
  id: number;
  chapter_id: number;
  content: string;
  model: string | null;
  created_at: string | null;
}

export interface Subscription {
  id: number;
  name: string;
  query_type: "keyword" | "category" | "author";
  query_value: string;
  max_results: number;
  lookback_days: number;
  enabled: boolean;
  last_run_at: string | null;
  created_at: string | null;
}

export interface RadarStatus {
  total: number;
  enabled: number;
  due: number;
  last_run_at: string | null;
}

export interface RadarRefreshResult {
  ran: number;
  created: number;
  results: { subscription_id: number; name: string; status: string; new_entries: number; error: string | null }[];
  ran_at: string;
}


export interface Provider {
  id: number;
  name: string;
  type: string;
  base_url: string | null;
  enabled: boolean;
  shared_connection_id?: string | null;
  shared_unavailable?: boolean;
}

export interface SharedConnection {
  id:string; name:string; type:string; base_url:string|null; enabled:boolean; version:number; updated_at:string;
  models:{model_id:string;display_name:string|null;context_window:number|null;role_default:string|null}[];
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

export interface TopicSource {
  source_type: 'topic_wiki';
  workspace_id: string;
  workspace_name: string;
  page_id: string;
  revision: number;
  title: string;
  url: string;
  snippet: string;
  support_status: string;
  review_note: string;
  source_changes: string[];
  evidence: { ref: string; title: string; quote: string; locator: string }[];
  retrieved_by: string;
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
  last_page: number | null;
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

// P13 实验记录
export interface ExperimentPaperRef {
  paper_id: number;
  title: string | null;
  role: "baseline" | "method" | "dataset";
  note: string | null;
}

export interface Experiment {
  id: number;
  project_id: number;
  idea_id: number | null;
  name: string;
  hypothesis: string | null;
  status: "planned" | "running" | "analyzing" | "done" | "abandoned";
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
  log_count: number;
  papers: ExperimentPaperRef[];
}

export interface ExperimentLog {
  id: number;
  experiment_id: number;
  content: string;
  created_at: string;
}

export interface Report {
  id: number;
  since: string;
  until: string;
  content: string;
  model: string | null;
  created_at: string | null;
}

// P14 周报聚合（确定性）
export interface WeeklyAggregate {
  since: string;
  until: string;
  papers_new: { count: number; items: { id: number; title: string | null }[] };
  papers_read: { count: number };
  notes_new: { count: number };
  excerpts_new: { count: number };
  ideas: {
    created: { count: number; items: { id: number; title: string; status: string }[] };
    updated: { count: number; by_status: Record<string, number> };
    closed: { count: number };
  };
  experiments: {
    created: { count: number; items: { id: number; name: string; status: string }[] };
    logs_added: { count: number };
    finished: { count: number };
    status_counts: Record<string, number>;
  };
  radar_high: { count: number; items: { title: string }[] };
  suggestions_ai: { count: number; by_kind: Record<string, number> };
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

export function createApi(BASE: string = '/api') {
const req = <T = any>(path: string, opts?: RequestInit) => request<T>(BASE, path, opts);
return {
  // papers
  listPapers: (limit?: number, offset?: number, q?: string) => {
    const params = new URLSearchParams();
    if (limit != null) params.set("limit", String(limit));
    if (offset != null) params.set("offset", String(offset));
    if (q && q.trim()) params.set("q", q.trim());
    const qs = params.toString();
    return req<PaperListResponse>(qs ? `/papers?${qs}` : "/papers");
  },
  getPaper: (id: number) => req<Paper>(`/papers/${id}`),
  patchPaper: (id: number, body: Record<string, unknown>) =>
    req<Paper>(`/papers/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deletePaper: (id: number) => req(`/papers/${id}`, { method: "DELETE" }),
  copyPaperToWorkspace: (id:number,body:{target_workspace:string;request_id:string;include_notes:boolean}) =>
    req<{paper_id:number;reused:boolean}>(`/papers/${id}/copy-to-workspace`,{method:'POST',body:JSON.stringify(body)}),
  reanalyzePaper: (id: number) =>
    req<{ id: number; summary: Record<string, string> | null; concepts: { name: string; type: string | null }[] }>(
      `/papers/${id}/analyze`,
      { method: "POST" },
    ),
  relatedPapers: (id: number) => req<RelatedPaper[]>(`/papers/${id}/related`),
  paperCitations: (id: number) => req<PaperCitations>(`/papers/${id}/citations`),
  // reading — 研究主页「继续阅读」
  recentlyRead: (limit?: number) => {
    const params = new URLSearchParams();
    if (limit != null) params.set("limit", String(limit));
    const qs = params.toString();
    return req<RecentlyReadPaper[]>(qs ? `/reading/recently-read?${qs}` : "/reading/recently-read");
  },
  // ideas
  listIdeas: (params?: { status?: string; priority?: string; project_id?: number }) => {
    const search = new URLSearchParams();
    if (params?.status) search.set("status", params.status);
    if (params?.priority) search.set("priority", params.priority);
    if (params?.project_id != null) search.set("project_id", String(params.project_id));
    const qs = search.toString();
    return req<Idea[]>(qs ? `/ideas?${qs}` : "/ideas");
  },
  createIdea: (body: Record<string, unknown>) =>
    req<Idea>("/ideas", { method: "POST", body: JSON.stringify(body) }),
  getIdea: (id: number) => req<Idea>(`/ideas/${id}`),
  patchIdea: (id: number, body: Record<string, unknown>) =>
    req<Idea>(`/ideas/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteIdea: (id: number) => req(`/ideas/${id}`, { method: "DELETE" }),
  linkIdeaPaper: (ideaId: number, paperId: number, role: string) =>
    req<{ idea_id: number; paper_id: number; role: string }>(`/ideas/${ideaId}/papers`, {
      method: "POST",
      body: JSON.stringify({ paper_id: paperId, role }),
    }),
  unlinkIdeaPaper: (ideaId: number, paperId: number, role: string) =>
    req(`/ideas/${ideaId}/papers/${paperId}/${role}`, { method: "DELETE" }),
  researchGaps: () => req<ResearchGap[]>("/research-gaps"),
  // P13 实验
  listExperiments: (params?: {
    status?: string;
    project_id?: number;
    idea_id?: number;
    include_hidden?: boolean;
  }) => {
    const search = new URLSearchParams();
    if (params?.status) search.set("status", params.status);
    if (params?.project_id != null) search.set("project_id", String(params.project_id));
    if (params?.idea_id != null) search.set("idea_id", String(params.idea_id));
    if (params?.include_hidden) search.set("include_hidden", "true");
    const qs = search.toString();
    return req<Experiment[]>(qs ? `/experiments?${qs}` : "/experiments");
  },
  createExperiment: (body: Record<string, unknown>) =>
    req<Experiment>("/experiments", { method: "POST", body: JSON.stringify(body) }),
  getExperiment: (id: number) => req<Experiment>(`/experiments/${id}`),
  patchExperiment: (id: number, body: Record<string, unknown>) =>
    req<Experiment>(`/experiments/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteExperiment: (id: number) => req(`/experiments/${id}`, { method: "DELETE" }),
  addExperimentLog: (id: number, content: string) =>
    req<ExperimentLog>(`/experiments/${id}/logs`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  listExperimentLogs: (id: number) => req<ExperimentLog[]>(`/experiments/${id}/logs`),
  deleteExperimentLog: (id: number, logId: number) =>
    req(`/experiments/${id}/logs/${logId}`, { method: "DELETE" }),
  linkExperimentPaper: (id: number, paperId: number, role: string) =>
    req<{ experiment_id: number; paper_id: number; role: string }>(`/experiments/${id}/papers`, {
      method: "POST",
      body: JSON.stringify({ paper_id: paperId, role }),
    }),
  unlinkExperimentPaper: (id: number, paperId: number, role: string) =>
    req(`/experiments/${id}/papers/${paperId}/${role}`, { method: "DELETE" }),
  // P14 组会汇报
  weeklyAggregate: (since?: string, until?: string) => {
    const search = new URLSearchParams();
    if (since) search.set("since", since);
    if (until) search.set("until", until);
    const qs = search.toString();
    return req<WeeklyAggregate>(qs ? `/reports/weekly?${qs}` : "/reports/weekly");
  },
  generateWeeklyReport: (body: { since?: string; until?: string; problems?: string }) =>
    req<Report>("/reports/weekly/generate", { method: "POST", body: JSON.stringify(body) }),
  listReports: () => req<Report[]>("/reports"),
  getReport: (id: number) => req<Report>(`/reports/${id}`),
  reportMarkdownUrl: (id: number) => `${BASE}/reports/${id}/markdown`,
  reportPptxUrl: (id: number) => `${BASE}/reports/${id}/pptx`,
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
  // P10.5 章节草稿生成
  generateChapterDraft: (chapterId: number) =>
    req<ChapterDraft>(`/thesis/chapters/${chapterId}/draft`, { method: "POST" }),
  listChapterDrafts: (chapterId: number) =>
    req<ChapterDraft[]>(`/thesis/chapters/${chapterId}/drafts`),
  // T8 单个草稿版本的 Markdown 下载（Content-Disposition 带 Unicode 文件名）。
  chapterDraftMarkdownUrl: (chapterId: number, draftId: number) =>
    `${BASE}/thesis/chapters/${chapterId}/drafts/${draftId}/markdown`,
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
  // P10.6 章节/项目级 .bib 导出
  thesisBibtexUrl: (target: { project_id?: number; chapter_id?: number }) =>
    target.chapter_id != null
      ? `${BASE}/thesis/chapters/${target.chapter_id}/bibtex`
      : `${BASE}/thesis/projects/${target.project_id}/bibtex`,
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
  // T10：库外发现一键加入待读（幂等；重复论文返回已有论文并置为待读）。
  addExternalPaper: (body: Record<string, unknown>) =>
    req<{ paper: Paper; created: boolean }>("/papers/from-external", {
      method: "POST",
      body: JSON.stringify(body),
    }),
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
  graph: (kind: "paper" | "concept" | "claims", minPapers = 1, edgeTypes?: string[], claimTypes?: string[]) => {
    const params = new URLSearchParams({ min_papers: String(minPapers) });
    if (kind === "paper" && edgeTypes && edgeTypes.length > 0) {
      params.set("edge_types", edgeTypes.join(","));
    }
    if (kind === "claims" && claimTypes && claimTypes.length > 0) {
      params.set("types", claimTypes.join(","));
    }
    return req<GraphData>(`/graph/${kind}?${params.toString()}`);
  },
  // claims（P12 论断）
  listPaperClaims: (id: number) => req<PaperClaim[]>(`/papers/${id}/claims`),
  createClaim: (id: number, body: { text: string; kind?: string; excerpt_id?: number | null }) =>
    req<PaperClaim>(`/papers/${id}/claims`, { method: "POST", body: JSON.stringify(body) }),
  deleteClaim: (claimId: number) => req(`/claims/${claimId}`, { method: "DELETE" }),
  // chat
  listConversations: () => req<{ id: number; title: string }[]>("/chat/conversations"),
  createConversation: (paperId?: number) => req<{ id: number; title: string }>("/chat/conversations", { method: "POST", body: JSON.stringify({ paper_id: paperId }) }),
  clearConversationPaper: (id: number) => req(`/chat/conversations/${id}`, { method: "PATCH", body: JSON.stringify({ paper_id: null }) }),
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
      messages: { id: number; role: string; content: string; model: string; sources: Source[]; topic_sources?: TopicSource[]; delivery_status?: string; error_message?: string | null; retryable?: boolean; clarification?: Clarification | null }[];
      paper_id: number | null;
      paper_title: string | null;
    }>(`/chat/conversations/${id}`),
  sendMessage: (id: number, content: string, extra?: ChatMessageExtra) =>
    req<{ role: string; content: string; model: string; tokens: number; sources: Source[]; topic_sources: TopicSource[]; clarification?: Clarification }>(
      `/chat/conversations/${id}/messages`,
      { method: "POST", body: JSON.stringify({ content, ...extra }) }
    ),
  streamMessage: (
    id: number,
    content: string,
    signal?: AbortSignal,
    extra?: ChatMessageExtra,
  ) => sseStream(`/chat/conversations/${id}/messages/stream`, { content, ...extra }, signal, BASE),
  // providers / models
  listProviders: () => req<Provider[]>("/providers"),
  sharedConnections: () => req<SharedConnection[]>('/shared-connections'),
  shareProvider: (id:number) => req<SharedConnection>(`/providers/${id}/share`,{method:'POST'}),
  attachConnection: (connection_id:string) => req<Provider>('/providers/attach',{method:'POST',body:JSON.stringify({connection_id})}),
  detachConnection: (id:number) => req<Provider>(`/providers/${id}/detach`,{method:'POST'}),
  updateSharedConnection: (id:string,body:Record<string,unknown>) => req<SharedConnection>(`/shared-connections/${id}`,{method:'PATCH',body:JSON.stringify(body)}),
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
      input_tokens: number;
      cached_input_tokens: number;
      cache_write_tokens: number;
      cache_reported_calls: number;
      cache_reported_input_tokens: number;
      cache_diagnostics?: CacheDiagnostics;
      call_count: number;
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
  // 带 X-Local-Token 下载备份压缩包（该端点要求本机令牌，不能用 <a href> 直链）。
  downloadBackup: async (filename: string): Promise<void> => {
    const res = await fetch(`${BASE}/archive/backups/${encodeURIComponent(filename)}`, {
      headers: { "X-Local-Token": localToken() },
    });
    if (!res.ok) throw new Error(parseApiErrorMessage(res.status, await res.text()));
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
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
      {
        method: "POST",
        body: JSON.stringify({ input }),
        // 运行技能属本机高危操作，后端要求 X-Local-Token；req 会合并额外 headers。
        headers: { "X-Local-Token": localToken() },
      },
    ),
  // suggestions
  listSuggestions: (status?: string) =>
    req<Suggestion[]>(`/suggestions${status ? `?status=${status}` : ""}`),
  patchSuggestion: (id: number, status: string) =>
    req<Suggestion>(`/suggestions/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  generateSuggestions: () => req<{ created: number }>("/suggestions/generate", { method: "POST" }),
  // radar subscriptions（文献雷达）
  listSubscriptions: () => req<Subscription[]>("/subscriptions"),
  createSubscription: (body: Record<string, unknown>) =>
    req<Subscription>("/subscriptions", { method: "POST", body: JSON.stringify(body) }),
  patchSubscription: (id: number, body: Record<string, unknown>) =>
    req<Subscription>(`/subscriptions/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteSubscription: (id: number) => req(`/subscriptions/${id}`, { method: "DELETE" }),
  radarStatus: () => req<RadarStatus>("/radar/status"),
  radarRefresh: () => req<RadarRefreshResult>("/radar/refresh", { method: "POST" }),
  // settings（通用 KV 设置，如 research_interests 研究方向描述）
  listSettings: () => req<Record<string, string | null>>("/settings"),
  putSetting: (key: string, value: string) =>
    req<{ key: string; value: string | null }>(`/settings/${key}`, {
      method: "PUT",
      body: JSON.stringify({ value }),
    }),
};
}
