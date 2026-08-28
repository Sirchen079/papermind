export type GraphMode = "paper" | "concept";
export type GraphTheme = "light" | "dark";

export type GraphNode = {
  id: number;
  label: string;
  title: string | null;
  name: string | null;
  year: number | null;
  type: string | null;
  count: number;
};

export type GraphParams = {
  mode: GraphMode;
  minPapers: number;
};

type GraphDataLike = {
  nodes?: {
    id: number;
    title?: string | null;
    name?: string | null;
    year?: number | null;
    type?: string | null;
    count?: number | null;
  }[];
  edges?: { source: number; target: number; weight?: number | null }[];
} | null;

export const CONCEPT_TYPE_LABELS: Record<string, string> = {
  method: "方法",
  dataset: "数据集",
  problem: "问题",
  task: "任务",
  theory: "理论",
  application: "应用",
  domain: "领域",
};

export const LEGEND_TYPES = ["method", "dataset", "problem", "task", "theory", "application", "domain"] as const;

export const CONCEPT_COLORS: Record<string, string> = {
  method: "#2563eb",
  dataset: "#059669",
  problem: "#dc2626",
  task: "#7c3aed",
  theory: "#b45309",
  application: "#0891b2",
  domain: "#475569",
  other: "#0f766e",
};

const CONCEPT_LIGHT_PALETTE: Record<string, { backgroundColor: string; textColor: string }> = {
  method: { backgroundColor: "#dbeafe", textColor: "#1e3a8a" },
  dataset: { backgroundColor: "#d1fae5", textColor: "#065f46" },
  problem: { backgroundColor: "#fee2e2", textColor: "#991b1b" },
  task: { backgroundColor: "#ede9fe", textColor: "#5b21b6" },
  theory: { backgroundColor: "#fef3c7", textColor: "#92400e" },
  application: { backgroundColor: "#cffafe", textColor: "#155e75" },
  domain: { backgroundColor: "#e2e8f0", textColor: "#334155" },
  other: { backgroundColor: "#ccfbf1", textColor: "#115e59" },
};

const CONCEPT_DARK_PALETTE: Record<string, { backgroundColor: string; textColor: string }> = {
  method: { backgroundColor: "#172554", textColor: "#dbeafe" },
  dataset: { backgroundColor: "#052e2b", textColor: "#a7f3d0" },
  problem: { backgroundColor: "#450a0a", textColor: "#fecaca" },
  task: { backgroundColor: "#2e1065", textColor: "#ddd6fe" },
  theory: { backgroundColor: "#451a03", textColor: "#fde68a" },
  application: { backgroundColor: "#164e63", textColor: "#cffafe" },
  domain: { backgroundColor: "#1e293b", textColor: "#e2e8f0" },
  other: { backgroundColor: "#134e4a", textColor: "#ccfbf1" },
};

export function conceptColor(type: string | null | undefined) {
  return CONCEPT_COLORS[type || ""] ?? CONCEPT_COLORS.other;
}

export function nodeVisualStyle(mode: GraphMode, theme: GraphTheme, type: string | null | undefined) {
  if (mode === "paper") {
    return {
      shape: "round-rectangle" as const,
      backgroundColor: theme === "dark" ? "#172554" : "#dbeafe",
      borderColor: theme === "dark" ? "#60a5fa" : "#2563eb",
      textColor: theme === "dark" ? "#dbeafe" : "#1e3a8a",
      focusColor: theme === "dark" ? "#93c5fd" : "#1d4ed8",
    };
  }

  const key = CONCEPT_LIGHT_PALETTE[type || ""] ? String(type) : "other";
  const palette = theme === "dark" ? CONCEPT_DARK_PALETTE[key] : CONCEPT_LIGHT_PALETTE[key];
  return {
    shape: "round-rectangle" as const,
    backgroundColor: palette.backgroundColor,
    borderColor: conceptColor(key),
    textColor: palette.textColor,
    focusColor: theme === "dark" ? "#86efac" : "#047857",
  };
}

