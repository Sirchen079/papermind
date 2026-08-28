import assert from "node:assert/strict";
import { test } from "node:test";

import {
  progressPriorityLabel,
  progressPriorityTone,
  researchProgressMarkdownExportUrl,
  summarizeProgressActions,
} from "../.tmp_graph_test_dist/researchProgressModel.js";

test("research progress model maps priorities to Chinese labels", () => {
  assert.equal(progressPriorityLabel("high"), "优先处理");
  assert.equal(progressPriorityLabel("normal"), "建议推进");
  assert.equal(progressPriorityLabel("low"), "持续维护");
  assert.equal(progressPriorityLabel("other"), "待处理");
});

test("research progress model maps priorities to stable tones", () => {
  assert.equal(progressPriorityTone("high"), "danger");
  assert.equal(progressPriorityTone("normal"), "warning");
  assert.equal(progressPriorityTone("low"), "success");
  assert.equal(progressPriorityTone("other"), "muted");
});

test("research progress model summarizes actions by priority", () => {
  assert.deepEqual(
    summarizeProgressActions([
      { id: "a", priority: "high" },
      { id: "b", priority: "normal" },
      { id: "c", priority: "normal" },
      { id: "d", priority: "low" },
    ]),
    { high: 1, normal: 2, low: 1 },
  );
});

test("research progress model builds markdown export urls", () => {
  assert.equal(researchProgressMarkdownExportUrl(), "/api/research/progress/markdown");
  assert.equal(researchProgressMarkdownExportUrl("/custom-api/"), "/custom-api/research/progress/markdown");
});
