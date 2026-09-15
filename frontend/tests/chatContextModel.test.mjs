import assert from "node:assert/strict";
import { test } from "node:test";

import {
  SELECTED_TEXT_LIMIT,
  chatMessagePayload,
  consumeSelection,
  contextBadgeLabel,
  selectedTextOverLimit,
} from "../.tmp_graph_test_dist/chatContextModel.js";

test("chat context detects over-limit selected text", () => {
  assert.equal(selectedTextOverLimit(null), false);
  assert.equal(selectedTextOverLimit(""), false);
  assert.equal(selectedTextOverLimit("x".repeat(SELECTED_TEXT_LIMIT)), false);
  assert.equal(selectedTextOverLimit("x".repeat(SELECTED_TEXT_LIMIT + 1)), true);
});

test("chat context badge names the paper and selection state", () => {
  assert.equal(
    contextBadgeLabel({ paperId: 7, paperTitle: "Attention 论文", selectedText: null }),
    "正在就《Attention 论文》提问",
  );
  assert.equal(
    contextBadgeLabel({ paperId: 7, paperTitle: "Attention 论文", selectedText: "选中句" }),
    "正在就《Attention 论文》选中的内容提问",
  );
  assert.equal(
    contextBadgeLabel({ paperId: 9, paperTitle: null, selectedText: null }),
    "正在就《论文 #9》提问",
  );
});

test("chat message payload keeps legacy shape without context", () => {
  assert.deepEqual(chatMessagePayload("你好", null), { content: "你好" });
});

test("chat message payload carries paper id and bounded selection", () => {
  assert.deepEqual(
    chatMessagePayload("这篇论文的方法可靠吗", {
      paperId: 5,
      paperTitle: "T",
      selectedText: null,
    }),
    { content: "这篇论文的方法可靠吗", paper_id: 5 },
  );
  assert.deepEqual(
    chatMessagePayload("解释这段", { paperId: 5, paperTitle: "T", selectedText: "关键句" }),
    { content: "解释这段", paper_id: 5, selected_text: "关键句" },
  );
});

test("chat message payload drops over-limit selection instead of failing the send", () => {
  const payload = chatMessagePayload("解释这段", {
    paperId: 5,
    paperTitle: "T",
    selectedText: "x".repeat(SELECTED_TEXT_LIMIT + 100),
  });
  assert.deepEqual(payload, { content: "解释这段", paper_id: 5 });
});

test("chat context selection is consumed once and paper id persists", () => {
  const ctx = { paperId: 5, paperTitle: "T", selectedText: "选中句" };
  const afterFirst = consumeSelection(ctx);
  assert.equal(afterFirst.selectedText, null);
  assert.equal(afterFirst.paperId, 5);
  // 再次消费是幂等的。
  assert.deepEqual(consumeSelection(afterFirst), afterFirst);
});
