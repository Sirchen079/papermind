import assert from "node:assert/strict";
import { test } from "node:test";

import { formatTokenEstimate } from "../.tmp_graph_test_dist/reviewComposerModel.js";

test("papers 为 0 时返回空串，界面不显示", () => {
  assert.equal(
    formatTokenEstimate({ papers: 0, with_full_text: 0, material_tokens: 0, map_tokens: 0, review_tokens: 0 }),
    "",
  );
});

test("按万位换算保留 1 位小数并拼接中文文案", () => {
  const text = formatTokenEstimate({
    papers: 12,
    with_full_text: 8,
    material_tokens: 42000,
    map_tokens: 63000,
    review_tokens: 126000,
  });
  assert.equal(
    text,
    "共 12 篇 · 8 篇有全文 · 材料约 4.2 万 token，生成地图约 6.3 万，写综述正文约 12.6 万（粗略估计，以实际用量为准）",
  );
});

test("不足 1 万直接给整数，整万不带小数点", () => {
  const text = formatTokenEstimate({
    papers: 3,
    with_full_text: 1,
    material_tokens: 5000,
    map_tokens: 7500,
    review_tokens: 60000,
  });
  assert.equal(text, "共 3 篇 · 1 篇有全文 · 材料约 5000 token，生成地图约 7500，写综述正文约 6 万（粗略估计，以实际用量为准）");
});

test("换算时四舍五入到 1 位小数", () => {
  const text = formatTokenEstimate({
    papers: 1,
    with_full_text: 1,
    material_tokens: 42500,
    map_tokens: 64000,
    review_tokens: 127500,
  });
  assert.equal(
    text,
    "共 1 篇 · 1 篇有全文 · 材料约 4.3 万 token，生成地图约 6.4 万，写综述正文约 12.8 万（粗略估计，以实际用量为准）",
  );
});
