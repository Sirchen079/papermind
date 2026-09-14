import assert from "node:assert/strict";
import { test } from "node:test";

import {
  canQueueExternal,
  externalPaperPayload,
  queueSuccessLabel,
} from "../.tmp_graph_test_dist/externalPaperModel.js";

test("external paper needs at least one of title/doi/arxiv to be queueable", () => {
  assert.equal(canQueueExternal({}), false);
  assert.equal(canQueueExternal({ title: "  ", doi: null, arxiv_id: "" }), false);
  assert.equal(canQueueExternal({ title: "A Paper" }), true);
  assert.equal(canQueueExternal({ doi: "10.1/x" }), true);
  assert.equal(canQueueExternal({ arxiv_id: "2401.00001" }), true);
});

test("external paper payload trims fields and omits empties", () => {
  assert.deepEqual(
    externalPaperPayload({
      title: "  Queued Paper ",
      doi: " 10.9999/queued ",
      arxiv_id: null,
      year: 2025,
      venue: " ",
      authors: ["A", "B"],
    }),
    {
      title: "Queued Paper",
      doi: "10.9999/queued",
      year: 2025,
      authors: ["A", "B"],
    },
  );
});

test("external paper payload is null when metadata is insufficient", () => {
  assert.equal(externalPaperPayload({ title: " ", doi: null }), null);
  assert.equal(externalPaperPayload({}), null);
});

test("citation-style entries with arxiv id prefer arxiv ingestion payload", () => {
  const payload = externalPaperPayload({
    title: "Cited Work",
    doi: "10.1/cited",
    arxiv_id: "1706.03762",
    year: 2017,
  });
  assert.deepEqual(payload, {
    title: "Cited Work",
    doi: "10.1/cited",
    arxiv_id: "1706.03762",
    year: 2017,
  });
});

test("queue success label distinguishes created vs deduped", () => {
  assert.equal(queueSuccessLabel(true), "已入库并加入待读。");
  assert.equal(queueSuccessLabel(false), "论文已在库中，已加入待读。");
});
