import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { type Core, type EdgeSingular, type NodeSingular } from "cytoscape";
import { api, type GraphData } from "../api";
import type { Theme } from "../theme";
import {
  CONCEPT_TYPE_LABELS,
  LEGEND_TYPES,
  type GraphMode,
  conceptColor,
  graphLabel,
  modeAccent,
  modeHint,
  modeLabel,
  nodeMetrics,
  nodeTypeLabel,
  nodeVisualStyle,
  normalizeNodes,
  readGraphParams,
  writeGraphParams,
} from "./graphModel";
import { Shell } from "../components/layout/Shell";

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function graphLayout(mode: GraphMode) {
  const isPaper = mode === "paper";
  return {
    name: "cose",
    animate: false,
    fit: true,
    padding: isPaper ? 64 : 80,
    randomize: true,
    componentSpacing: isPaper ? 170 : 220,
    nodeRepulsion: isPaper ? 11200 : 14200,
    idealEdgeLength: isPaper ? 156 : 118,
    edgeElasticity: 92,
    gravity: isPaper ? 0.18 : 0.24,
    spacingFactor: isPaper ? 1.08 : 1.18,
    numIter: 1500,
  } as any;
}

function edgeIsVisible(edge: EdgeSingular, visibleIds: Set<string>) {
  return visibleIds.has(edge.source().id()) || visibleIds.has(edge.target().id());
}

