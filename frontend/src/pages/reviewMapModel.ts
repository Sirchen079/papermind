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

// 新增与合并出的主题先用临时 id（new-N）区分彼此，保存时去掉，由后端分配 T 编号。
const TEMP_ID = /^new-\d+$/;

function nextTempId(themes: MapTheme[]): string {
  const used = new Set(themes.map((theme) => theme.id));
  let n = 1;
  while (used.has(`new-${n}`)) n += 1;
  return `new-${n}`;
}

export function renameTheme(themes: MapTheme[], id: string, name: string): MapTheme[] {
  return themes.map((theme) => (theme.id === id ? { ...theme, name } : theme));
}

export function mergeThemes(themes: MapTheme[], ids: string[], name: string): MapTheme[] {
  const picked = themes.filter((theme) => ids.includes(theme.id));
  const rest = themes.filter((theme) => !ids.includes(theme.id));
  const definition = picked.map((theme) => theme.definition).filter(Boolean).join('；');
  const include = picked.map((theme) => theme.include ?? '').filter(Boolean).join('；');
  const exclude = picked.map((theme) => theme.exclude ?? '').filter(Boolean).join('；');
  return [...rest, { id: nextTempId(themes), name, definition, include, exclude }];
}

export function removeTheme(themes: MapTheme[], id: string): MapTheme[] {
  return themes.filter((theme) => theme.id !== id);
}

export function addTheme(themes: MapTheme[], name: string, definition = ''): MapTheme[] {
  return [...themes, { id: nextTempId(themes), name, definition, include: '', exclude: '' }];
}

export function themesForSave(themes: MapTheme[]): MapTheme[] {
  return themes.map((theme) => (TEMP_ID.test(theme.id) ? { ...theme, id: '' } : theme));
}

// 地图里“值得研究的问题”和“方法组合机会”是研究起点：带着依据论文进入研究对话继续核对和设计验证。
export type MapOpenQuestion = { question: string; why?: string; cannot_claim?: string; cards?: number[] };
export type MapCombination = { idea: string; expected?: string; risk?: string; cards?: number[] };

const HANDOFF_PAPERS = 6;
const HANDOFF_CHARS = 2000;

export function researchHandoff(
  theme: string,
  item: MapOpenQuestion | MapCombination,
  representative: number[] = [],
): { question: string; paperIds: number[] } {
  const paperIds = [...new Set([...(item.cards ?? []), ...representative])].slice(0, HANDOFF_PAPERS);
  const lines = 'question' in item
    ? [
      `围绕文献地图「${theme}」主题中的这个待研究问题继续研究：`,
      item.question,
      item.why ? `地图给出的依据：${item.why}` : '',
      item.cannot_claim ? `现有证据的缺口：${item.cannot_claim}` : '',
      '请先核对所附论文原文：这个问题是否确实尚未解决、已有工作做到哪一步、各自的实验条件；再提出一个最小可行的验证方案（数据、基线、评价指标、预期风险），并标出仍需我判断的地方。',
    ]
    : [
      `围绕文献地图「${theme}」主题中的这个方法组合机会继续研究：`,
      item.idea,
      item.expected ? `预期收益：${item.expected}` : '',
      item.risk ? `地图提示的风险：${item.risk}` : '',
      '请先核对所附论文原文中相关方法的前提与实验条件，判断这一组合是否成立、是否已有人做过；再给出最小可行的验证方案（数据、基线、评价指标、预期风险），并标出仍需我判断的地方。',
    ];
  const instruction = lines[lines.length - 1];
  let body = lines.slice(0, -1).filter(Boolean).join('\n');
  const room = HANDOFF_CHARS - instruction.length - 2;
  if (body.length > room) body = body.slice(0, room - 1) + '…';
  return { question: `${body}\n\n${instruction}`, paperIds };
}
