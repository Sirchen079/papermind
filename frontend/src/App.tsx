import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { useTheme, type Theme } from "./theme";

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
  icon: string;
  hint: string;
}

const NAV: NavItem[] = [
  { key: "library", label: "论文库", icon: "📚", hint: "论文与入库" },
  { key: "suggestions", label: "建议", icon: "✦", hint: "主动关联" },
  { key: "graph", label: "图谱", icon: "🕸", hint: "知识网络" },
  { key: "chat", label: "对话", icon: "💬", hint: "科研对话" },
  { key: "skills", label: "技能", icon: "⚡", hint: "自定义能力" },
  { key: "settings", label: "设置", icon: "⚙", hint: "模型与提供商" },
];

function ThemeToggle({ theme, toggle }: { theme: Theme; toggle: () => void }) {
  return (
    <button
      onClick={toggle}
      className="btn-ghost w-full justify-start"
      title={`切换到${theme === "dark" ? "浅色" : "深色"}模式`}
      aria-label="切换主题"
    >
      <span className="text-base leading-none">{theme === "dark" ? "☀" : "☾"}</span>
      <span>{theme === "dark" ? "浅色模式" : "深色模式"}</span>
    </button>
  );
}

export default function App() {
  const [page, setPage] = useState("library");
  const [newCount, setNewCount] = useState(0);
  const [openPaperId, setOpenPaperId] = useState<number | null>(null);
  const [activeConv, setActiveConv] = useState<number | null>(null);
  const { theme, toggle } = useTheme();
  const active = NAV.find((n) => n.key === page);

  // Cross-page "open this paper" — e.g. clicking a RAG source chip in Chat.
  const openPaper = useCallback((id: number) => {
    setOpenPaperId(id);
    setPage("library");
  }, []);
  const clearOpenPaper = useCallback(() => setOpenPaperId(null), []);

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
    <div className="flex h-screen overflow-hidden">
      <aside
        className="flex w-60 shrink-0 flex-col p-4"
        style={{ backgroundColor: "var(--surface)", borderRight: "1px solid var(--border)" }}
      >
        <div className="mb-6 flex items-center gap-2.5 px-2">
          <div
            className="flex h-9 w-9 items-center justify-center rounded-lg text-lg font-bold"
            style={{ backgroundColor: "var(--accent)", color: "var(--accent-contrast)" }}
          >
            P
          </div>
          <div>
            <div className="text-base font-bold leading-tight tracking-tight">PaperMind</div>
            <div className="text-[11px]" style={{ color: "var(--faint)" }}>
              AI 科研工作台
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
                onClick={() => setPage(item.key)}
                className="group relative flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors"
                style={
                  isActive
                    ? { backgroundColor: "var(--accent-soft)", color: "var(--text)" }
                    : { color: "var(--muted)" }
                }
                onMouseEnter={(e) => {
                  if (!isActive) e.currentTarget.style.backgroundColor = "var(--surface-2)";
                }}
                onMouseLeave={(e) => {
                  if (!isActive) e.currentTarget.style.backgroundColor = "transparent";
                }}
              >
                {isActive && (
                  <span
                    className="absolute left-0 top-1/2 h-5 -translate-y-1/2 rounded-r-full"
                    style={{ width: "3px", backgroundColor: "var(--accent)" }}
                  />
                )}
                <span className="w-5 text-center text-base leading-none">{item.icon}</span>
                <span className="flex-1">
                  <span className="block text-sm font-medium">{item.label}</span>
                  <span className="block text-[11px]" style={{ color: "var(--faint)" }}>
                    {item.hint}
                  </span>
                </span>
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
          <ThemeToggle theme={theme} toggle={toggle} />
          <div className="px-2 pt-1 text-[11px]" style={{ color: "var(--faint)" }}>
            本地 · 单用户 · v0.1
          </div>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">
        <header
          className="sticky top-0 z-10 flex items-center justify-between px-8 py-4 backdrop-blur"
          style={{
            backgroundColor: "color-mix(in srgb, var(--bg) 82%, transparent)",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <div>
            <h2 className="text-xl font-bold tracking-tight">{active?.label ?? "PaperMind"}</h2>
            <p className="text-xs" style={{ color: "var(--muted)" }}>
              {active?.hint}
            </p>
          </div>
        </header>
        <div className="p-8">
          <Suspense
            fallback={
              <div
                className="flex h-64 items-center justify-center text-sm"
                style={{ color: "var(--faint)" }}
              >
                加载中…
              </div>
            }
          >
            {page === "library" && (
              <Library openPaperId={openPaperId} onConsumedOpen={clearOpenPaper} />
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
  );
}
