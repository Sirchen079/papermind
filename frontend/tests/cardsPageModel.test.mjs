import assert from "node:assert/strict";
import { test } from "node:test";

import {
  cardFieldRows,
  cardToMarkdown,
  filterCards,
} from "../.tmp_graph_test_dist/cardsPageModel.js";

const field = (value, quote = "") => ({ value, quote, status: "quote_verified" });
const fullCard = {
  problem: field("如何从少量观测恢复稀疏信号", "观测数远小于信号维度"),
  mechanism: field("凸优化 l1 最小化"),
  data_setting: field("高斯随机观测矩阵"),
  contributions: [field("给出恢复的充分条件"), field(""), field("实测数据验证")],
  boundary: field("仅适用于高斯观测"),
};
const entry = (overrides = {}) => ({
  paper_id: 12,
  title: "Sparse Recovery in Compressive Sensing",
  status: "done",
  card: null,
  warning: "",
  updated_at: null,
  ...overrides,
});

test("cardFieldRows null 返回空数组", () => {
  assert.deepEqual(cardFieldRows(null), []);
});

test("cardFieldRows 按固定顺序映射字段并带引文", () => {
  const rows = cardFieldRows(fullCard);
  assert.deepEqual(rows.map((r) => r.label), [
    "问题",
    "机制",
    "数据条件",
    "主要贡献 1",
    "主要贡献 3",
    "判断边界",
  ]);
  assert.equal(rows[0].value, "如何从少量观测恢复稀疏信号");
  assert.equal(rows[0].quote, "观测数远小于信号维度");
});

test("cardFieldRows 过滤缺失与空值字段，空引文不带 quote", () => {
  const rows = cardFieldRows({
    problem: field("问题值"),
    mechanism: field(""),
    contributions: [field("贡献值", "")],
    boundary: undefined,
  });
  assert.deepEqual(rows, [
    { label: "问题", value: "问题值" },
    { label: "主要贡献 1", value: "贡献值" },
  ]);
});

test("filterCards 空查询原样返回", () => {
  const entries = [entry(), entry({ paper_id: 3, title: "Field Study" })];
  assert.deepEqual(filterCards(entries, ""), entries);
  assert.deepEqual(filterCards(entries, "   "), entries);
});

test("filterCards 按题名子串不区分大小写匹配", () => {
  const entries = [entry(), entry({ paper_id: 3, title: "Field Study" })];
  assert.deepEqual(filterCards(entries, "sparse").map((e) => e.paper_id), [12]);
  assert.deepEqual(filterCards(entries, "FIELD").map((e) => e.paper_id), [3]);
  assert.deepEqual(filterCards(entries, "不存在").map((e) => e.paper_id), []);
});

test("filterCards 支持 P12 与 12 两种编号写法", () => {
  const entries = [entry(), entry({ paper_id: 3, title: "Field Study" })];
  assert.deepEqual(filterCards(entries, "P12").map((e) => e.paper_id), [12]);
  assert.deepEqual(filterCards(entries, "p12").map((e) => e.paper_id), [12]);
  assert.deepEqual(filterCards(entries, "3").map((e) => e.paper_id), [3]);
  assert.deepEqual(filterCards(entries, "P99").map((e) => e.paper_id), []);
});

test("cardToMarkdown 输出标题、元信息行与字段引文", () => {
  const text = cardToMarkdown(entry({ card: fullCard }), {
    year: 2019,
    venue: "IEEE TSP",
    doi: "10.1234/abc",
  });
  assert.match(text, /^# \[P12\] Sparse Recovery in Compressive Sensing\n/);
  assert.match(text, /2019 · IEEE TSP · DOI: 10\.1234\/abc/);
  assert.match(text, /\*\*问题：\*\*如何从少量观测恢复稀疏信号/);
  assert.match(text, /> 原文：“观测数远小于信号维度”/);
  assert.match(text, /\*\*主要贡献 3：\*\*实测数据验证/);
  assert.match(text, /\*\*判断边界：\*\*仅适用于高斯观测/);
  assert.ok(!text.includes("undefined"));
});

test("cardToMarkdown 无卡片时保留标题并输出卡片状态行", () => {
  const text = cardToMarkdown(entry(), { year: 2019 });
  assert.match(text, /^# \[P12\] Sparse Recovery in Compressive Sensing/);
  assert.match(text, /- 卡片状态：done/);
  assert.match(text, /2019/);
  assert.ok(!text.includes("IEEE"));
});

test("cardToMarkdown 不带 paper 参数时省略元信息行", () => {
  const text = cardToMarkdown(entry({ card: fullCard }));
  assert.match(text, /^# \[P12\]/);
  assert.match(text, /\*\*机制：\*\*凸优化 l1 最小化/);
  assert.ok(!text.includes("DOI"));
});
