// T10：库外论文（OpenAlex 相关研究 / 未匹配引用）一键加入待读。
// 纯模型：元数据是否足够、请求载荷、成功文案；失败时 UI 保留外链降级。

export interface ExternalPaperLike {
  title?: string | null;
  doi?: string | null;
  arxiv_id?: string | null;
  year?: number | null;
  venue?: string | null;
  authors?: string[];
}

export function canQueueExternal(item: ExternalPaperLike): boolean {
  return Boolean(item.title?.trim() || item.doi?.trim() || item.arxiv_id?.trim());
}

export function externalPaperPayload(
  item: ExternalPaperLike,
): Record<string, unknown> | null {
  if (!canQueueExternal(item)) return null;
  const payload: Record<string, unknown> = {};
  const title = item.title?.trim();
  const doi = item.doi?.trim();
  const arxivId = item.arxiv_id?.trim();
  if (title) payload.title = title;
  if (doi) payload.doi = doi;
  if (arxivId) payload.arxiv_id = arxivId;
  if (item.year != null) payload.year = item.year;
  const venue = item.venue?.trim();
  if (venue) payload.venue = venue;
  if (item.authors && item.authors.length > 0) payload.authors = item.authors;
  return payload;
}

export function queueSuccessLabel(created: boolean): string {
  return created ? "已入库并加入待读。" : "论文已在库中，已加入待读。";
}