export default function Graph({
  theme,
  onOpenPaper,
}: {
  theme: Theme;
  onOpenPaper: (id: number) => void;
}) {
  const initialParams = useMemo(() => readGraphParams(), []);
  const [mode, setMode] = useState<GraphMode>(initialParams.mode);
  const [minPapers, setMinPapers] = useState(initialParams.minPapers);
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  const switchMode = (next: GraphMode) => {
    setMode(next);
    setQuery("");
    setSelectedId(null);
  };

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    setData(null);
    setSelectedId(null);
    api
      .graph(mode, minPapers)
      .then((next) => {
        if (!alive) return;
        setData(next);
      })
      .catch((e: any) => {
        if (alive) setError(e.message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [mode, minPapers, reloadTick]);

  const nodes = useMemo(() => normalizeNodes(data), [data]);
  const nodeIndex = useMemo(() => new Map(nodes.map((node) => [node.id, node] as const)), [nodes]);
  const selectedNode = selectedId != null ? nodeIndex.get(selectedId) ?? null : null;

  const stats = useMemo(() => {
    const topNode = [...nodeIndex.values()].sort((a, b) => (b.count ?? 0) - (a.count ?? 0))[0] ?? null;
    return {
      nodes: data?.nodes.length ?? 0,
      edges: data?.edges.length ?? 0,
      topNode,
    };
  }, [data, nodeIndex]);

  useEffect(() => {
    writeGraphParams(mode, minPapers);
  }, [mode, minPapers]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const syncFromHash = () => {
      const next = readGraphParams();
      setMode(next.mode);
      setMinPapers(next.minPapers);
    };
    window.addEventListener("hashchange", syncFromHash);
    return () => window.removeEventListener("hashchange", syncFromHash);
  }, []);

  useEffect(() => {
    if (!data || !containerRef.current) {
      if (cyRef.current) {
        cyRef.current.destroy();
        cyRef.current = null;
      }
      return;
    }

    if (cyRef.current) {
      cyRef.current.destroy();
      cyRef.current = null;
    }

    const paperVisual = nodeVisualStyle("paper", theme, null);
    const activeVisual = nodeVisualStyle(mode, theme, null);
    const focusColor = activeVisual.focusColor;
    const hierarchyColor = theme === "dark" ? "#34d399" : "#059669";
    const edgeBase = cssVar("--border-strong") || "#cbd5e1";
    const focusBorder = theme === "dark" ? "#f8fafc" : "#0f172a";
    const isPaper = mode === "paper";
    const elements = [
      ...nodes.map((node) => ({
        data: {
          id: String(node.id),
          label: graphLabel(node.label, mode),
          rawLabel: node.label,
          count: node.count,
          type: node.type ?? "",
          year: node.year ?? "",
        },
      })),
      ...data.edges.map((edge) => ({
        data: {
          id: `${edge.source}-${edge.target}-${edge.edge_type ?? "cooccurrence"}`,
          source: String(edge.source),
          target: String(edge.target),
          weight: edge.weight,
          edgeType: edge.edge_type ?? "cooccurrence",
        },
      })),
    ];

    const cy = cytoscape({
      container: containerRef.current,
      elements,
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "text-justification": "center",
            "font-size": isPaper ? "12px" : "12px",
            "font-weight": 600,
            "line-height": 1.25,
            color: (ele: NodeSingular) =>
              nodeVisualStyle(mode, theme, String(ele.data("type") || "")).textColor,
            shape: (ele: NodeSingular) =>
              nodeVisualStyle(mode, theme, String(ele.data("type") || "")).shape,
            "text-wrap": "wrap",
            "text-overflow-wrap": "anywhere",
            "text-max-width": (ele: NodeSingular) => `${nodeMetrics(String(ele.data("rawLabel") || ""), Number(ele.data("count") || 0), mode).textMaxWidth}px`,
            width: (ele: NodeSingular) => `${nodeMetrics(String(ele.data("rawLabel") || ""), Number(ele.data("count") || 0), mode).width}px`,
            height: (ele: NodeSingular) => `${nodeMetrics(String(ele.data("rawLabel") || ""), Number(ele.data("count") || 0), mode).height}px`,
            padding: "14px",
            "background-color": (ele: NodeSingular) => {
              const type = String(ele.data("type") || "");
              return nodeVisualStyle(mode, theme, type).backgroundColor;
            },
            "border-width": 3,
            "border-color": (ele: NodeSingular) =>
              nodeVisualStyle(mode, theme, String(ele.data("type") || "")).borderColor,
            "overlay-padding": 8,
            "text-outline-width": 0,
            "min-zoomed-font-size": 8,
          },
        },
        {
          selector: "node.focus",
          style: {
            "border-width": 4,
            "border-color": focusBorder,
            "overlay-opacity": 0.1,
            "overlay-color": focusColor,
          } as any,
        },
        {
          selector: "node.dimmed",
          style: {
            opacity: 0.12,
          },
        },
        {
          selector: "node:selected",
          style: {
            "overlay-opacity": 0.08,
            "overlay-color": focusColor,
          },
        },
        {
          selector: "edge",
          style: {
            width: (ele: any) =>
              ele.data("edgeType") === "hierarchy"
                ? 1.4
                : Math.max(1, Math.min(4.5, 0.8 + Number(ele.data("weight") || 1) * 0.9)),
            "line-color": (ele: any) => {
              if (ele.data("edgeType") === "hierarchy") return hierarchyColor;
              const weight = Number(ele.data("weight") || 1);
              return weight > 2 ? paperVisual.borderColor : edgeBase;
            },
            opacity: (ele: any) => (ele.data("edgeType") === "hierarchy" ? 0.55 : 0.42),
            "line-style": (ele: any) => (ele.data("edgeType") === "hierarchy" ? "dashed" : "solid"),
            "curve-style": "bezier",
            "target-arrow-shape": (ele: any) => (ele.data("edgeType") === "hierarchy" ? "triangle" : "none"),
            "target-arrow-color": (ele: any) => (ele.data("edgeType") === "hierarchy" ? hierarchyColor : edgeBase),
            "arrow-scale": 0.75,
            "line-cap": "round",
          },
        },
        {
          selector: "edge.dimmed",
          style: {
            opacity: 0.05,
          },
        },
      ],
      layout: graphLayout(mode),
      minZoom: 0.18,
      maxZoom: 3.2,
      wheelSensitivity: 0.18,
    });

    const applyFocus = (id: number | null) => {
      const focus = id != null ? cy.$id(String(id)) : cy.collection();
      cy.nodes().removeClass("dimmed focus");
      cy.edges().removeClass("dimmed");
      if (focus.empty()) return;
      const neighborhood = focus.closedNeighborhood();
      cy.nodes().not(neighborhood.nodes()).addClass("dimmed");
      cy.edges().not(neighborhood.edges()).addClass("dimmed");
      focus.addClass("focus");
    };

    const applyQuery = (value: string) => {
      const q = value.trim().toLowerCase();
      if (!q) {
        applyFocus(selectedId);
        return;
      }
      cy.nodes().removeClass("dimmed");
      cy.edges().removeClass("dimmed");
      const matches = cy.nodes().filter((node) => String(node.data("rawLabel") || "").toLowerCase().includes(q));
      const visibleIds = new Set(matches.map((node) => node.id()));
      cy.nodes().not(matches).addClass("dimmed");
      cy.edges().filter((edge) => !edgeIsVisible(edge as EdgeSingular, visibleIds)).addClass("dimmed");
      if (selectedId != null && !visibleIds.has(String(selectedId))) {
        cy.$id(String(selectedId)).addClass("focus");
      }
    };

    cy.on("tap", "node", (evt: any) => {
      const id = Number(evt.target.id());
      setSelectedId(id);
      applyFocus(id);
    });

    cyRef.current = cy;
    setTimeout(() => {
      applyFocus(selectedId);
      applyQuery(query);
    }, 0);

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, mode, theme]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const q = query.trim().toLowerCase();
    cy.nodes().removeClass("dimmed focus");
    cy.edges().removeClass("dimmed");
    if (selectedId != null) {
      const focus = cy.$id(String(selectedId));
      if (focus.nonempty()) {
        const neighborhood = focus.closedNeighborhood();
        cy.nodes().not(neighborhood.nodes()).addClass("dimmed");
        cy.edges().not(neighborhood.edges()).addClass("dimmed");
        focus.addClass("focus");
      }
    }
    if (q) {
      const matches = cy.nodes().filter((node) => String(node.data("rawLabel") || "").toLowerCase().includes(q));
      const visibleIds = new Set(matches.map((node) => node.id()));
      cy.nodes().not(matches).addClass("dimmed");
      cy.edges().filter((edge) => !edgeIsVisible(edge as EdgeSingular, visibleIds)).addClass("dimmed");
    }
  }, [query, selectedId]);

  const selectedMeta = selectedNode
    ? [
        selectedNode.year ? `${selectedNode.year} 年` : null,
        nodeTypeLabel(selectedNode.type) ? `类型：${nodeTypeLabel(selectedNode.type)}` : null,
        `关联数：${selectedNode.count}`,
      ].filter(Boolean)
    : [];

  const topRows = [...nodeIndex.values()].sort((a, b) => (b.count ?? 0) - (a.count ?? 0)).slice(0, 5);
  const graphWash =
    mode === "paper"
      ? theme === "dark"
        ? "rgba(59, 130, 246, 0.12)"
        : "rgba(37, 99, 235, 0.08)"
      : theme === "dark"
        ? "rgba(16, 185, 129, 0.12)"
        : "rgba(5, 150, 105, 0.08)";
  const gridLine = theme === "dark" ? "rgba(148, 163, 184, 0.1)" : "rgba(148, 163, 184, 0.16)";
  const emptyMessage =
    mode === "concept" && minPapers > 1
      ? "当前最少论文数筛选过高，已经没有概念满足条件。"
      : "暂无图谱数据。先导入论文并生成概念，再回来查看关系网络。";

  return (
    <Shell max="wide">
      <div className="mb-4 border-b pb-4 border-[var(--border)]">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">关系图谱</h1>
            <p className="mt-1 text-sm text-muted">
              在论文图谱和概念图谱之间切换，快速定位核心文献、主题簇和高频概念。
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="inline-flex overflow-hidden rounded-lg border shadow-sm border-[var(--border)] bg-[var(--surface-2)]">
              {(["paper", "concept"] as const).map((item) => {
                const active = mode === item;
                return (
                  <button
                    key={item}
                    onClick={() => switchMode(item)}
                    className="px-4 py-2 text-sm font-medium transition-colors"
                    style={
                      active
                        ? { backgroundColor: modeAccent(item), color: "var(--accent-contrast)" }
                        : { backgroundColor: "transparent", color: "var(--muted)" }
                    }
                  >
                    {item === "paper" ? "论文图谱" : "概念图谱"}
                  </button>
                );
              })}
            </div>

            {mode === "concept" && (
              <label className="flex items-center gap-2 text-sm text-muted">
                <span >最少论文数</span>
                <input
                  type="number"
                  min={1}
                  value={minPapers}
                  onChange={(e) => setMinPapers(Math.max(1, Number(e.target.value) || 1))}
                  className="input w-24 py-2 text-sm"
                />
              </label>
            )}
          </div>
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="block">
              <span className="label">搜索节点</span>
              <input
                className="input py-2"
                placeholder={mode === "paper" ? "输入论文标题关键词" : "输入概念名称关键词"}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <div className="rounded-lg border p-3 border-[var(--border)] bg-[var(--surface-2)]">
              <div className="text-xs text-faint">
                当前模式
              </div>
              <div className="mt-1 font-semibold">{modeLabel(mode)}</div>
              <div className="mt-1 text-sm text-muted">
                {modeHint(mode)}
              </div>
            </div>
            <div className="rounded-lg border p-3 border-[var(--border)] bg-[var(--surface-2)]">
              <div className="text-xs text-faint">
                统计
              </div>
              <div className="mt-1 font-semibold">
                {stats.nodes} 个节点 / {stats.edges} 条边
              </div>
              <div className="mt-1 text-sm text-muted">
                {loading ? "正在加载图谱..." : stats.topNode ? `最密集节点：${stats.topNode.label}` : "暂无图谱数据"}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2">
            <button onClick={() => cyRef.current?.fit(undefined, 42)} className="btn-ghost py-2 text-sm" title="适配画布">
              适配画布
            </button>
            <button
              onClick={() =>
                cyRef.current
                  ?.layout(graphLayout(mode))
                  .run()
              }
              className="btn-ghost py-2 text-sm"
              title="重新布局"
            >
              重新布局
            </button>
            <button onClick={() => setQuery("")} className="btn-subtle py-2 text-sm" title="清空搜索">
              清空搜索
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div
          className="mb-3 rounded-lg border px-4 py-3 text-sm"
          style={{
            borderColor: "color-mix(in srgb, var(--danger) 30%, var(--border))",
            color: "var(--danger)",
            backgroundColor: "color-mix(in srgb, var(--danger) 8%, transparent)",
          }}
        >
          图谱加载失败：{error}
          <button onClick={() => setReloadTick((tick) => tick + 1)} className="btn-ghost ml-3 py-1 text-xs">
            重试
          </button>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="relative overflow-hidden rounded-lg border p-2 shadow-sm bg-[var(--surface)] border-[var(--border)]">
          <div
            ref={containerRef}
            className="min-h-[72vh] w-full rounded-md"
            style={{
              backgroundColor: "var(--surface)",
              backgroundImage: `linear-gradient(${gridLine} 1px, transparent 1px), linear-gradient(90deg, ${gridLine} 1px, transparent 1px), linear-gradient(180deg, ${graphWash} 0%, transparent 46%)`,
              backgroundSize: "32px 32px, 32px 32px, auto",
            }}
          />
          {loading && (
            <div
              className="absolute inset-2 flex items-center justify-center rounded-md text-sm font-medium"
              style={{
                color: "var(--muted)",
                backgroundColor: "color-mix(in srgb, var(--surface) 72%, transparent)",
              }}
            >
              正在加载{modeLabel(mode)}…
            </div>
          )}
          {data && stats.nodes === 0 && !error && (
            <div className="absolute inset-2 flex items-center justify-center rounded-md px-4 text-center text-sm text-muted">
              <div className="max-w-md rounded-lg border px-4 py-3 shadow-sm" style={{ borderColor: "var(--border)", backgroundColor: "var(--surface)" }}>
                <div className="font-medium text-[var(--text)]">
                  暂无可展示节点
                </div>
                <div className="mt-1 leading-relaxed">{emptyMessage}</div>
                {mode === "concept" && minPapers > 1 && (
                  <button onClick={() => setMinPapers(1)} className="btn-primary mt-3 py-2 text-sm">
                    显示全部概念
                  </button>
                )}
              </div>
            </div>
          )}
        </div>

        <aside className="space-y-4">
          <section className="rounded-lg border p-4 shadow-sm bg-[var(--surface)] border-[var(--border)]">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-base font-semibold">{mode === "paper" ? "节点详情" : "概念详情"}</h2>
              <button onClick={() => setSelectedId(null)} className="btn-subtle py-1 text-xs">
                清除选中
              </button>
            </div>
            {selectedNode ? (
              <div className="mt-4 space-y-3">
                <div>
                  <div className="text-lg font-semibold leading-snug">{selectedNode.label}</div>
                  <div className="mt-1 text-xs text-muted">
                    {selectedMeta.join(" · ")}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {mode === "paper" && (
                    <button onClick={() => onOpenPaper(selectedNode.id)} className="btn-primary py-2 text-sm">
                      在库中打开
                    </button>
                  )}
                  <button
                    onClick={() => {
                      setQuery(selectedNode.label);
                    }}
                    className="btn-ghost py-2 text-sm"
                  >
                    搜索该节点
                  </button>
                </div>
                <div className="rounded-lg border p-3 text-sm border-[var(--border)] bg-[var(--surface-2)]">
                  <div className="text-xs text-faint">
                    说明
                  </div>
                  <div className="mt-1 leading-relaxed text-muted">
                    {mode === "paper"
                      ? "论文节点越大，说明它在当前库里与更多概念相关；边越粗，说明共享概念越多。"
                      : "概念节点越大，说明它出现在更多论文中；边越粗，说明两个概念经常共同出现。"}
                  </div>
                </div>
              </div>
            ) : (
              <p className="mt-3 text-sm text-muted">
                点击任意节点查看详情。
              </p>
            )}
          </section>

          <section className="rounded-lg border p-4 shadow-sm bg-[var(--surface)] border-[var(--border)]">
            <h2 className="text-base font-semibold">图例</h2>
            {mode === "paper" ? (
              <div className="mt-3 space-y-2">
                <div className="flex items-center gap-2 text-sm text-muted">
                  <span className="h-3 w-5 rounded bg-[var(--accent)]"  />
                  论文节点
                </div>
                <div className="rounded-lg border px-3 py-2 text-xs leading-relaxed" style={{ borderColor: "var(--border)", backgroundColor: "var(--surface-2)", color: "var(--muted)" }}>
                  节点越大，表示这篇论文与更多概念相关；边越粗，表示共享概念越多。
                </div>
              </div>
            ) : (
              <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
                {LEGEND_TYPES.map((type) => (
                  <div key={type} className="flex items-center gap-2 text-muted">
                    <span className="h-3 w-5 rounded" style={{ backgroundColor: conceptColor(type) }} />
                    {CONCEPT_TYPE_LABELS[type]}
                  </div>
                ))}
                <div className="flex items-center gap-2 text-muted">
                  <span className="h-3 w-5 rounded" style={{ backgroundColor: conceptColor(null) }} />
                  其他
                </div>
                <div className="col-span-2 flex items-center gap-2 text-muted">
                  <span className="h-px w-8 border-t border-dashed" style={{ borderColor: "#059669" }} />
                  上下位概念关系
                </div>
                <div className="col-span-2 rounded-lg border px-3 py-2 text-xs leading-relaxed" style={{ borderColor: "var(--border)", backgroundColor: "var(--surface-2)", color: "var(--muted)" }}>
                  节点越大，表示该概念出现在更多论文中；边越粗，表示两个概念经常共同出现。
                </div>
              </div>
            )}
          </section>

          <section className="rounded-lg border p-4 shadow-sm bg-[var(--surface)] border-[var(--border)]">
            <h2 className="text-base font-semibold">筛选状态</h2>
            <div className="mt-3 grid gap-2 text-sm">
              <div className="flex items-center justify-between gap-3 text-muted">
                <span >模式</span>
                <span className="font-medium">{modeLabel(mode)}</span>
              </div>
              <div className="flex items-center justify-between gap-3 text-muted">
                <span >搜索</span>
                <span className="max-w-[180px] truncate font-medium">{query.trim() || "未筛选"}</span>
              </div>
              {mode === "concept" && (
                <div className="flex items-center justify-between gap-3 text-muted">
                  <span >最少论文数</span>
                  <span className="font-medium">{minPapers}</span>
                </div>
              )}
              <div className="flex items-center justify-between gap-3 text-muted">
                <span >选中节点</span>
                <span className="max-w-[180px] truncate font-medium">{selectedNode?.label ?? "无"}</span>
              </div>
            </div>
          </section>

          <section className="rounded-lg border p-4 shadow-sm bg-[var(--surface)] border-[var(--border)]">
            <h2 className="text-base font-semibold">当前高频</h2>
            <div className="mt-3 space-y-2">
              {topRows.map((node) => (
                <button
                  key={node.id}
                  onClick={() => setSelectedId(node.id)}
                  className="flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left transition-colors border-[var(--border)] bg-[var(--surface-2)]"
                  
                >
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{node.label}</span>
                  <span className="chip shrink-0">{node.count}</span>
                </button>
              ))}
              {topRows.length === 0 && (
                <p className="text-sm text-muted">
                  暂无可展示的高频节点。
                </p>
              )}
            </div>
          </section>
        </aside>
      </div>
    </Shell>
  );
}
