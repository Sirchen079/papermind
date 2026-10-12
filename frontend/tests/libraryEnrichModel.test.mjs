import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ENRICH_METADATA_CAP,
  FETCH_FULLTEXT_CAP,
  buildPaperIdsPayload,
  summarizeEnrichResults,
  summarizeFulltextResults,
} from "../.tmp_graph_test_dist/libraryEnrichModel.js";

test("paper id payload caps match the backend batch limits", () => {
  assert.equal(ENRICH_METADATA_CAP, 200);
  assert.equal(FETCH_FULLTEXT_CAP, 50);
});

test("buildPaperIdsPayload dedupes and keeps only positive integer ids", () => {
  assert.deepEqual(buildPaperIdsPayload([4, 4, -1, 2, 0, 2, 7.5], 10), [4, 2]);
  assert.deepEqual(buildPaperIdsPayload([], 10), []);
});

test("buildPaperIdsPayload returns null only when over cap", () => {
  assert.equal(buildPaperIdsPayload([1, 2, 3], 2), null);
  assert.deepEqual(buildPaperIdsPayload([1, 2], 2), [1, 2]);
  assert.deepEqual(buildPaperIdsPayload([1, 2, 3], 3), [1, 2, 3]);
});

test("summarizeEnrichResults renders counts in fixed status order", () => {
  assert.equal(
    summarizeEnrichResults({ updated: 12, no_doi: 3, not_found: 2, unchanged: 1 }),
    "补全完成:12 篇已更新,3 篇无 DOI,2 篇未找到,1 篇无变化",
  );
  assert.equal(
    summarizeEnrichResults({ updated: 2, unavailable: 1 }),
    "补全完成:2 篇已更新,1 篇查询失败",
  );
});

test("summarizeEnrichResults reports when no field was filled", () => {
  assert.equal(summarizeEnrichResults({ unchanged: 3, no_doi: 1 }), "没有补全到新字段");
  assert.equal(summarizeEnrichResults({}), "没有补全到新字段");
});

test("summarizeFulltextResults renders counts in fixed status order", () => {
  assert.equal(
    summarizeFulltextResults({ attached: 5, no_open_access: 8, has_pdf: 2, failed: 1 }),
    "已获取 5 篇公开全文,8 篇无公开获取,2 篇已有全文,1 篇失败",
  );
  assert.equal(
    summarizeFulltextResults({ attached: 0, no_doi: 2, not_found: 1 }),
    "已获取 0 篇公开全文,2 篇无 DOI,1 篇未找到",
  );
  assert.equal(summarizeFulltextResults({}), "已获取 0 篇公开全文");
});
