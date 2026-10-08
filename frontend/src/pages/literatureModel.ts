// 文献调研页的纯状态模型：参数校验、状态文案与选择规则。
// 后端契约：单次导入上限 import_batch cap（当前 10）；下载只走公开开放获取链接并串行限速。

export const DEFAULT_IMPORT_BATCH_CAP = 10;

export function surveyQueryValid(query: string): boolean {
  const trimmed = (query ?? '').trim();
  return trimmed.length > 0 && trimmed.length <= 500;
}

export function surveyActive(status: string): boolean {
  return status === 'queued' || status === 'running';
}

export function importActive(detail: Pick<LiteratureLikeDetail, 'import_status' | 'counts'> | null): boolean {
  if (!detail) return false;
  if (detail.import_status === 'running') return true;
  return (detail.counts?.queued_import ?? 0) > 0;
}

export interface LiteratureLikeDetail {
  import_status: string;
  counts: Record<string, number>;
}

export function canImportCandidate(status: string): boolean {
  return status === 'candidate' || status === 'failed';
}

export function selectionWithinCap(selected: number, cap: number = DEFAULT_IMPORT_BATCH_CAP): boolean {
  return selected > 0 && selected <= cap;
}

const surveyStatusLabels: Record<string, string> = {
  queued: '排队中', running: '正在调研', ready: '已完成', error: '未完成', interrupted: '已中断',
};
export function surveyStatusLabel(status: string): string {
  return surveyStatusLabels[status] ?? status;
}

const candidateStatusLabels: Record<string, string> = {
  candidate: '待选择', queued_import: '正在添加', imported: '已入库（含全文）',
  imported_no_pdf: '已入库（仅题录）', duplicate: '库中已有', failed: '添加失败',
};
export function candidateStatusLabel(status: string): string {
  return candidateStatusLabels[status] ?? status;
}

export function candidateStatusTone(status: string): string {
  switch (status) {
    case 'imported':
    case 'duplicate':
      return 'var(--accent)';
    case 'failed':
      return 'var(--danger)';
    case 'imported_no_pdf':
    case 'queued_import':
      return 'var(--muted, inherit)';
    default:
      return 'inherit';
  }
}

export function candidateHasOaPdf(candidate: { oa_pdf_url: string | null; arxiv_id: string }): boolean {
  return Boolean(candidate.oa_pdf_url) || Boolean(candidate.arxiv_id);
}

export function candidateSourceLabel(candidate: { oa_pdf_url: string | null; arxiv_id: string }): string {
  return candidateHasOaPdf(candidate) ? '公开全文' : '仅题录';
}

export function authorLine(authors: string[], limit = 3): string {
  const names = (authors ?? []).filter(Boolean);
  if (!names.length) return '';
  return names.slice(0, limit).join('、') + (names.length > limit ? ` 等 ${names.length} 人` : '');
}

export const YEARS_OPTIONS = [1, 2, 3, 5] as const;
export const MAX_RESULTS_OPTIONS = [10, 20, 30, 50] as const;

export function clampChoice<T extends number>(value: unknown, options: readonly T[], fallback: T): T {
  return typeof value === 'number' && (options as readonly number[]).includes(value) ? (value as T) : fallback;
}
