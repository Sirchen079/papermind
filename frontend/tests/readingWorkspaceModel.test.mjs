import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildExcerptPayload,
  buildNotePayload,
  mergeMatrixSuggestion,
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
