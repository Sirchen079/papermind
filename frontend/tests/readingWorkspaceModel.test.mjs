import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildExcerptPayload,
  buildExcerptNotePayload,
  buildNotePayload,
  emptyReaderNoteDraft,
  mergeMatrixSuggestion,
  readerNoteDraftError,
} from "../.tmp_graph_test_dist/readingWorkspaceModel.js";

test("reading note payload trims content and splits tags", () => {
  assert.deepEqual(
    buildNotePayload({
      kind: "idea",
      content: "  可用于第二章的问题定义  ",
      tags: "综述, 问题定义,  ",
    }),
    { kind: "idea", content: "可用于第二章的问题定义", tags: ["综述", "问题定义"] },
  );
});

test("reading note payload rejects empty content", () => {
  assert.equal(buildNotePayload({ kind: "note", content: "   ", tags: "x" }), null);
});

test("excerpt payload normalizes optional fields", () => {
  assert.deepEqual(
    buildExcerptPayload({
      quote: "  important quote  ",
      page: "12",
      section: "  Method  ",
      locator: "  para 2  ",
      note: "  baseline evidence  ",
      tags: "方法,证据",
    }),
    {
      quote: "important quote",
      page: 12,
      section: "Method",
      locator: "para 2",
      note: "baseline evidence",
      tags: ["方法", "证据"],
    },
  );
});

test("excerpt payload rejects empty quote and invalid page", () => {
  assert.equal(
    buildExcerptPayload({ quote: "", page: "1", section: "", locator: "", note: "", tags: "" }),
    null,
  );
  assert.equal(
    buildExcerptPayload({ quote: "quote", page: "0", section: "", locator: "", note: "", tags: "" }),
    null,
  );
  assert.equal(
    buildExcerptPayload({ quote: "quote", page: "1.5", section: "", locator: "", note: "", tags: "" }),
    null,
  );
});

test("matrix suggestion fills empty fields without overwriting user text", () => {
  const result = mergeMatrixSuggestion(
    {
      problem: "人工已写的问题",
      method: "",
      dataset: "   ",
    },
    {
      problem: "模型建议的问题",
      method: "模型建议的方法",
      dataset: "模型建议的数据集",
      ignored: "不应写入",
    },
    ["problem", "method", "dataset"],
  );

  assert.deepEqual(result, {
    draft: {
      problem: "人工已写的问题",
      method: "模型建议的方法",
      dataset: "模型建议的数据集",
    },
    applied: 2,
    skipped: 1,
  });
});

test("reader note draft starts empty with default kind", () => {
  const draft = emptyReaderNoteDraft();
  assert.deepEqual(draft, { kind: "note", content: "", tags: "" });
  assert.equal(readerNoteDraftError(draft), "笔记内容不能为空");
});

test("reader note draft validates kind and content", () => {
  assert.equal(
    readerNoteDraftError({ kind: "critique", content: "  论证链条不完整  ", tags: "" }),
    null,
  );
  assert.equal(
    readerNoteDraftError({ kind: "bogus", content: "内容", tags: "" }),
    "请选择笔记类型",
  );
  for (const kind of ["note", "question", "idea", "critique", "todo"]) {
    assert.equal(readerNoteDraftError({ kind, content: "内容", tags: "" }), null, kind);
  }
});

test("excerpt note payload trims and allows clearing the note", () => {
  assert.deepEqual(buildExcerptNotePayload("  关键论据  "), "关键论据");
  assert.deepEqual(buildExcerptNotePayload(""), "");
  assert.deepEqual(buildExcerptNotePayload("   "), "");
});
