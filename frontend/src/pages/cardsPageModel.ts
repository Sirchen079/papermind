// 纯逻辑模型：一级精读卡片页的字段行、筛选与单篇 Markdown 导出。
// 与 reviewMapModel.ts 一样自包含（类型与 reviewsApi 保持结构一致，
// 不直接 import，避免 tsconfig.graph-test.json 的 rootDir 越界）。
type PaperCardField = {
  value: string;
  quote: string;
  status: string;
  found_in?: string | null;
  pages?: number[];
  missing_numbers?: string[];
  similarity?: number | null;
};
type PaperCardData = {
  metadata?: Record<string, unknown>;
  evidence_level?: string;
  problem?: PaperCardField;
  mechanism?: PaperCardField;
  data_setting?: PaperCardField;
  boundary?: PaperCardField;
  contributions?: PaperCardField[];
};
type PaperCardEntry = { paper_id: number; title: string; status: string; card: PaperCardData | null; warning: string; updated_at: string | null };

// 字段顺序与文献地图区块一致：问题/机制/数据条件/主要贡献 N/判断边界。
export type CardRow = { label: string; value: string; quote?: string };

export function cardFieldRows(card: PaperCardData | null): CardRow[] {
  if (!card) return [];
  const rows: CardRow[] = [];
  const push = (label: string, field: PaperCardField | undefined) => {
    if (!field || !field.value || !field.value.trim()) return;
    rows.push(field.quote ? { label, value: field.value, quote: field.quote } : { label, value: field.value });
  };
  push("问题", card.problem);
  push("机制", card.mechanism);
  push("数据条件", card.data_setting);
  (card.contributions ?? []).forEach((contribution, i) => push(`主要贡献 ${i + 1}`, contribution));
  push("判断边界", card.boundary);
  return rows;
}

// 搜索题名子串（不区分大小写）或卡片编号（P12、12 均可）。
export function filterCards(entries: PaperCardEntry[], query: string): PaperCardEntry[] {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) return entries;
  const idMatch = /^p?(\d+)$/.exec(trimmed);
  const wantedId = idMatch ? Number(idMatch[1]) : null;
  return entries.filter((entry) => {
    if (wantedId !== null && entry.paper_id === wantedId) return true;
    return (entry.title ?? "").toLowerCase().includes(trimmed);
  });
}

export type CardPaperMeta = { year?: number | string | null; venue?: string | null; doi?: string | null };

// 单篇卡片导出为 Markdown；card 为 null 时保留标题并输出卡片状态行。
export function cardToMarkdown(entry: PaperCardEntry, paper?: CardPaperMeta): string {
  const lines: string[] = [`# [P${entry.paper_id}] ${entry.title ?? `论文 ${entry.paper_id}`}`];
  const meta = [
    paper?.year != null && paper.year !== "" ? String(paper.year) : "",
    paper?.venue ?? "",
    paper?.doi ? `DOI: ${paper.doi}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  if (meta) lines.push("", meta);
  if (!entry.card) {
    lines.push("", `- 卡片状态：${entry.status}`);
    return lines.join("\n");
  }
  for (const row of cardFieldRows(entry.card)) {
    lines.push("", `**${row.label}：**${row.value}`);
    if (row.quote) lines.push("", `> 原文：“${row.quote}”`);
  }
  return lines.join("\n");
}
