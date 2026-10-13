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

// R07：批量操作后是否需要刷新当前视图——只有真实改动（书目确实更新/全文
// 确实附接）才刷新，其余状态沿用原提示，不发无意义的刷新请求。
export function enrichHasUpdates(counts: Record<string, number>): boolean {
  return (counts.updated ?? 0) > 0;
}

export function fulltextHasAttachments(counts: Record<string, number>): boolean {
  return (counts.attached ?? 0) > 0;
}

// R07：与 load()/搜索共用的异步序号判定——响应发出后若有更新的请求发起
// （新搜索/新刷新），旧响应直接丢弃，不得覆盖新查询结果。
export function responseIsCurrent(issueSeq: number, latestSeq: number): boolean {
  return issueSeq === latestSeq;
}

// R07：详情同步判定——仅当用户仍选中同一篇论文（含详情仍打开）时才套用
// 慢响应带回的新详情；切换选中或关闭详情后不覆盖新的上下文。
export function selectionMatchesPaper(
  currentSelectedId: number | null | undefined,
  fetchedPaperId: number,
): boolean {
  return currentSelectedId === fetchedPaperId;
}

// R07：批量改动后刷新当前视图的结果。
// refreshed=已套用；stale=期间发起了更新的查询/刷新，本次旧快照丢弃；
// failed=刷新请求本身失败（业务操作不受影响）。
export type BulkViewRefreshOutcome = "refreshed" | "stale" | "failed";

// R07：把业务结果与刷新结果合成最终提示。业务统计在所有分支里原样保留，
// 并明确"数据已保存"；刷新失败单独说明，不引导用户重复执行已成功的操作。
export function combineBulkResultMessage(opMsg: string, outcome: BulkViewRefreshOutcome): string {
  if (outcome === "refreshed") return opMsg;
  if (outcome === "stale") return `${opMsg}；数据已保存，期间视图已切换到新的查询结果，未套用本次刷新。`;
  return `${opMsg}；数据已保存，但当前视图刷新失败，请稍后刷新页面查看最新内容。`;
}
