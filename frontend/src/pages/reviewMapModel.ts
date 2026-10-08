// 纯逻辑模型：文献地图区块的核对标签、定位、筛选与主题编辑。
// 不导入 reviewsApi 等运行时模块，保持可被 tsconfig.graph-test.json 单独编译。

export type MapTheme = { id: string; name: string; definition: string; include?: string; exclude?: string };
export type CardField = {
  value: string;
  quote: string;
  status: string;
  found_in?: string | null;
  pages?: number[];
  missing_numbers?: string[];
  similarity?: number | null;
};
export type FilterablePaper = {
  paper_id: number;
  title: string;
  year?: number | string | null;
  venue?: string | null;
  doi?: string | null;
  themes: string[];
  evidence_level: string;
  card_status: string;
  fields: CardField[];
};

export type PaperFilter = { query?: string; theme?: string; evidence?: string; status?: string };

export function statusLabel(status: string, similarity?: number | null): string {
  switch (status) {
    case 'quote_verified':
      return similarity != null && similarity < 1 ? '近似核对原文' : '已核对原文';
    case 'number_mismatch':
      return '数字与原文不符';
    case 'quote_not_found':
      return '未在原文找到引文';
    case 'no_quote':
      return '模型归纳';
    case 'unverifiable':
      return '仅元数据，无法核对';
    default:
      return status || '';
  }
}

export function fieldLocation(field: CardField): { page?: number; text: string } {
  const pages = field.pages ?? [];
  if (pages.length > 0) return { page: pages[0], text: `第 ${pages[0]} 页` };
  if (field.found_in === 'abstract') return { text: '摘要' };
  return { text: '' };
}

export function filterPapers(papers: FilterablePaper[], filter: PaperFilter): FilterablePaper[] {
  const query = (filter.query ?? '').trim().toLowerCase();
  return papers.filter((paper) => {
    if (query) {
      const haystack = `${paper.title ?? ''} ${paper.doi ?? ''}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    if (filter.theme && !paper.themes.includes(filter.theme)) return false;
    if (filter.evidence && paper.evidence_level !== filter.evidence) return false;
    if (filter.status) {
      const needsCheck = paper.fields.some(
        (field) => field.status === 'number_mismatch' || field.status === 'quote_not_found',
      );
      if (!needsCheck) return false;
    }
    return true;
  });
}

export function renameTheme(themes: MapTheme[], id: string, name: string): MapTheme[] {
  return themes.map((theme) => (theme.id === id ? { ...theme, name } : theme));
}

export function mergeThemes(themes: MapTheme[], ids: string[], name: string): MapTheme[] {
  const picked = themes.filter((theme) => ids.includes(theme.id));
  const definition = picked.map((theme) => theme.definition).filter(Boolean).join('；');
  const include = picked.map((theme) => theme.include ?? '').filter(Boolean).join('；');
  const exclude = picked.map((theme) => theme.exclude ?? '').filter(Boolean).join('；');
  return [
    ...themes.filter((theme) => !ids.includes(theme.id)),
    { id: '', name, definition, include, exclude },
  ];
}

export function removeTheme(themes: MapTheme[], id: string): MapTheme[] {
  return themes.filter((theme) => theme.id !== id);
}

export function addTheme(themes: MapTheme[], name: string, definition = ''): MapTheme[] {
  return [...themes, { id: '', name, definition, include: '', exclude: '' }];
}
