// 顶层页面 + Library 内层状态的 hash 深链模型。
// hash 形如 `#library?view=matrix`：路径段是顶层页面，查询段是深链参数。
// 后端 readiness/research_progress 的 route 契约保持 `route="library"` 等页面级
// 字符串；具体落点（导入抽屉、审阅矩阵、阅读队列……）由这里的 ID 映射承担。

export interface NavLocation {
  page: string;
  params: Record<string, string>;
}

export const DEFAULT_PAGE = "home";

// 与 App.tsx 的导航保持一致的顶层页面集合。
export const KNOWN_PAGES: readonly string[] = [
  "home",
  "research",
  "wiki",
  "library",
  "suggestions",
  "ideas",
  "graph",
  "chat",
  "skills",
  "settings",
  "help",
];

export type LibraryViewKey = "library" | "matrix" | "thesis";
export type ImportTabKey = "manual" | "bibtex" | "ris" | "arxiv" | "pdf";
export type ReadingStatusKey = "all" | "unread" | "queued" | "reading" | "read" | "skipped";

export interface LibraryDeepLink {
  view: LibraryViewKey;
  importOpen: boolean;
  importTab: ImportTabKey;
  readingStatus: ReadingStatusKey;
}

const LIBRARY_VIEWS: readonly LibraryViewKey[] = ["library", "matrix", "thesis"];
const IMPORT_TABS: readonly ImportTabKey[] = ["manual", "bibtex", "ris", "arxiv", "pdf"];
const READING_STATUSES: readonly ReadingStatusKey[] = [
  "all",
  "unread",
  "queued",
  "reading",
  "read",
  "skipped",
];

function oneOf<T extends string>(values: readonly T[], raw: unknown, fallback: T): T {
  return typeof raw === "string" && (values as readonly string[]).includes(raw) ? (raw as T) : fallback;
}

export function normalizePage(raw: string | null | undefined): string {
  return typeof raw === "string" && KNOWN_PAGES.includes(raw) ? raw : DEFAULT_PAGE;
}

export function parseHash(hash: string): NavLocation {
  const raw = (hash ?? "").replace(/^#/, "");
  const [rawPage, rawQuery] = raw.split("?");
  const page = normalizePage(rawPage);
  const params: Record<string, string> = {};
  if (rawQuery) {
    for (const [key, value] of new URLSearchParams(rawQuery).entries()) {
      if (key) params[key] = value;
    }
  }
  return { page, params };
}

// 参数按键排序，保证 buildHash 的输出是规范形式，sameLocation 可直接比较。
export function buildHash(location: NavLocation): string {
  const page = normalizePage(location.page);
  const keys = Object.keys(location.params)
    .filter((key) => key && location.params[key] !== "")
    .sort();
  if (keys.length === 0) return page === DEFAULT_PAGE ? "" : `#${page}`;
  const query = keys.map((key) => `${encodeURIComponent(key)}=${encodeURIComponent(location.params[key])}`).join("&");
  return `#${page}?${query}`;
}

export function sameLocation(a: NavLocation, b: NavLocation): boolean {
  return buildHash(a) === buildHash(b);
}

export function libraryDeepLinkFromParams(params: Record<string, string>): LibraryDeepLink {
  return {
    view: oneOf(LIBRARY_VIEWS, params.view, "library"),
    importOpen: IMPORT_TABS.includes(params.import as ImportTabKey),
    importTab: oneOf(IMPORT_TABS, params.import, "manual"),
    readingStatus: oneOf(READING_STATUSES, params.status, "all"),
  };
}

// 默认状态输出空参数，保证默认 hash 保持 ""，避免无意义的 hash 抖动。
export function libraryParamsFromState(state: Partial<LibraryDeepLink>): Record<string, string> {
  const params: Record<string, string> = {};
  if (state.view && state.view !== "library") params.view = state.view;
  if (state.importOpen && state.importTab) params.import = state.importTab;
  if (state.readingStatus && state.readingStatus !== "all") params.status = state.readingStatus;
  return params;
}

function pageLocation(page: string): NavLocation {
  return { page: normalizePage(page), params: {} };
}

function fallbackLocation(route: string | undefined): NavLocation {
  return route ? pageLocation(route) : pageLocation(DEFAULT_PAGE);
}

// readiness check ID → 具体落点。后端只回页面级 route；这里按 check ID 补足内层状态。
export function readinessCheckLocation(checkId: string, fallbackRoute?: string): NavLocation {
  switch (checkId) {
    case "llm":
    case "embedding":
    case "rag":
      return pageLocation("settings");
    case "library":
      return { page: "library", params: { import: "pdf" } };
    case "analysis":
      return pageLocation("library");
    case "graph":
      return pageLocation("graph");
    case "reading":
      return { page: "library", params: { status: "reading" } };
    case "writing":
      return { page: "library", params: { view: "thesis" } };
    default:
      return fallbackLocation(fallbackRoute);
  }
}

// research progress action ID → 具体落点（修复“去处理”只在 library 页失灵的问题）。
export function researchActionLocation(actionId: string, fallbackRoute?: string): NavLocation {
  switch (actionId) {
    case "import_papers":
      return { page: "library", params: { import: "pdf" } };
    case "fix_library_quality":
      // 诊断面板随研究仪表板迁移到了研究主页。
      return pageLocation("home");
    case "process_reading_queue":
      return { page: "library", params: { status: "queued" } };
    case "build_review_matrix":
      return { page: "library", params: { view: "matrix" } };
    case "create_thesis_structure":
    case "link_read_papers_to_thesis":
      return { page: "library", params: { view: "thesis" } };
    case "continue_research_loop":
      return pageLocation("library");
    default:
      return fallbackLocation(fallbackRoute);
  }
}
