import assert from "node:assert/strict";
import { test } from "node:test";

import {
  cardCheckSummary,
  cardFieldRows,
  cardRowQuoteLabel,
  cardRowStatusText,
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

// R02 复现输入：数字与原文不符的字段（返工任务书原样输入）。
const mismatchField = {
  value: "Accuracy 99.9%",
  quote: "Accuracy was 52.7% on the test set.",
  status: "number_mismatch",
  missing_numbers: ["99.9"],
  pages: [7],
  found_in: "full_text",
};

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
  // R02 契约扩展：行携带核验状态等字段；此处保留原断言意图（过滤/空引文）并按新行结构验证。
  assert.deepEqual(
    rows.map((r) => ({ label: r.label, value: r.value, quote: r.quote ?? null })),
    [
      { label: "问题", value: "问题值", quote: null },
      { label: "主要贡献 1", value: "贡献值", quote: null },
    ],
  );
  for (const row of rows) {
    assert.equal(row.problem, false, "正常核验字段不产生警告标记");
    assert.equal(row.statusText, "已核对原文");
    assert.deepEqual(row.missingNumbers, []);
    assert.equal(row.locationText, "");
    assert.equal(row.page, undefined);
  }
});

test("R02 复现输入：行模型保留数字不匹配、缺少 99.9 与第 7 页定位", () => {
  const rows = cardFieldRows({ problem: mismatchField });
  assert.equal(rows.length, 1);
  const row = rows[0];
  assert.equal(row.status, "number_mismatch");
  assert.equal(row.problem, true);
  assert.deepEqual(row.missingNumbers, ["99.9"]);
  assert.equal(row.page, 7);
  assert.equal(row.locationText, "第 7 页");
  assert.equal(row.quote, "Accuracy was 52.7% on the test set.");
  const status = cardRowStatusText(row);
  assert.match(status, /数字与原文不符/);
  assert.match(status, /缺少 99\.9/);
  assert.match(status, /第 7 页/);
});

test("R02 复现输入：Markdown 导出可见数字不匹配、99.9 与第 7 页", () => {
  const text = cardToMarkdown(entry({ card: { problem: mismatchField } }));
  assert.match(text, /\*\*问题：\*\*Accuracy 99\.9%/);
  assert.match(text, /数字与原文不符：缺少 99\.9（第 7 页）/);
  assert.match(text, /Accuracy was 52\.7% on the test set\./);
  assert.match(text, /字段核对：1 项需注意/);
});

test("R02 正常核验字段显示已核对原文，不产生假警告", () => {
  const verified = {
    value: "凸优化恢复",
    quote: "we convexify the recovery",
    status: "quote_verified",
    pages: [3],
    found_in: "full_text",
  };
  const row = cardFieldRows({ mechanism: verified })[0];
  assert.equal(row.problem, false);
  assert.equal(row.statusText, "已核对原文");
  assert.equal(cardRowStatusText(row), "已核对原文（第 3 页）");
  assert.equal(cardRowQuoteLabel(row), "原文");
  const text = cardToMarkdown(entry({ card: { mechanism: verified } }));
  assert.match(text, /已核对原文（第 3 页）/);
  assert.match(text, /> 原文：“we convexify the recovery”/);
  assert.ok(!text.includes("⚠"), "正常核验不得出现警告标记");
});

test("R02 近似核对仍属正常核验显示，不算警告", () => {
  const fuzzy = { value: "l1 最小化", quote: "l1 minimization approach", status: "quote_verified", similarity: 0.93 };
  const row = cardFieldRows({ mechanism: fuzzy })[0];
  assert.equal(row.problem, false);
  assert.equal(row.statusText, "近似核对原文");
  assert.ok(!cardToMarkdown(entry({ card: { mechanism: fuzzy } })).includes("⚠"));
});

