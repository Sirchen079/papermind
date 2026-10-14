import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ENRICH_METADATA_CAP,
  FETCH_FULLTEXT_CAP,
  buildPaperIdsPayload,
  combineBulkResultMessage,
  enrichHasUpdates,
  fulltextHasAttachments,
  loadingReleaseBelongsTo,
  responseIsCurrent,
  selectionMatchesPaper,
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

// R07 回归：批量书目/全文操作后刷新当前视图的判定逻辑。
test("enrichHasUpdates is true only when at least one paper was actually updated", () => {
  assert.equal(enrichHasUpdates({ updated: 1 }), true);
  assert.equal(enrichHasUpdates({ updated: 3, no_doi: 2, unavailable: 1 }), true);
  assert.equal(enrichHasUpdates({ updated: 0, unchanged: 3 }), false);
  assert.equal(enrichHasUpdates({ no_doi: 4 }), false);
  assert.equal(enrichHasUpdates({}), false);
});

test("fulltextHasAttachments is true only when a PDF was actually attached", () => {
  assert.equal(fulltextHasAttachments({ attached: 2, failed: 1 }), true);
  assert.equal(fulltextHasAttachments({ attached: 1 }), true);
  assert.equal(fulltextHasAttachments({ attached: 0, no_open_access: 4 }), false);
  assert.equal(fulltextHasAttachments({ has_pdf: 2, failed: 1 }), false);
  assert.equal(fulltextHasAttachments({}), false);
});

test("responseIsCurrent drops stale responses once a newer request has been issued", () => {
  assert.equal(responseIsCurrent(5, 5), true);
  assert.equal(responseIsCurrent(5, 6), false);
  assert.equal(responseIsCurrent(6, 5), false);
});

test("selectionMatchesPaper keeps a newly selected paper when a slow detail response lands", () => {
  assert.equal(selectionMatchesPaper(7, 7), true);
  assert.equal(selectionMatchesPaper(8, 7), false);
  assert.equal(selectionMatchesPaper(undefined, 7), false);
  assert.equal(selectionMatchesPaper(null, 7), false);
});

test("combineBulkResultMessage keeps operation stats on the refreshed path", () => {
  const opMsg = summarizeEnrichResults({ updated: 3, unavailable: 1 });
  assert.equal(combineBulkResultMessage(opMsg, "refreshed"), opMsg);
});

test("combineBulkResultMessage reports refresh failure separately without asking to re-run", () => {
  const opMsg = summarizeEnrichResults({ updated: 3 });
  const failed = combineBulkResultMessage(opMsg, "failed");
  assert.ok(failed.startsWith(opMsg), "业务统计必须保留在提示最前");
  assert.ok(failed.includes("数据已保存"), "必须明确操作结果已保存");
  assert.ok(failed.includes("刷新失败"), "刷新失败必须与业务结果可区分");
  const stale = combineBulkResultMessage(opMsg, "stale");
  assert.ok(stale.startsWith(opMsg), "业务统计必须保留在提示最前");
  assert.ok(stale.includes("数据已保存"), "必须明确操作结果已保存");
});

test("combineBulkResultMessage keeps fulltext stats and never fakes read availability", () => {
  const opMsg = summarizeFulltextResults({ attached: 2, failed: 1 });
  const failed = combineBulkResultMessage(opMsg, "failed");
  assert.ok(failed.startsWith("已获取 2 篇公开全文"), "全文成功统计必须保留");
  assert.ok(failed.includes("数据已保存"), "必须明确操作结果已保存");
  assert.ok(failed.includes("刷新失败"), "刷新失败必须与业务结果可区分");
});

// R07/W04（F04 回归）：共享 loading 的所有权模型。每次发起请求（搜索/load/
// 批量刷新）setLoading(true) 并登记最新序号；请求结束时（成功或失败）仅当
// 自己仍是全局最新序号才 setLoading(false)。过期响应既不写数据也不动 loading；
// 抢占了序号的刷新在自身结束时负责解除。
test("loadingReleaseBelongsTo grants the shared loading release to the still-latest request only", () => {
  assert.equal(loadingReleaseBelongsTo(5, 5), true, "仍是最新序号的请求负责解除");
  assert.equal(loadingReleaseBelongsTo(5, 6), false, "被更新请求抢占后不得再动 loading");
  assert.equal(loadingReleaseBelongsTo(6, 5), false, "序号不存在的请求不得解除");
});

test("F04 timeline: refresh overtaking a pending search releases loading and the stale search stays inert", () => {
  // 验收时序回放：搜索挂起（补全触发的首查）→ 补全完成触发批量刷新（接管序号）
  // → 刷新先返回 → 原搜索延迟 4 秒返回。所有有效请求结束后 loading 必须为
  // false，导入抽屉「添加到论文库」才能恢复可用。
  let latestSeq = 0;
  let loading = false;
  const issue = () => { latestSeq += 1; loading = true; return latestSeq; };
  const finish = (seq) => { if (loadingReleaseBelongsTo(seq, latestSeq)) loading = false; };
  const searchSeq = issue();
  assert.equal(loading, true, "搜索发起后共享 loading 置位");
  const refreshSeq = issue();
  assert.equal(loading, true, "刷新发起即接管共享 loading");
  finish(refreshSeq);
  assert.equal(loading, false, "刷新完成后（它仍是最新序号）必须解除 loading——F04 残留点");
  finish(searchSeq);
  assert.equal(loading, false, "过期搜索返回后不得再次置位或残留 loading");
});

test("F04 timeline: stale search returning before the refresh still ends with loading released", () => {
  let latestSeq = 0;
  let loading = false;
  const issue = () => { latestSeq += 1; loading = true; return latestSeq; };
  const finish = (seq) => { if (loadingReleaseBelongsTo(seq, latestSeq)) loading = false; };
  const searchSeq = issue();
  const refreshSeq = issue();
  finish(searchSeq);
  assert.equal(loading, true, "过期搜索先返回时不得解除 loading（刷新仍在进行）");
  finish(refreshSeq);
  assert.equal(loading, false, "最后的有效请求（刷新）返回后必须解除 loading");
});

test("F04 timeline: consecutive interleaved searches leave loading released by the latest one", () => {
  let latestSeq = 0;
  let loading = false;
  const issue = () => { latestSeq += 1; loading = true; return latestSeq; };
  const finish = (seq) => { if (loadingReleaseBelongsTo(seq, latestSeq)) loading = false; };
  const first = issue();
  const second = issue();
  finish(second);
  assert.equal(loading, false, "最新搜索完成即解除 loading，不等待被抢占的旧搜索");
  finish(first);
  assert.equal(loading, false, "旧搜索随后返回不得再次置位 loading");
});

test("F04: a failing latest request still releases the shared loading via its finally path", () => {
  let latestSeq = 0;
  let loading = false;
  const issue = () => { latestSeq += 1; loading = true; return latestSeq; };
  const finish = (seq) => { if (loadingReleaseBelongsTo(seq, latestSeq)) loading = false; };
  const searchSeq = issue();
  const refreshSeq = issue();
  // 刷新请求本身失败：所有权判定只看序号，不看成败——失败也必须解除，
  // 否则刷新失败同样会让导入按钮永久禁用。
  finish(refreshSeq);
  assert.equal(loading, false, "刷新失败（仍是最新序号）也必须解除 loading");
  finish(searchSeq);
  assert.equal(loading, false, "过期搜索返回不得再次置位 loading");
});
