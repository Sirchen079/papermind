import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildPdfImportQueue,
  firstDonePdfItem,
  markPdfImportItem,
  nextQueuedPdf,
  summarizePdfImport,
} from "../.tmp_graph_test_dist/pdfBatchModel.js";

test("pdf import queue keeps PDFs and marks non-PDF files as failed", () => {
  const queue = buildPdfImportQueue([
    { name: "Transformer.pdf", type: "application/pdf" },
    { name: "扫描论文.PDF", type: "" },
    { name: "notes.txt", type: "text/plain" },
  ]);

  assert.deepEqual(
    queue.map((item) => ({ name: item.name, status: item.status, error: item.error })),
    [
      { name: "Transformer.pdf", status: "queued", error: null },
      { name: "扫描论文.PDF", status: "queued", error: null },
      { name: "notes.txt", status: "failed", error: "只支持 PDF 文件" },
    ],
  );
  assert.equal(nextQueuedPdf(queue)?.name, "Transformer.pdf");
});

test("pdf import item status updates are stable and immutable", () => {
  const queue = buildPdfImportQueue([{ name: "A.pdf", type: "application/pdf" }]);
  const importing = markPdfImportItem(queue, queue[0].id, { status: "importing" });
  const done = markPdfImportItem(importing, queue[0].id, { status: "done", paperId: 42 });
  const failed = markPdfImportItem(done, "missing-id", { status: "failed", error: "bad file" });

  assert.equal(queue[0].status, "queued");
  assert.equal(importing[0].status, "importing");
  assert.equal(done[0].status, "done");
  assert.equal(done[0].paperId, 42);
  assert.deepEqual(failed, done);
});

test("pdf import outcome picks the first successful paper for auto-open", () => {
  const queue = buildPdfImportQueue([
    { name: "A.pdf", type: "application/pdf" },
    { name: "B.pdf", type: "application/pdf" },
    { name: "C.pdf", type: "application/pdf" },
  ]);
  let current = markPdfImportItem(queue, queue[0].id, { status: "failed", error: "解析失败" });
  current = markPdfImportItem(current, queue[1].id, { status: "done", paperId: 7 });
  current = markPdfImportItem(current, queue[2].id, { status: "done", paperId: 9 });

  assert.equal(firstDonePdfItem(current)?.paperId, 7);
  assert.deepEqual(summarizePdfImport(current), { done: 2, failed: 1, remaining: 0 });
});

test("pdf import outcome reports nothing when no import succeeded", () => {
  const queue = buildPdfImportQueue([{ name: "A.pdf", type: "application/pdf" }]);
  const failed = markPdfImportItem(queue, queue[0].id, { status: "failed", error: "解析失败" });

  assert.equal(firstDonePdfItem(failed), null);
  assert.deepEqual(summarizePdfImport(failed), { done: 0, failed: 1, remaining: 0 });
  assert.deepEqual(summarizePdfImport(queue), { done: 0, failed: 0, remaining: 1 });
});
