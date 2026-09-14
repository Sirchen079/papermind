import assert from "node:assert/strict";
import { test } from "node:test";

import {
  captureFlow,
  ideaPayloadFromAnswer,
  ideaTitleFromAnswer,
  notePayloadFromAnswer,
  resolveCapturePaper,
} from "../.tmp_graph_test_dist/chatCaptureModel.js";

const SOURCES = [
  { paper_id: 11, title: "论文 A" },
  { paper_id: 12, title: "论文 B" },
];

test("capture flow prefers the active paper context", () => {
  assert.deepEqual(captureFlow(7, SOURCES), { flow: "paper", paperId: 7 });
});

test("capture flow asks the user to pick when only RAG sources exist", () => {
  assert.deepEqual(captureFlow(null, SOURCES), { flow: "pick", sources: SOURCES });
});

test("capture flow is free without context or sources", () => {
  assert.deepEqual(captureFlow(null, []), { flow: "free" });
});

test("capture paper resolution never silently picks the first source", () => {
  const flow = captureFlow(null, SOURCES);
  assert.equal(resolveCapturePaper(flow, null), "required");
  assert.equal(resolveCapturePaper(flow, 12), 12);
  assert.equal(resolveCapturePaper(captureFlow(7, SOURCES), null), 7);
  assert.equal(resolveCapturePaper(captureFlow(null, []), null), null);
  assert.equal(resolveCapturePaper(captureFlow(null, []), 12), 12);
});

test("note payload reuses reading notes contract", () => {
  assert.deepEqual(notePayloadFromAnswer("回答内容"), { kind: "note", content: "回答内容", tags: [] });
});

test("idea payload derives a bounded title and links the chosen paper", () => {
  const payload = ideaPayloadFromAnswer("第一行结论\n第二行细节", 11);
  assert.equal(payload.title, "第一行结论");
  assert.equal(payload.origin, "manual");
  assert.deepEqual(payload.papers, [{ paper_id: 11, role: "basis" }]);

  const withoutPaper = ideaPayloadFromAnswer("回答", null);
  assert.equal(withoutPaper.papers, undefined);
});

test("idea title falls back and caps length", () => {
  assert.equal(ideaTitleFromAnswer("  \n\n  "), "来自对话的研究想法");
  const long = "长".repeat(80);
  const title = ideaTitleFromAnswer(long);
  assert.equal(title.length, 60);
  assert.ok(title.endsWith("…"));
});
