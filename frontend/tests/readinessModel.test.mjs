import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildFirstUseGuide,
  readinessLevelLabel,
  readinessStatusTone,
  summarizeReadinessChecks,
} from "../.tmp_graph_test_dist/readinessModel.js";

test("readiness model maps levels to Chinese labels", () => {
  assert.equal(readinessLevelLabel("setup"), "待配置");
  assert.equal(readinessLevelLabel("usable"), "可试用");
  assert.equal(readinessLevelLabel("ready"), "可持续使用");
  assert.equal(readinessLevelLabel("unknown"), "未知状态");
});

test("readiness model summarizes check counts and next action", () => {
  const summary = summarizeReadinessChecks([
    { id: "llm", status: "done", action: "配置 LLM", route: "settings" },
    { id: "library", status: "action", action: "导入论文", route: "library" },
    { id: "rag", status: "warning", action: "重建索引", route: "settings" },
  ]);

  assert.deepEqual(summary.counts, { done: 1, warning: 1, action: 1 });
  assert.deepEqual(summary.nextAction, { label: "导入论文", route: "library" });
});

test("readiness model uses stable tones for check statuses", () => {
  assert.equal(readinessStatusTone("done"), "success");
  assert.equal(readinessStatusTone("warning"), "warning");
  assert.equal(readinessStatusTone("action"), "danger");
  assert.equal(readinessStatusTone("other"), "muted");
});

test("readiness model groups checks into ordered onboarding milestones", () => {
  const guide = buildFirstUseGuide([
    { id: "llm", label: "LLM 模型", status: "done", action: "配置 LLM", route: "settings" },
    { id: "embedding", label: "向量模型", status: "action", action: "配置向量模型", route: "settings" },
    { id: "library", label: "论文库", status: "action", action: "导入论文", route: "library" },
    { id: "analysis", label: "AI 摘要与概念", status: "warning", action: "重新分析论文", route: "library" },
    { id: "rag", label: "全文检索 RAG", status: "warning", action: "重建索引", route: "settings" },
    { id: "graph", label: "知识图谱", status: "warning", action: "查看图谱", route: "graph" },
    { id: "reading", label: "阅读沉淀", status: "action", action: "进入阅读工作区", route: "library" },
    { id: "writing", label: "论文写作组织", status: "action", action: "组织写作材料", route: "library" },
  ]);

  assert.equal(guide.steps.length, 5);
  assert.deepEqual(
    guide.steps.map((step) => step.title),
    ["配置模型能力", "导入第一批论文", "生成摘要、图谱和检索索引", "开始精读沉淀", "建立论文写作结构"],
  );
  assert.equal(guide.completed, 0);
  assert.equal(guide.nextStep?.id, "models");
  assert.equal(guide.nextStep?.action, "配置向量模型");
  assert.equal(guide.nextStep?.route, "settings");
});

test("readiness model advances onboarding to the first unfinished milestone", () => {
  const guide = buildFirstUseGuide([
    { id: "llm", label: "LLM 模型", status: "done", action: "配置 LLM", route: "settings" },
    { id: "embedding", label: "向量模型", status: "done", action: "配置向量模型", route: "settings" },
    { id: "library", label: "论文库", status: "done", action: "导入论文", route: "library" },
    { id: "analysis", label: "AI 摘要与概念", status: "done", action: "重新分析论文", route: "library" },
    { id: "rag", label: "全文检索 RAG", status: "warning", action: "重建索引", route: "settings" },
    { id: "graph", label: "知识图谱", status: "done", action: "查看图谱", route: "graph" },
    { id: "reading", label: "阅读沉淀", status: "action", action: "进入阅读工作区", route: "library" },
    { id: "writing", label: "论文写作组织", status: "action", action: "组织写作材料", route: "library" },
  ]);

  assert.equal(guide.completed, 2);
  assert.equal(guide.nextStep?.id, "analysis");
  assert.equal(guide.nextStep?.status, "warning");
  assert.equal(guide.nextStep?.action, "重建索引");
  assert.equal(guide.percent, 40);
});
