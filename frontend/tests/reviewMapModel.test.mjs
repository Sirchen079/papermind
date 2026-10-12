import assert from "node:assert/strict";
import { test } from "node:test";

import {
  addTheme,
  fieldLocation,
  filterPapers,
  ideaHandoff,
  mergeThemes,
  removeTheme,
  renameTheme,
  researchHandoff,
  statusLabel,
  themesForSave,
} from "../.tmp_graph_test_dist/reviewMapModel.js";

test("statusLabel 按相似度区分近似核对", () => {
  assert.equal(statusLabel("quote_verified", 0.95), "近似核对原文");
  assert.equal(statusLabel("quote_verified", 1), "已核对原文");
  assert.equal(statusLabel("quote_verified"), "已核对原文");
});

test("statusLabel 覆盖全部核对状态", () => {
  assert.equal(statusLabel("quote_verified"), "已核对原文");
  assert.equal(statusLabel("number_mismatch"), "数字与原文不符");
  assert.equal(statusLabel("quote_not_found"), "未在原文找到引文");
  assert.equal(statusLabel("no_quote"), "模型归纳");
  assert.equal(statusLabel("unverifiable"), "仅元数据，无法核对");
  assert.equal(statusLabel(""), "");
});

test("fieldLocation 三种情况：页码、摘要、无定位", () => {
  assert.deepEqual(fieldLocation({ value: "v", quote: "q", status: "quote_verified", pages: [3] }), {
    page: 3,
    text: "第 3 页",
  });
  assert.deepEqual(
    fieldLocation({ value: "v", quote: "q", status: "quote_verified", found_in: "abstract" }),
    { text: "摘要" },
  );
  assert.deepEqual(fieldLocation({ value: "v", quote: "q", status: "no_quote" }), { text: "" });
});

const papers = [
  {
    paper_id: 1,
    title: "Sparse Recovery",
    doi: "10.1000/one",
    themes: ["T1"],
    evidence_level: "full_text",
    card_status: "done",
    fields: [{ value: "v", quote: "q", status: "quote_verified" }],
  },
  {
    paper_id: 2,
    title: "Retrieval Augmented",
    doi: "10.1000/two",
    themes: ["T2"],
    evidence_level: "abstract",
    card_status: "done",
    fields: [
      { value: "v", quote: "q", status: "number_mismatch", missing_numbers: ["52.7"] },
      { value: "v2", quote: "q2", status: "quote_verified" },
    ],
  },
  {
    paper_id: 3,
    title: "Field Study",
    doi: null,
    themes: ["T1", "T2"],
    evidence_level: "metadata",
    card_status: "pending",
    fields: [],
  },
];

test("filterPapers 按关键词、主题、证据级别、需核对筛选", () => {
  assert.deepEqual(
    filterPapers(papers, { query: "retrieval" }).map((p) => p.paper_id),
    [2],
  );
  assert.deepEqual(filterPapers(papers, { query: "10.1000/one" }).map((p) => p.paper_id), [1]);
  assert.deepEqual(filterPapers(papers, { theme: "T1" }).map((p) => p.paper_id), [1, 3]);
  assert.deepEqual(filterPapers(papers, { evidence: "abstract" }).map((p) => p.paper_id), [2]);
  assert.deepEqual(filterPapers(papers, { status: "needs_check" }).map((p) => p.paper_id), [2]);
  assert.deepEqual(filterPapers(papers, { theme: "T1", evidence: "metadata" }).map((p) => p.paper_id), [3]);
  assert.equal(filterPapers(papers, {}).length, 3);
});

test("mergeThemes 删除被合并主题、新增带临时 id 的主题、定义拼接且不改入参", () => {
  const themes = [
    { id: "T1", name: "稀疏恢复", definition: "定义一", include: "a", exclude: "b" },
    { id: "T2", name: "检索增强", definition: "定义二", include: "c", exclude: "d" },
    { id: "T3", name: "其他", definition: "定义三", include: "", exclude: "" },
  ];
  const snapshot = JSON.parse(JSON.stringify(themes));
  const merged = mergeThemes(themes, ["T1", "T2"], "合并主题");
  assert.deepEqual(themes, snapshot); // 入参未被修改
  assert.equal(merged.length, 2);
  assert.deepEqual(merged[0], themes[2]);
  assert.equal(merged[1].id, "new-1");
  assert.equal(merged[1].name, "合并主题");
  assert.equal(merged[1].definition, "定义一；定义二");
});

test("removeTheme、renameTheme、addTheme 返回新数组", () => {
  const themes = [
    { id: "T1", name: "稀疏恢复", definition: "d1" },
    { id: "T2", name: "检索增强", definition: "d2" },
  ];
  const removed = removeTheme(themes, "T1");
  assert.deepEqual(removed.map((t) => t.id), ["T2"]);
  assert.equal(themes.length, 2);
  const renamed = renameTheme(themes, "T2", "改名");
  assert.equal(renamed[1].name, "改名");
  assert.equal(themes[1].name, "检索增强");
  const added = addTheme(themes, "新主题");
  assert.equal(added.length, 3);
  assert.equal(added[2].id, "new-1");
  assert.equal(added[2].name, "新主题");
  assert.equal(themes.length, 2);
});

