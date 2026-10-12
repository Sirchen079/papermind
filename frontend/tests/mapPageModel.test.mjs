import assert from "node:assert/strict";
import { test } from "node:test";

import { pickInitialReview } from "../.tmp_graph_test_dist/mapPageModel.js";

const rows = [{ id: "r1" }, { id: "r2" }, { id: "r3" }];

test("pickInitialReview 无上次选中与深链参数时选第一项", () => {
  assert.equal(pickInitialReview("", "", rows), "r1");
});

test("pickInitialReview 上次选中仍存在时保留", () => {
  assert.equal(pickInitialReview("r2", "", rows), "r2");
  // 上次选中与深链参数都有效时，保留当前选中，不打断浏览。
  assert.equal(pickInitialReview("r2", "r3", rows), "r2");
});

test("pickInitialReview 上次选中已不存在时用深链参数兜底", () => {
  assert.equal(pickInitialReview("r9", "r3", rows), "r3");
  assert.equal(pickInitialReview("", "r3", rows), "r3");
});

test("pickInitialReview 深链参数不在列表或为空时不选中", () => {
  assert.equal(pickInitialReview("", "r9", rows), "r1");
  assert.equal(pickInitialReview("r9", "", rows), "r1");
});

test("pickInitialReview 空列表返回空串", () => {
  assert.equal(pickInitialReview("", "", []), "");
  assert.equal(pickInitialReview("r1", "", []), "");
});
