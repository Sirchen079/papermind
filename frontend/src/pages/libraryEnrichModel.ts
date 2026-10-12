// P1c：批量“补全书目信息 / 获取公开全文”的纯逻辑（不发请求）。
// 状态取值与后端 /papers/enrich-metadata、/papers/fetch-open-fulltext 一致。

// 后端单次批量上限（超限返回 422）。
export const ENRICH_METADATA_CAP = 200;
export const FETCH_FULLTEXT_CAP = 50;

const ENRICH_STATUS_LABELS: Record<string, string> = {
  updated: "已更新",
  no_doi: "无 DOI",
  unavailable: "查询失败",
  not_found: "未找到",
  unchanged: "无变化",
};
const ENRICH_STATUS_ORDER = ["updated", "no_doi", "unavailable", "not_found", "unchanged"];

const FULLTEXT_STATUS_LABELS: Record<string, string> = {
  no_open_access: "无公开获取",
  has_pdf: "已有全文",
  failed: "失败",
  no_doi: "无 DOI",
  not_found: "未找到",
};
const FULLTEXT_STATUS_ORDER = ["no_open_access", "has_pdf", "failed", "no_doi", "not_found"];

export function buildPaperIdsPayload(selected: number[], cap: number): number[] | null {
  const seen = new Set<number>();
  const ids: number[] = [];
  for (const id of selected) {
    if (!Number.isInteger(id) || id <= 0 || seen.has(id)) continue;
    seen.add(id);
    ids.push(id);
  }
  if (ids.length > cap) return null;
  return ids;
}

export function summarizeEnrichResults(counts: Record<string, number>): string {
  if ((counts.updated ?? 0) === 0) return "没有补全到新字段";
  const parts = ENRICH_STATUS_ORDER
    .filter((status) => (counts[status] ?? 0) > 0)
    .map((status) => `${counts[status]} 篇${ENRICH_STATUS_LABELS[status]}`);
  return `补全完成:${parts.join(",")}`;
}

export function summarizeFulltextResults(counts: Record<string, number>): string {
  const parts = FULLTEXT_STATUS_ORDER
    .filter((status) => (counts[status] ?? 0) > 0)
    .map((status) => `${counts[status]} 篇${FULLTEXT_STATUS_LABELS[status]}`);
  const suffix = parts.length > 0 ? `,${parts.join(",")}` : "";
  return `已获取 ${counts.attached ?? 0} 篇公开全文${suffix}`;
}
