import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_IMPORT_BATCH_CAP,
  authorLine,
  canImportCandidate,
  candidateSourceLabel,
  candidateStatusLabel,
  clampChoice,
  importActive,
  selectionWithinCap,
  surveyActive,
  surveyQueryValid,
  surveyStatusLabel,
} from "../.tmp_graph_test_dist/literatureModel.js";

test("survey query must be non-empty and bounded", () => {
  assert.equal(surveyQueryValid(""), false);
  assert.equal(surveyQueryValid("   "), false);
  assert.equal(surveyQueryValid("近两年 FWI 目标函数"), true);
  assert.equal(surveyQueryValid("x".repeat(501)), false);
});

test("survey and import activity flags drive polling", () => {
  assert.equal(surveyActive("queued"), true);
  assert.equal(surveyActive("running"), true);
  assert.equal(surveyActive("ready"), false);
  assert.equal(importActive({ import_status: "running", counts: {} }), true);
  assert.equal(importActive({ import_status: "idle", counts: { queued_import: 2 } }), true);
  assert.equal(importActive({ import_status: "done", counts: { imported: 2 } }), false);
  assert.equal(importActive(null), false);
});

test("only fresh or failed candidates can be selected for import", () => {
  assert.equal(canImportCandidate("candidate"), true);
  assert.equal(canImportCandidate("failed"), true);
  assert.equal(canImportCandidate("imported"), false);
  assert.equal(canImportCandidate("duplicate"), false);
  assert.equal(canImportCandidate("queued_import"), false);
});

test("selection must stay within the backend batch cap", () => {
  assert.equal(selectionWithinCap(0), false);
  assert.equal(selectionWithinCap(1), true);
  assert.equal(selectionWithinCap(DEFAULT_IMPORT_BATCH_CAP), true);
  assert.equal(selectionWithinCap(DEFAULT_IMPORT_BATCH_CAP + 1), false);
  assert.equal(selectionWithinCap(3, 2), false);
});

test("status labels stay in Chinese for the board", () => {
  assert.equal(surveyStatusLabel("running"), "正在调研");
  assert.equal(surveyStatusLabel("interrupted"), "已中断");
  assert.equal(candidateStatusLabel("imported_no_pdf"), "已入库（仅题录）");
  assert.equal(candidateStatusLabel("duplicate"), "库中已有");
  assert.equal(surveyStatusLabel("weird-status"), "weird-status");
});

test("candidate source badge reflects OA availability", () => {
  assert.equal(candidateSourceLabel({ oa_pdf_url: "https://x.test/a.pdf", arxiv_id: "" }), "公开全文");
  assert.equal(candidateSourceLabel({ oa_pdf_url: null, arxiv_id: "2401.00001" }), "公开全文");
  assert.equal(candidateSourceLabel({ oa_pdf_url: null, arxiv_id: "" }), "仅题录");
});

test("author line truncates beyond the limit", () => {
  assert.equal(authorLine([]), "");
  assert.equal(authorLine(["张三", "李四", "王五", "赵六"]), "张三、李四、王五 等 4 人");
  assert.equal(authorLine(["张三"]), "张三");
});

test("form choices fall back to defaults when invalid", () => {
  assert.equal(clampChoice(3, [1, 2, 3, 5], 2), 3);
  assert.equal(clampChoice(4, [1, 2, 3, 5], 2), 2);
  assert.equal(clampChoice("2", [1, 2, 3, 5], 2), 2);
});
