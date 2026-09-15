// T9：服务端全库搜索的前端纯模型。
// 论文列表搜索走 GET /api/papers?q=（覆盖全库），带防抖与请求竞态合并；
// 阅读状态/优先级等复杂筛选仍为客户端逻辑，只作用于已加载范围。

export const SEARCH_DEBOUNCE_MS = 300;

export function normalizeSearchQuery(raw: string): string {
  return (raw ?? "").trim().replace(/\s+/g, " ");
}

export function isServerSearchActive(raw: string): boolean {
  return normalizeSearchQuery(raw).length > 0;
}

export interface SearchItemLike {
  id: number;
}

// 首页结果整体替换；加载更多按 offset 追加并按 id 去重。
export function mergeSearchPage<T extends SearchItemLike>(
  existing: T[],
  incoming: T[],
  offset: number,
): T[] {
  if (offset === 0) return incoming;
  const seen = new Set(existing.map((item) => item.id));
  return [...existing, ...incoming.filter((item) => !seen.has(item.id))];
}

export interface SearchScopeNoticeInput {
  serverActive: boolean;
  loaded: number;
  total: number;
}

// 服务器搜索覆盖全库匹配，但复杂筛选仍只作用于已加载部分——如实提示范围。
export function searchScopeNotice(input: SearchScopeNoticeInput): string | null {
  if (!input.serverActive || input.loaded >= input.total) return null;
  return `已匹配全库 ${input.total} 篇，当前加载 ${input.loaded} 篇；阅读状态等筛选只作用于已加载部分。`;
}
