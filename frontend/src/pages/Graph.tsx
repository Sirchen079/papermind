import { useEffect, useRef, useState } from "react";
import cytoscape, { type Core } from "cytoscape";
import { api, type GraphData } from "../api";

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
            "background-color": kind === "paper" ? "#1e40af" : "#7c3aed",
            color: "#fff",
            width: "44px",
            height: "44px",
            "text-wrap": "wrap",
            "text-max-width": "56px",
          },
        },
        { selector: "edge", style: { width: 2, "line-color": "#cbd5e1" } },
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
      <div className="flex items-center gap-4 mb-4">
        <h2 className="text-2xl font-bold">Knowledge Graph</h2>
        <div className="inline-flex rounded-lg overflow-hidden border">
          {(["paper", "concept"] as const).map((k) => (
            <button
              key={k}
              onClick={() => setKind(k)}
              className={`px-3 py-1.5 text-sm capitalize ${
                kind === k ? "bg-slate-900 text-white" : "bg-white"
              }`}
            >
              {k}
            </button>
          ))}
        </div>
        {kind === "concept" && (
          <label className="text-sm flex items-center gap-2">
            min papers
            <input
              type="number"
              min={1}
              value={minPapers}
              onChange={(e) => setMinPapers(Math.max(1, Number(e.target.value)))}
              className="w-16 border rounded px-2 py-1"
            />
          </label>
        )}
        <span className="text-sm text-slate-500 ml-auto">
          {nodeCount} nodes · {edgeCount} edges
        </span>
      </div>
      {error && <div className="text-red-600 text-sm mb-2">{error}</div>}
      <div
        ref={containerRef}
        className="bg-white rounded-lg shadow border h-[640px]"
      />
    </div>
  );
}
