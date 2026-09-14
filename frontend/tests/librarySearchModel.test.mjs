import assert from "node:assert/strict";
import { test } from "node:test";

import {
  SEARCH_DEBOUNCE_MS,
  isServerSearchActive,
  mergeSearchPage,
  normalizeSearchQuery,
  searchScopeNotice,
} from "../.tmp_graph_test_dist/librarySearchModel.js";

test("search query normalization trims and collapses whitespace", () => {
  assert.equal(normalizeSearchQuery(""), "");
  assert.equal(normalizeSearchQuery("   "), "");
  assert.equal(normalizeSearchQuery("  attention   networks  "), "attention networks");
});

test("server search activates only for non-blank queries", () => {
  assert.equal(isServerSearchActive(""), false);
  assert.equal(isServerSearchActive("   "), false);
  assert.equal(isServerSearchActive("attention"), true);
  assert.equal(isServerSearchActive("  图神经网络 "), true);
});

test("search debounce is a sane positive value", () => {
  assert.ok(SEARCH_DEBOUNCE_MS >= 200 && SEARCH_DEBOUNCE_MS <= 600);
});

test("search page merge replaces on first page and appends deduped after", () => {
  const first = [{ id: 1 }, { id: 2 }];
  const next = [{ id: 3 }, { id: 1 }];

  assert.deepEqual(mergeSearchPage(first, next, 0), next);
  assert.deepEqual(mergeSearchPage(first, next, 2), [{ id: 1 }, { id: 2 }, { id: 3 }]);
});

test("search scope notice reports whole-library match with client-filter caveat", () => {
  assert.equal(
    searchScopeNotice({ serverActive: true, loaded: 10, total: 42 }),
    "已匹配全库 42 篇，当前加载 10 篇；阅读状态等筛选只作用于已加载部分。",
  );
  assert.equal(searchScopeNotice({ serverActive: true, loaded: 42, total: 42 }), null);
  assert.equal(searchScopeNotice({ serverActive: false, loaded: 3, total: 40 }), null);
});