test("R02 缺失/未知状态不被当作核验通过，引文不包装成原文", () => {
  const noStatus = { value: "仅小样本适用", quote: "small samples only" };
  const row = cardFieldRows({ boundary: noStatus })[0];
  assert.equal(row.status, "");
  assert.equal(row.problem, false, "缺失状态不是检测到的问题，但也不算通过");
  assert.equal(row.statusText, "未记录核验状态");
  assert.equal(cardRowQuoteLabel(row), "引文");
  const text = cardToMarkdown(entry({ card: { boundary: noStatus } }));
  assert.match(text, /未记录核验状态/);
  assert.ok(!text.includes("已核对原文"), "缺失状态不得显示已核对");
  assert.match(text, /引文：“small samples only”/);
  assert.ok(!text.includes("原文：“small samples only”"), "未核验引文不得标成原文");

  const unknown = { value: "未知状态", quote: "quote", status: "some_future_status" };
  const row2 = cardFieldRows({ mechanism: unknown })[0];
  assert.notEqual(row2.statusText, "已核对原文");
  assert.equal(cardRowQuoteLabel(row2), "引文");
});

test("R02 未找到引文时给中文警告且引文不标原文", () => {
  const notFound = { value: "收敛快 3 倍", quote: "converges 3x faster", status: "quote_not_found" };
  const row = cardFieldRows({ mechanism: notFound })[0];
  assert.equal(row.problem, true);
  assert.equal(row.statusText, "未在原文找到引文");
  const text = cardToMarkdown(entry({ card: { mechanism: notFound } }));
  assert.match(text, /⚠ 未在原文找到引文/);
  assert.ok(!text.includes("原文：“converges"), "未找到的引文不得标成原文");
  assert.match(text, /引文：“converges 3x faster”/);
});

test("R02 兼容：只有摘要定位时不编造页码", () => {
  const abstractOnly = {
    value: "准确率提升",
    quote: "improves accuracy on benchmarks",
    status: "quote_verified",
    found_in: "abstract",
    pages: [],
  };
  const row = cardFieldRows({ problem: abstractOnly })[0];
  assert.equal(row.locationText, "摘要");
  assert.equal(row.page, undefined);
  const text = cardToMarkdown(entry({ card: { problem: abstractOnly } }));
  assert.match(text, /已核对原文（摘要）/);
  assert.ok(!/第 \d+ 页/.test(text), "无真实页码不得输出页码定位");
});

test("R02 兼容：全文命中但无页码时定位为空且不编造", () => {
  const noPages = {
    value: "方法有效",
    quote: "the method works well",
    status: "quote_verified",
    found_in: "full_text",
    pages: [],
  };
  const row = cardFieldRows({ problem: noPages })[0];
  assert.equal(row.locationText, "");
  assert.equal(row.page, undefined);
  assert.equal(cardRowStatusText(row), "已核对原文");
});

test("R02 兼容：无引文字段不输出引文行，状态显示模型归纳", () => {
  const noQuote = { value: "纯模型归纳内容", quote: "", status: "no_quote" };
  const row = cardFieldRows({ mechanism: noQuote })[0];
  assert.equal(row.quote, undefined);
  assert.equal(row.problem, false);
  assert.equal(row.statusText, "模型归纳");
  const text = cardToMarkdown(entry({ card: { mechanism: noQuote } }));
  assert.match(text, /模型归纳/);
  assert.ok(!text.includes("原文：“"));
  assert.ok(!text.includes("引文：“"));
});

test("R02 兼容：旧卡片缺少可选字段（仅 value/quote/status）可用且无假定位", () => {
  const rows = cardFieldRows({ problem: { value: "旧卡片字段", quote: "old quote text", status: "quote_verified" } });
  assert.equal(rows.length, 1);
  const row = rows[0];
  assert.deepEqual(row.missingNumbers, []);
  assert.equal(row.locationText, "");
  assert.equal(row.page, undefined);
  assert.equal(row.statusText, "已核对原文");
  const text = cardToMarkdown(entry({ card: { problem: { value: "旧卡片字段", quote: "old quote text", status: "quote_verified" } } }));
  assert.match(text, /\*\*问题：\*\*旧卡片字段/);
  assert.match(text, /> 原文：“old quote text”/);
});

test("R02 整卡完成与字段核对分开：摘要只统计需注意字段", () => {
  assert.equal(cardCheckSummary(null), "");
  assert.equal(cardCheckSummary(fullCard), "");
  assert.equal(cardCheckSummary({ problem: mismatchField, mechanism: field("正常字段") }), "字段核对：1 项需注意");
  assert.equal(
    cardCheckSummary({ problem: mismatchField, mechanism: mismatchField }),
    "字段核对：2 项需注意",
  );
  // 空值字段不进入行也不计入
  assert.equal(cardCheckSummary({ problem: { value: "  ", status: "number_mismatch", missing_numbers: ["1"] } }), "");
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
