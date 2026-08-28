import { useEffect, useMemo, useState } from "react";
import { api, type LibraryDiagnosticsReport } from "../api";
import {
  availableDiagnosticActions,
  diagnosticSeverityLabel,
  diagnosticSeverityTone,
  summarizeDiagnostics,
  type DiagnosticRepairAction,
  type DiagnosticTone,
} from "../pages/libraryDiagnosticsModel";

const TONE_COLOR: Record<DiagnosticTone, string> = {
  success: "var(--success)",
  warning: "var(--accent)",
  danger: "var(--danger)",
  muted: "var(--faint)",
};

const ISSUE_LABELS: Record<string, string> = {
  missing_text: "缺少可用文本",
  low_parse_confidence: "PDF 解析质量低",
  analysis_failed: "AI 分析失败",
  missing_summary: "缺少 AI 摘要",
  missing_concepts: "缺少概念关系",
  not_indexed: "未进入向量索引",
  missing_citation_key: "缺少引用键",
};

const REPAIR_LABELS: Record<DiagnosticRepairAction, string> = {
  citation_keys: "批量补 citation key",
  reanalyze: "重试 AI 分析",
  reindex: "重建向量索引",
};

export default function LibraryDiagnosticsPanel({
  onOpenPaper,
  onNavigate,
  onLibraryChanged,
}: {
  onOpenPaper: (paperId: number) => void;
  onNavigate?: (page: string) => void;
  onLibraryChanged?: () => Promise<void> | void;
}) {
  const [report, setReport] = useState<LibraryDiagnosticsReport | null>(null);
  const [collapsed, setCollapsed] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [repairing, setRepairing] = useState<DiagnosticRepairAction | null>(null);
  const [repairMsg, setRepairMsg] = useState<string | null>(null);

  async function load() {
    try {
      setReport(await api.libraryDiagnostics());
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function runRepair(action: DiagnosticRepairAction) {
    setRepairing(action);
    setRepairMsg(null);
    setError(null);
    try {
      if (action === "reindex") {
        const result = await api.reindexLibrary();
        if (!result.configured) {
          setRepairMsg("未配置 embedding 模型，请先在设置中配置向量模型。");
        } else if (result.error) {
          setRepairMsg(`重建索引失败：${result.error}`);
        } else {
          setRepairMsg(`已重建索引：处理 ${result.papers} 篇论文，生成 ${result.chunks} 个文本块。`);
        }
      } else {
        const result = await api.repairLibraryDiagnostics(action);
        if (!result.configured) {
          setRepairMsg(result.error ?? "当前修复动作缺少必要配置。");
        } else if (action === "citation_keys") {
          setRepairMsg(`已为 ${result.changed} 篇论文补全 citation key。`);
        } else {
          const failedText = result.failed.length > 0 ? `，${result.failed.length} 篇仍失败` : "";
          setRepairMsg(`已重试分析 ${result.processed} 篇论文，成功 ${result.changed} 篇${failedText}。`);
        }
      }
      await load();
      await onLibraryChanged?.();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRepairing(null);
    }
  }

  const summary = useMemo(() => summarizeDiagnostics(report ?? { issue_counts: {}, papers: [] }), [report]);
  if (error) {
    return (
      <section className="card mb-4 border-[var(--danger)]">
        <p className="text-sm text-[var(--danger)]">
          论文质量诊断加载失败：{error}
        </p>
      </section>
    );
  }
  if (!report) {
    return (
      <section className="card mb-4">
        <p className="text-sm text-faint">
          正在检查论文库质量...
        </p>
      </section>
    );
  }

  const problemPapers = report.papers.filter((paper) => paper.severity !== "ok");
  const visiblePapers = collapsed ? problemPapers.slice(0, 5) : problemPapers;
  const topIssueLabel = summary.topIssue ? ISSUE_LABELS[summary.topIssue.id] ?? summary.topIssue.id : "暂无";
  const repairActions = availableDiagnosticActions(report.issue_counts);

  return (
    <section className="card mb-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold">论文质量诊断</h3>
          <p className="mt-1 text-sm text-muted">
            逐篇检查导入质量、AI 分析、图谱关系和 RAG 索引，优先处理会影响科研使用的论文。
          </p>
        </div>
        <button onClick={load} className="btn-ghost py-1 text-xs">
          刷新诊断
        </button>
      </div>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
        <Metric label="论文总数" value={report.summary.total} tone="muted" />
        <Metric label="正常" value={report.summary.healthy} tone="success" />
        <Metric label="待完善" value={report.summary.warning} tone="warning" />
        <Metric label="严重" value={report.summary.critical} tone="danger" />
        <Metric label="需处理" value={summary.actionable} tone={summary.actionable ? "warning" : "success"} />
      </div>

      <div className="mt-3 rounded-lg border px-3 py-2 text-xs text-faint border-[var(--border)]">
        <span >最常见问题：</span>
        <span className="ml-1 font-medium text-muted">{topIssueLabel}</span>
        {summary.topIssue && <span >（{summary.topIssue.count} 篇）</span>}
      </div>

      {repairActions.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {repairActions.map((action) => (
            <button
              key={action}
              onClick={() => runRepair(action)}
              disabled={repairing !== null}
              className="btn-ghost py-1 text-xs disabled:opacity-50"
            >
              {repairing === action ? "处理中..." : REPAIR_LABELS[action]}
            </button>
          ))}
          {repairMsg && (
            <span className="text-xs text-[var(--success)]">
              {repairMsg}
            </span>
          )}
        </div>
      )}

      {problemPapers.length === 0 ? (
        <p className="mt-4 text-sm text-[var(--success)]">
          当前论文库没有发现需要处理的质量问题。
        </p>
      ) : (
        <div className="mt-4 space-y-2">
          {visiblePapers.map((row) => {
            const tone = diagnosticSeverityTone(row.severity);
            return (
              <div key={row.paper.id} className="rounded-lg border p-3 border-[var(--border)]">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className="rounded-full px-2 py-0.5 text-xs"
                        style={{
                          color: TONE_COLOR[tone],
                          backgroundColor: `color-mix(in srgb, ${TONE_COLOR[tone]} 12%, transparent)`,
                        }}
                      >
                        {diagnosticSeverityLabel(row.severity)}
                      </span>
                      <h4 className="text-sm font-semibold">{row.paper.title ?? "（无标题）"}</h4>
                    </div>
                    <div className="mt-1 text-xs text-faint">
                      {row.paper.year ?? "年份未知"} · {row.paper.source} · {row.paper.citation_key ?? "无 citation key"}
                    </div>
                  </div>
                  <button onClick={() => onOpenPaper(row.paper.id)} className="btn-ghost py-1 text-xs">
                    打开处理
                  </button>
                </div>
                <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2">
                  {row.issues.map((issue) => (
                    <div key={issue.id} className="rounded-lg px-3 py-2" style={{ backgroundColor: "var(--surface-2)" }}>
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <span className="text-xs font-medium">{issue.label}</span>
                        <button
                          className="btn-ghost py-0.5 text-[11px]"
                          onClick={() => (issue.route === "library" ? onOpenPaper(row.paper.id) : onNavigate?.(issue.route))}
                        >
                          {issue.action}
                        </button>
                      </div>
                      <p className="text-xs leading-relaxed text-muted">
                        {issue.detail}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
          {problemPapers.length > 5 && (
            <button onClick={() => setCollapsed(!collapsed)} className="btn-ghost py-1 text-xs">
              {collapsed ? `显示全部 ${problemPapers.length} 篇问题论文` : "收起问题论文"}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function Metric({ label, value, tone }: { label: string; value: number; tone: DiagnosticTone }) {
  return (
    <div className="rounded-lg border px-3 py-2 border-[var(--border)]">
      <div className="text-lg font-semibold" style={{ color: TONE_COLOR[tone] }}>
        {value}
      </div>
      <div className="text-[11px] text-faint">
        {label}
      </div>
    </div>
  );
}
