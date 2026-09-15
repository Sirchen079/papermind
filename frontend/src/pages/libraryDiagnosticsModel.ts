export type DiagnosticTone = "success" | "warning" | "danger" | "muted";

export interface DiagnosticsLike {
  issue_counts: Record<string, number>;
  papers: { severity: string; issues: unknown[] }[];
}

export type DiagnosticRepairAction = "citation_keys" | "reanalyze" | "reindex";

export function diagnosticSeverityLabel(severity: string): string {
  if (severity === "critical") return "严重";
  if (severity === "warning") return "待完善";
  if (severity === "ok") return "正常";
  return "未知";
}

export function diagnosticSeverityTone(severity: string): DiagnosticTone {
  if (severity === "critical") return "danger";
  if (severity === "warning") return "warning";
  if (severity === "ok") return "success";
  return "muted";
}

export function summarizeDiagnostics(report: DiagnosticsLike) {
  const healthy = report.papers.filter((paper) => paper.severity === "ok").length;
  const actionable = report.papers.length - healthy;
  const topIssue =
    Object.entries(report.issue_counts).sort((a, b) => b[1] - a[1])[0] ?? null;
  return {
    actionable,
    healthy,
    topIssue: topIssue ? { id: topIssue[0], count: topIssue[1] } : null,
  };
}

export function availableDiagnosticActions(issueCounts: Record<string, number>): DiagnosticRepairAction[] {
  const actions: DiagnosticRepairAction[] = [];
  if ((issueCounts.missing_citation_key ?? 0) > 0) actions.push("citation_keys");
  if (
    (issueCounts.missing_summary ?? 0) > 0 ||
    (issueCounts.missing_concepts ?? 0) > 0 ||
    (issueCounts.analysis_failed ?? 0) > 0
  ) {
    actions.push("reanalyze");
  }
  if ((issueCounts.not_indexed ?? 0) > 0) actions.push("reindex");
  return actions;
}