test("新增与合并的主题各有临时 id，改名、删除、合并只作用于一条", () => {
  let draft = [{ id: "T1", name: "甲", definition: "d1" }, { id: "T2", name: "乙", definition: "d2" }];
  draft = addTheme(draft, "新一");
  draft = addTheme(draft, "新二");
  assert.deepEqual(draft.map((t) => t.id), ["T1", "T2", "new-1", "new-2"]);
  draft = renameTheme(draft, "new-1", "新一改");
  assert.deepEqual(draft.map((t) => t.name), ["甲", "乙", "新一改", "新二"]);
  draft = mergeThemes(draft, ["new-2", "T2"], "合并");
  assert.deepEqual(draft.map((t) => t.id), ["T1", "new-1", "new-3"]); // 不复用刚被合并掉的 id
  assert.equal(draft[2].name, "合并");
  draft = removeTheme(draft, "new-1");
  assert.deepEqual(draft.map((t) => t.name), ["甲", "合并"]);
});

test("themesForSave 去掉临时 id 交给后端编号，保留已有编号且不改入参", () => {
  const draft = [{ id: "T1", name: "甲", definition: "d1" }, { id: "new-1", name: "乙", definition: "" }];
  const saved = themesForSave(draft);
  assert.deepEqual(saved.map((t) => t.id), ["T1", ""]);
  assert.equal(saved[1].name, "乙");
  assert.equal(draft[1].id, "new-1");
});

test("researchHandoff 把值得研究的问题连同依据论文带入研究对话", () => {
  const handoff = researchHandoff("弹性多参数", {
    question: "多参数串扰在实测数据上是否仍未解决？",
    why: "多数结果来自合成模型",
    cannot_claim: "合成例子成功不能证明全局收敛",
    cards: [12, 7, 12],
  }, [7, 30, 31, 32, 33, 34, 35]);
  assert.deepEqual(handoff.paperIds, [12, 7, 30, 31, 32, 33]);
  assert.match(handoff.question, /「弹性多参数」/);
  assert.match(handoff.question, /多参数串扰在实测数据上是否仍未解决？/);
  assert.match(handoff.question, /依据：多数结果来自合成模型/);
  assert.match(handoff.question, /现有证据的缺口：合成例子成功不能证明全局收敛/);
  assert.match(handoff.question, /最小可行的验证方案/);
});

test("researchHandoff 处理方法组合机会，缺少字段时不输出空行", () => {
  const handoff = researchHandoff("生成式先验", { idea: "扩散先验结合不确定性估计", cards: [] }, []);
  assert.deepEqual(handoff.paperIds, []);
  assert.match(handoff.question, /方法组合机会/);
  assert.match(handoff.question, /扩散先验结合不确定性估计/);
  assert.ok(!handoff.question.includes("预期收益"), "缺少字段时不输出该行");
  assert.ok(!handoff.question.includes("undefined"));
});

test("researchHandoff 题干不超过对话输入上限", () => {
  const handoff = researchHandoff("长", { question: "问".repeat(5000), why: "因".repeat(500), cards: [1] }, []);
  assert.ok(handoff.question.length <= 2000);
});

test("ideaHandoff 拼装问题类想法的字段并合并去重论文", () => {
  const out = ideaHandoff("弹性多参数", {
    question: "多参数串扰在实测数据上是否仍未解决？",
    why: "多数结果来自合成模型",
    cannot_claim: "合成例子成功不能证明全局收敛",
    cards: [12, 7, 12],
  }, [7, 30, 31, 32, 33, 34, 35]);
  assert.equal(out.title, "多参数串扰在实测数据上是否仍未解决？");
  assert.ok(out.content.includes("多参数串扰在实测数据上是否仍未解决？"));
  assert.ok(out.content.includes("地图给出的依据：多数结果来自合成模型"));
  assert.ok(out.content.includes("现有证据的缺口：合成例子成功不能证明全局收敛"));
  assert.ok(out.content.endsWith("来源：文献地图主题「弹性多参数」"));
  assert.ok(!out.content.includes("预期收益"), "问题类想法不出现组合字段");
  assert.deepEqual(out.paperIds, [12, 7, 30, 31, 32, 33]);
});

test("ideaHandoff 拼装组合类想法，空字段行跳过", () => {
  const out = ideaHandoff("生成式先验", {
    idea: "扩散先验结合不确定性估计",
    expected: "减少标注需求",
    cards: [],
  }, []);
  assert.equal(out.title, "扩散先验结合不确定性估计");
  assert.ok(out.content.includes("预期收益：减少标注需求"));
  assert.ok(out.content.endsWith("来源：文献地图主题「生成式先验」"));
  assert.ok(!out.content.includes("地图提示的风险"), "缺少风险时不输出该行");
  assert.ok(!out.content.includes("undefined"));
  assert.deepEqual(out.paperIds, []);
});
