import assert from "node:assert/strict";
import { test } from "node:test";

import { buildManualPaperPayload } from "../.tmp_graph_test_dist/manualPaperModel.js";

test("manual paper payload trims Chinese metadata and splits authors by line", () => {
  assert.deepEqual(
    buildManualPaperPayload({
      citation_key: " zhang2026graph ",
      title: " 面向硕士论文的中文知识图谱综述 ",
      authors: " 张三 \n李四\n ",
      year: " 2026 ",
      venue: " 软件学报 ",
      doi: " ",
      arxiv_id: "2601.00001",
      abstract: " 这是一篇摘要。 ",
    }),
    {
      citation_key: "zhang2026graph",
      title: "面向硕士论文的中文知识图谱综述",
      authors: ["张三", "李四"],
      year: 2026,
      venue: "软件学报",
      doi: null,
      arxiv_id: "2601.00001",
      abstract: "这是一篇摘要。",
    },
  );
});

test("manual paper payload rejects empty title and invalid year", () => {
  assert.equal(
    buildManualPaperPayload({
      citation_key: "",
      title: " ",
      authors: "",
      year: "2026",
      venue: "",
      doi: "",
      arxiv_id: "",
      abstract: "",
    }),
    null,
  );
  assert.equal(
    buildManualPaperPayload({
      citation_key: "",
      title: "Valid Paper",
      authors: "",
      year: "twenty",
      venue: "",
      doi: "",
      arxiv_id: "",
      abstract: "",
    }),
    null,
  );
});
