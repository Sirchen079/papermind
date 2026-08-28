import { lazy, Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import { useTheme, type Theme } from "./theme";
import { Blocks, BookOpen, Lightbulb, Logo, Menu, MessageSquare, Moon, Settings as SettingsIcon, Share2, Sun } from "./icons";
import { ConfirmProvider } from "./components/ui/ConfirmDialog";
import { ToastProvider } from "./components/ui/Toast";
import { Skeleton, SkeletonGroup } from "./components/ui/Skeleton";

// Route-level code splitting keeps the heavy graph lib (cytoscape) out of the
// initial bundle — it only loads when the Graph page is opened.
const Library = lazy(() => import("./pages/Library"));
const Graph = lazy(() => import("./pages/Graph"));
const Chat = lazy(() => import("./pages/Chat"));
const Skills = lazy(() => import("./pages/Skills"));
const Settings = lazy(() => import("./pages/Settings"));
const Suggestions = lazy(() => import("./pages/Suggestions"));

interface NavItem {
  key: string;
  label: string;
  icon: ReactNode;
  hint: string;
}

const NAV: NavItem[] = [
  { key: "library", label: "论文库", icon: <BookOpen size={18} />, hint: "论文与入库" },
  { key: "suggestions", label: "建议", icon: <Lightbulb size={18} />, hint: "主动关联" },
  { key: "graph", label: "图谱", icon: <Share2 size={18} />, hint: "知识网络" },
  { key: "chat", label: "对话", icon: <MessageSquare size={18} />, hint: "科研对话" },
  { key: "skills", label: "技能", icon: <Blocks size={18} />, hint: "自定义能力" },
  { key: "settings", label: "设置", icon: <SettingsIcon size={18} />, hint: "模型与提供商" },
];

function readInitialPage() {
  if (typeof window === "undefined") return "library";
  const raw = window.location.hash.replace(/^#/, "");
  const [page] = raw.split("?");
  return NAV.some((item) => item.key === page) ? page : "library";
}

function ThemeToggle({ theme, toggle }: { theme: Theme; toggle: () => void }) {
  const isDark = theme === "dark";
  return (
    <button
      onClick={toggle}
      className="btn-ghost w-full justify-start"
      title={`切换到${isDark ? "浅色" : "深色"}模式`}
      aria-label={`切换到${isDark ? "浅色" : "深色"}模式`}
    >
      {isDark ? <Sun size={16} /> : <Moon size={16} />}
      <span>{isDark ? "浅色模式" : "深色模式"}</span>
    </button>
  );
}

export default function App() {
  const [page, setPage] = useState(readInitialPage);
  const [newCount, setNewCount] = useState(0);
  const [openPaperId, setOpenPaperId] = useState<number | null>(null);
  const [activeConv, setActiveConv] = useState<number | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { theme, toggle } = useTheme();
  const active = NAV.find((n) => n.key === page);

  // Cross-page "open this paper" — e.g. clicking a RAG source chip in Chat.
  const openPaper = useCallback((id: number) => {
    setOpenPaperId(id);
    setPage("library");
  }, []);
  const clearOpenPaper = useCallback(() => setOpenPaperId(null), []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const raw = window.location.hash.replace(/^#/, "");
    const [currentPage] = raw.split("?");
    if (currentPage === page) return;
    const nextHash = page === "library" ? "" : `#${page}`;
    if (window.location.hash !== nextHash) {
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${nextHash}`);
    }
  }, [page]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const syncFromHash = () => {
      const raw = window.location.hash.replace(/^#/, "");
      const [nextPage] = raw.split("?");
      if (NAV.some((item) => item.key === nextPage) && nextPage !== page) {
        setPage(nextPage);
      }
    };
    window.addEventListener("hashchange", syncFromHash);
    return () => window.removeEventListener("hashchange", syncFromHash);
  }, [page]);

  useEffect(() => {
    let alive = true;
    api
      .listSuggestions("new")
      .then((s) => alive && setNewCount(s.length))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [page]);

  return (
    <ToastProvider>
    <ConfirmProvider>
    <div className="flex h-screen overflow-hidden">
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-72 shrink-0 flex-col p-4 transition-transform duration-200 lg:static lg:z-auto lg:w-60 lg:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
        style={{ backgroundColor: "var(--surface)", borderRight: "1px solid var(--border)" }}
      >
        <div className="mb-6 flex items-center gap-2.5 px-2">
          <div
            className="flex h-9 w-9 items-center justify-center rounded-lg"
            style={{ backgroundColor: "var(--accent)", color: "var(--accent-contrast)" }}
          >
            <Logo size={22} />
          </div>
          <div>
            <div className="text-base font-bold leading-tight tracking-tight">PaperMind</div>
            <div className="text-[11px] text-faint">
              面向硕士研究的论文管理工作台
            </div>
          </div>
        </div>

        <nav className="flex-1 space-y-1">
          <div className="label px-2">导航</div>
          {NAV.map((item) => {
            const isActive = page === item.key;
            return (
              <button
                key={item.key}
                onClick={() => {
                  setPage(item.key);
                  setSidebarOpen(false);
                }}
                className={`group relative flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors ${
                  isActive
                    ? "bg-[var(--accent-soft)]"
                    : "text-muted hover:bg-[var(--surface-2)]"
                }`}
                title={item.hint}
              >
                {isActive && (
                  <span
                    className="absolute left-0 top-1/2 h-5 -translate-y-1/2 rounded-r-full"
                    style={{ width: "3px", backgroundColor: "var(--accent)" }}
                  />
                )}
                <span className="flex h-5 w-5 items-center justify-center">{item.icon}</span>
                <span className="flex-1 text-sm font-medium">{item.label}</span>
                {item.key === "suggestions" && newCount > 0 && (
                  <span
                    className="ml-auto flex h-5 min-w-[1.25rem] items-center justify-center rounded-full px-1.5 text-[11px] font-semibold"
                    style={{ backgroundColor: "var(--accent)", color: "var(--accent-contrast)" }}
                  >
                    {newCount}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        <div className="mt-4 space-y-2">
          <div className="lg:hidden">
            <ThemeToggle theme={theme} toggle={toggle} />
          </div>
          <div className="px-2 pt-1 text-[11px] text-faint">
            本地 · 单用户 · v0.1
          </div>
        </div>
      </aside>

      {sidebarOpen && (
        <div
          className="modal-overlay z-30 lg:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      <main className="flex-1 overflow-auto">
        <header
          className="sticky top-0 z-10 flex items-center justify-between gap-3 px-4 py-4 backdrop-blur sm:px-6 lg:px-10"
          style={{
            backgroundColor: "color-mix(in srgb, var(--bg) 82%, transparent)",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSidebarOpen(true)}
              className="btn-ghost shrink-0 p-2 lg:hidden"
              aria-label="打开导航"
            >
              <Menu size={18} />
            </button>
            <div className="flex items-center gap-2 text-sm">
              <span className="text-faint">PaperMind</span>
              <span className="text-faint">/</span>
              <span className="font-medium text-[var(--text)]">{active?.label}</span>
            </div>
          </div>
          <div className="hidden items-center gap-2 lg:flex">
            <ThemeToggle theme={theme} toggle={toggle} />
          </div>
        </header>
        {/*
          内容壳只提供纵向 padding；横向 padding + 居中 + 宽度由各页面的 <Shell>
          自治（wide/narrow/fluid）。这样 header 的 px 与各页 Shell 的 px 对齐，
          内容居中、宽度按页面用途区分。
        */}
        <div className="py-4 sm:py-6 lg:py-8">
          <Suspense
            fallback={
              <div className="space-y-4">
                <Skeleton variant="card" />
                <SkeletonGroup variant="row" count={4} />
              </div>
            }
          >
            {page === "library" && (
              <Library openPaperId={openPaperId} onConsumedOpen={clearOpenPaper} onNavigate={setPage} />
            )}
            {page === "suggestions" && <Suggestions onOpenPaper={openPaper} />}
            {page === "graph" && <Graph theme={theme} onOpenPaper={openPaper} />}
            {page === "chat" && (
              <Chat
                activeConv={activeConv}
                setActiveConv={setActiveConv}
                onOpenPaper={openPaper}
              />
            )}
            {page === "skills" && <Skills />}
            {page === "settings" && <Settings />}
          </Suspense>
        </div>
      </main>
    </div>
    </ConfirmProvider>
    </ToastProvider>
  );
}