export function parseGraphParamsFromHash(hash: string): GraphParams {
  const raw = hash.replace(/^#/, "");
  const [page, query = ""] = raw.split("?");
  if (page !== "graph") return { mode: "paper", minPapers: 1 };
  const params = new URLSearchParams(query);
  const mode = params.get("mode") === "concept" ? "concept" : "paper";
  const minPapers = Math.max(1, Number(params.get("min_papers") || "1") || 1);
  return { mode, minPapers };
}

export function buildGraphHash(mode: GraphMode, minPapers: number) {
  if (mode === "paper") return "#graph";
  const params = new URLSearchParams();
  params.set("mode", "concept");
  params.set("min_papers", String(Math.max(1, minPapers)));
  return `#graph?${params.toString()}`;
}

export function readGraphParams(): GraphParams {
  if (typeof window === "undefined") return { mode: "paper", minPapers: 1 };
  return parseGraphParamsFromHash(window.location.hash);
}

export function writeGraphParams(mode: GraphMode, minPapers: number) {
  if (typeof window === "undefined") return;
  const hash = buildGraphHash(mode, minPapers);
  if (window.location.hash !== hash) {
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${hash}`);
  }
}

export function modeLabel(mode: GraphMode) {
  return mode === "paper" ? "论文图谱" : "概念图谱";
}

export function modeHint(mode: GraphMode) {
  return mode === "paper"
    ? "论文节点表示文献，连线表示共享概念，适合找核心文献和相关论文。"
    : "概念节点表示研究主题，连线表示共现或上下位关系，适合梳理方向脉络。";
}

export function modeAccent(mode: GraphMode) {
  return mode === "paper" ? "#2563eb" : "#047857";
}

export function nodeTypeLabel(type: string | null | undefined) {
  if (!type) return null;
  return CONCEPT_TYPE_LABELS[type] ?? type;
}

export function visualWidth(text: string) {
  return [...text].reduce((sum, char) => {
    if (/\s/.test(char)) return sum + 0.45;
    if (/[\u3000-\u303f\uff00-\uffef\u4e00-\u9fff]/u.test(char)) return sum + 1;
    if (/[A-Z0-9]/.test(char)) return sum + 0.86;
    return sum + 0.76;
  }, 0);
}

function trimToVisualWidth(text: string, maxWidth: number) {
  let next = "";
  for (const char of [...text]) {
    if (visualWidth(`${next}${char}...`) > maxWidth) break;
    next += char;
  }
  return `${next || text.slice(0, 1)}...`;
}

export function wrapGraphLabel(label: string, mode: GraphMode) {
  const clean = (label || "未命名").trim().replace(/\s+/g, " ");
  const maxLineWidth = mode === "paper" ? 18 : 12;
  const maxLines = mode === "paper" ? 4 : 3;
  const lines: string[] = [];
  let line = "";

  for (const char of [...clean]) {
    const next = line ? `${line}${char}` : char;
    if (line && visualWidth(next) > maxLineWidth) {
      lines.push(line.trim());
      line = char.trimStart();
      if (lines.length === maxLines) break;
    } else {
      line = next;
    }
  }

  if (line && lines.length < maxLines) lines.push(line.trim());
  const compactLines = lines.filter(Boolean);
  const consumed = compactLines.join("").replace(/\s/g, "").length;
  const original = clean.replace(/\s/g, "");
  if (original.length > consumed && compactLines.length > 0) {
    compactLines[compactLines.length - 1] = trimToVisualWidth(
      compactLines[compactLines.length - 1],
      maxLineWidth,
    );
  }

  return compactLines.length > 0 ? compactLines : ["未命名"];
}

export function nodeMetrics(label: string, count: number, mode: GraphMode) {
  const lines = wrapGraphLabel(label, mode);
  const longest = Math.max(...lines.map(visualWidth));
  const minWidth = mode === "paper" ? 260 : 212;
  const maxWidth = mode === "paper" ? 390 : 320;
  const textScale = mode === "paper" ? 11.6 : 13;
  const width = Math.ceil(
    Math.min(maxWidth, Math.max(minWidth, longest * textScale + 56 + Math.min(count, 8) * 2)),
  );
  const minHeight = mode === "paper" ? 98 : 96;
  const maxHeight = mode === "paper" ? 150 : 128;
  const lineHeight = mode === "paper" ? 18 : 17;
  const height = Math.ceil(Math.min(maxHeight, Math.max(minHeight, 46 + lines.length * lineHeight)));

  return {
    width,
    height,
    textMaxWidth: Math.max(132, width - 42),
  };
}

export function graphLabel(label: string, mode: GraphMode) {
  return wrapGraphLabel(label, mode).join("\n");
}

export function nodeLabel(node: { title?: string | null; name?: string | null; id: number }) {
  return node.title ?? node.name ?? String(node.id);
}

export function normalizeNodes(data: GraphDataLike): GraphNode[] {
  const edgeDegree = new Map<number, number>();
  for (const edge of data?.edges ?? []) {
    const weight = Number(edge.weight || 1);
    edgeDegree.set(edge.source, (edgeDegree.get(edge.source) ?? 0) + weight);
    edgeDegree.set(edge.target, (edgeDegree.get(edge.target) ?? 0) + weight);
  }
  return (data?.nodes ?? []).map((node) => ({
    id: node.id,
    label: nodeLabel(node),
    title: node.title ?? null,
    name: node.name ?? null,
    year: node.year ?? null,
    type: node.type ?? null,
    count: node.count ?? edgeDegree.get(node.id) ?? 0,
  }));
}
