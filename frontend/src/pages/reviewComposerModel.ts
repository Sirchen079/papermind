// 纯逻辑模型：创建综述/文献地图前的 token 用量预估文案。
// 自包含，不导入 reviewsApi 等运行时模块，保持可被 tsconfig.graph-test.json 单独编译。
// 数字与后端 GET /reviews/estimate 的返回结构一一对应。

export type ReviewEstimate = {
  papers: number;
  with_full_text: number;
  material_tokens: number;
  map_tokens: number;
  review_tokens: number;
};

// 万位换算保留 1 位小数（四舍五入），不足 1 万直接给整数；整万不带小数点。
function tokenAmount(tokens: number): string {
  if (tokens < 10000) return String(tokens);
  return `${Math.round(tokens / 1000) / 10} 万`;
}

export function formatTokenEstimate(r: ReviewEstimate): string {
  if (!r || r.papers === 0) return '';
  return `共 ${r.papers} 篇 · ${r.with_full_text} 篇有全文 · 材料约 ${tokenAmount(r.material_tokens)} token，生成地图约 ${tokenAmount(r.map_tokens)}，写综述正文约 ${tokenAmount(r.review_tokens)}（粗略估计，以实际用量为准）`;
}
