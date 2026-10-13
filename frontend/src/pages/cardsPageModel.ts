// 纯逻辑模型：一级精读卡片页的字段行、筛选与单篇 Markdown 导出。
// 与 reviewMapModel.ts 一样不 import reviewsApi（类型保持结构一致，
// 避免 tsconfig.graph-test.json 的 rootDir 越界）；核验状态与来源定位的
// 中文文案复用 reviewMapModel 的 statusLabel/fieldLocation，与文献地图
// 卡片区块保持一致（同在 src/pages，运行时 import 需带 .js 后缀）。
import { fieldLocation, statusLabel } from './reviewMapModel.js';
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
// 行模型保留字段级核验信息：状态、未匹配数字与真实来源定位（页码/摘要），
// 供页面警示、原文跳转与 Markdown 导出使用，不再只剩值和引文。
export type CardRow = {
  label: string;
  value: string;
  quote?: string;
  status: string; // 后端原始核验状态；旧卡片缺失时为空串
  statusText: string; // 中文核验状态；未知/缺失如实标注，不当作已核验
  missingNumbers: string[];
  locationText: string; // 「第 N 页」「摘要」等真实定位；无定位为空串
  page?: number; // 原文跳转页码；仅来自真实页码，不补造
  problem: boolean; // 数字不匹配 / 未找到引文，需人工核对
};

// 与文献地图「只看需核对的」一致：仅这两类状态视为需人工核对，其余不产生警告。
const PROBLEM_STATUSES = new Set(['number_mismatch', 'quote_not_found']);
const NO_STATUS_TEXT = '未记录核验状态';

function fieldStatusText(field: PaperCardField): string {
  const label = statusLabel(field.status ?? '', field.similarity);
  return label || NO_STATUS_TEXT;
}

export function cardFieldRows(card: PaperCardData | null): CardRow[] {
  if (!card) return [];
  const rows: CardRow[] = [];
  const push = (label: string, field: PaperCardField | undefined) => {
    if (!field || !field.value || !field.value.trim()) return;
    const location = fieldLocation(field);
    const status = field.status ?? '';
    rows.push({
      label,
      value: field.value,
      quote: field.quote || undefined,
      status,
      statusText: fieldStatusText(field),
      missingNumbers: field.missing_numbers ?? [],
      locationText: location.text,
      page: location.page,
      problem: PROBLEM_STATUSES.has(status),
    });
  };
  push("问题", card.problem);
  push("机制", card.mechanism);
  push("数据条件", card.data_setting);
  (card.contributions ?? []).forEach((contribution, i) => push(`主要贡献 ${i + 1}`, contribution));
  push("判断边界", card.boundary);
  return rows;
}

// 行内核验说明，文案与文献地图卡片区块一致：状态＋缺少数字＋（定位）。
export function cardRowStatusText(row: CardRow): string {
  let text = row.statusText;
  if (row.missingNumbers.length) text += `：缺少 ${row.missingNumbers.join('、')}`;
  if (row.locationText) text += `（${row.locationText}）`;
  return text;
}

// 引文出处标签：仅当核验确认引文存在于原文（含命中但数字不符）时才标「原文」，
// 其余状态一律用「引文」，不把未经核实的引文包装成原文结论。
export function cardRowQuoteLabel(row: CardRow): string {
  return row.status === 'quote_verified' || row.status === 'number_mismatch' ? '原文' : '引文';
}

// 整卡级字段核对摘要，与卡片完成状态（entry.status）分开显示；
// 无需注意字段时返回空串，不做「全部通过」的保证。
export function cardCheckSummary(card: PaperCardData | null): string {
  const problems = cardFieldRows(card).filter((row) => row.problem).length;
  return problems ? `字段核对：${problems} 项需注意` : '';
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
  const summary = cardCheckSummary(entry.card);
  if (summary) lines.push("", summary);
  for (const row of cardFieldRows(entry.card)) {
    lines.push("", `**${row.label}：**${row.value}`);
    const status = cardRowStatusText(row);
    if (status) lines.push("", `${row.problem ? "⚠ " : ""}${status}`);
    if (row.quote) lines.push("", `> ${cardRowQuoteLabel(row)}：“${row.quote}”`);
  }
  return lines.join("\n");
}
