import assert from "node:assert/strict";
import { test } from "node:test";

import {
  availableDiagnosticActions,
  diagnosticSeverityLabel,
  diagnosticSeverityTone,
  summarizeDiagnostics,
} from "../.tmp_graph_test_dist/libraryDiagnosticsModel.js";

test("library diagnostics model maps severities to Chinese labels", () => {
  assert.equal(diagnosticSeverityLabel("critical"), "严重");
  assert.equal(diagnosticSeverityLabel("warning"), "待完善");
  assert.equal(diagnosticSeverityLabel("ok"), "正常");
  assert.equal(diagnosticSeverityLabel("unknown"), "未知");
});

test("library diagnostics model summarizes actionable papers and top issue", () => {
  const summary = summarizeDiagnostics({
    issue_counts: { not_indexed: 3, missing_summary: 1 },
    papers: [
      { severity: "ok", issues: [] },
      { severity: "warning", issues: [{ id: "not_indexed" }] },
      { severity: "critical", issues: [{ id: "missing_text" }] },
    ],
  });

  assert.deepEqual(summary, {
    actionable: 2,
    healthy: 1,
    topIssue: { id: "not_indexed", count: 3 },
  });
});

test("library diagnostics model uses stable tones", () => {
  assert.equal(diagnosticSeverityTone("critical"), "danger");
  assert.equal(diagnosticSeverityTone("warning"), "warning");
  assert.equal(diagnosticSeverityTone("ok"), "success");
  assert.equal(diagnosticSeverityTone("other"), "muted");
});

test("library diagnostics model exposes repair actions from issue counts", () => {
  assert.deepEqual(
    availableDiagnosticActions({
      missing_citation_key: 2,
      missing_summary: 1,
      missing_concepts: 1,
      not_indexed: 3,
    }),
    ["citation_keys", "reanalyze", "reindex"],
  );
  assert.deepEqual(availableDiagnosticActions({}), []);
});
