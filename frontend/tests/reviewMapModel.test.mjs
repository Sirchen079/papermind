import assert from "node:assert/strict";
import { test } from "node:test";

import {
  addTheme,
  fieldLocation,
  filterPapers,
  mergeThemes,
  removeTheme,
  renameTheme,
  statusLabel,
} from "../.tmp_graph_test_dist/reviewMapModel.js";

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

test("mergeThemes 删除被合并主题、新增不带 id 的主题、定义拼接且不改入参", () => {
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
  assert.equal(merged[1].id, "");
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
  assert.equal(added[2].id, "");
  assert.equal(added[2].name, "新主题");
  assert.equal(themes.length, 2);
});
