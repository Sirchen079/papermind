// 纯逻辑模型：一级文献地图页的初始专题选择。
// 与 CardsPage 同一规则：上次选中且仍在列表则保留；否则用深链 review 参数；
// 再否则第一项；没有综述时为空串。
export function pickInitialReview(prev: string, paramReview: string, rows: { id: string }[]): string {
  if (prev && rows.some((r) => r.id === prev)) return prev;
  if (paramReview && rows.some((r) => r.id === paramReview)) return paramReview;
  return rows[0]?.id ?? '';
}
