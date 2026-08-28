import assert from "node:assert/strict";
import { test } from "node:test";

import {
  restoreGuideStatusLabel,
  restoreGuideTone,
} from "../.tmp_graph_test_dist/archiveModel.js";

test("archive model maps restore guide status to Chinese labels", () => {
  assert.equal(restoreGuideStatusLabel(true), "可按指南恢复");
  assert.equal(restoreGuideStatusLabel(false), "不建议恢复");
});

test("archive model maps restore guide status to stable tones", () => {
  assert.equal(restoreGuideTone(true), "success");
  assert.equal(restoreGuideTone(false), "danger");
});
