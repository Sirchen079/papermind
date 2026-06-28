import { useEffect, useRef, useState } from "react";
import cytoscape, { type Core } from "cytoscape";
import { api, type GraphData } from "../api";

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export default function Graph() {
  const [kind, setKind] = useState<"paper" | "concept">("paper");
  const [minPapers, setMinPapers] = useState(1);
  const [data, setData] = useState<GraphData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  useEffect(() => {
    api.graph(kind, minPapers).then(setData).catch((e: any) => setError(e.message));
  }, [kind, minPapers]);

  useEffect(() => {
    if (!data || !containerRef.current) return;
    if (cyRef.current) {
      cyRef.current.destroy();
      cyRef.current = null;
    }
    const accent = cssVar("--accent") || "#4f46e5";
    const accent2 = "#7c3aed";
    const edgeColor = cssVar("--border-strong") || "#cbd5e1";
    const nodes = data.nodes.map((n) => ({
      data: { id: String(n.id), label: n.title ?? n.name ?? String(n.id) },
    }));
    const edges = data.edges.map((e) => ({
      data: { id: `${e.source}-${e.target}`, source: String(e.source), target: String(e.target), weight: e.weight },
    }));
    cyRef.current = cytoscape({
      container: containerRef.current,
      elements: [...nodes, ...edges],
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "text-valign": "center",
            "font-size": "8px",
            "background-color": kind === "paper" ? accent : accent2,
            color: "#ffffff",
            width: "44px",
            height: "44px",
            "text-wrap": "wrap",
            "text-max-width": "56px",
          },
        },
        { selector: "edge", style: { width: 2, "line-color": edgeColor } },
      ],
      layout: { name: "cose", animate: false, padding: 30 } as any,
      minZoom: 0.2,
      maxZoom: 3,
    });
    return () => {
      cyRef.current?.destroy();
      cyRef.current = null;
    };
  }, [data, kind]);

  const nodeCount = data?.nodes.length ?? 0;
  const edgeCount = data?.edges.length ?? 0;

  return (
    <div className="max-w-6xl">
      <div className="mb-4 flex flex-wrap items-center gap-4">
        <div className="inline-flex overflow-hidden rounded-lg" style={{ border: "1px solid var(--border)" }}>
          {(["paper", "concept"] as const).map((k) => {
            const isActive = kind === k;
            return (
              <button
                key={k}
                onClick={() => setKind(k)}
                className="px-3.5 py-1.5 text-sm capitalize transition-colors"
                style={
                  isActive
                    ? { backgroundColor: "var(--accent)", color: "var(--accent-contrast)" }
                    : { backgroundColor: "var(--surface)", color: "var(--muted)" }
                }
              >
                {k} graph
              </button>
            );
          })}
        </div>
        {kind === "concept" && (
          <label className="flex items-center gap-2 text-sm">
            <span style={{ color: "var(--muted)" }}>min papers</span>
            <input
              type="number"
              min={1}
              value={minPapers}
              onChange={(e) => setMinPapers(Math.max(1, Number(e.target.value)))}
              className="input w-20 py-1"
            />
          </label>
        )}
        <span className="ml-auto text-sm" style={{ color: "var(--muted)" }}>
          {nodeCount} nodes · {edgeCount} edges
        </span>
      </div>
      {error && (
        <div className="mb-2 text-sm" style={{ color: "var(--danger)" }}>
          {error}
        </div>
      )}
      <div
        ref={containerRef}
        className="h-[640px] rounded-xl border"
        style={{ backgroundColor: "var(--surface)", borderColor: "var(--border)" }}
      />
    </div>
  );
}
