import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildGraphHash,
  graphLabel,
  nodeVisualStyle,
  nodeMetrics,
  parseGraphParamsFromHash,
  visualWidth,
  wrapGraphLabel,
} from "../.tmp_graph_test_dist/graphModel.js";

test("graph hash keeps concept mode and min paper filter addressable", () => {
  assert.deepEqual(parseGraphParamsFromHash("#graph?mode=concept&min_papers=3"), {
    mode: "concept",
    minPapers: 3,
  });
  assert.equal(buildGraphHash("concept", 3), "#graph?mode=concept&min_papers=3");
  assert.equal(buildGraphHash("paper", 9), "#graph");
});

test("concept labels are manually wrapped before cytoscape renders them", () => {
  const longConcept = "多模态大语言模型检索增强生成与知识图谱推理";
  const lines = wrapGraphLabel(longConcept, "concept");

  assert.ok(lines.length >= 2);
  assert.ok(lines.length <= 3);
  assert.ok(lines.every((line) => visualWidth(line.replace("...", "")) <= 12));
  assert.equal(graphLabel(longConcept, "concept"), lines.join("\n"));
});

test("concept node metrics leave room for wrapped Chinese labels", () => {
  const label = "多模态大语言模型检索增强生成与知识图谱推理";
  const lines = wrapGraphLabel(label, "concept");
  const metrics = nodeMetrics(label, 5, "concept");
  const longestLine = Math.max(...lines.map(visualWidth));

  assert.ok(metrics.textMaxWidth >= longestLine * 14);
  assert.ok(metrics.height >= 24 + lines.length * 21);
  assert.ok(metrics.width < 240, 'wrapped concept labels do not require oversized blocks');
  assert.ok(metrics.textMaxWidth <= metrics.width - 26);
});

test("graph nodes use readable rectangular tag styling instead of circular color blobs", () => {
  const concept = nodeVisualStyle("concept", "light", "method");
  assert.equal(concept.shape, "round-rectangle");
  assert.notEqual(concept.borderColor, concept.backgroundColor);
  assert.notEqual(concept.textColor, concept.backgroundColor);

  const paper = nodeVisualStyle("paper", "dark", null);
  assert.equal(paper.shape, "round-rectangle");
  assert.notEqual(paper.borderColor, paper.backgroundColor);
  assert.notEqual(paper.textColor, paper.backgroundColor);
});
