import { useEffect, useMemo, useState } from "react";
import { api, type ResearchProgressReport } from "../api";
import {
  progressPriorityLabel,
  progressPriorityTone,
  researchProgressMarkdownExportUrl,
  summarizeProgressActions,
  type ProgressTone,
} from "../pages/researchProgressModel";

const TONE_COLOR: Record<ProgressTone, string> = {
  success: "var(--success)",
  warning: "var(--accent)",
  danger: "var(--danger)",
  muted: "var(--faint)",
};

export default function ResearchProgressPanel({ onNavigate }: { onNavigate?: (page: string) => void }) {
  const [report, setReport] = useState<ResearchProgressReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setReport(await api.researchProgress());
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const actionSummary = useMemo(() => summarizeProgressActions(report?.actions ?? []), [report]);
  if (error) {
    return (
      <section className="card mb-4 border-[var(--danger)]">
        <p className="text-sm text-[var(--danger)]">
          科研进度加载失败：{error}
        </p>
      </section>
    );
  }
  if (!report) {
    return (
      <section className="card mb-4">
        <p className="text-sm text-faint">
          正在汇总科研进度...
        </p>
      </section>
    );
  }

  const readRate = report.reading.total_papers
    ? Math.round((report.reading.status_counts.read / report.reading.total_papers) * 100)
    : 0;
  const matrixRate = report.reading.status_counts.read
    ? Math.round((report.reading.review_matrices / report.reading.status_counts.read) * 100)
    : 0;

  return (
    <section className="card mb-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold">科研进度</h3>
          <p className="mt-1 text-sm text-muted">
            把阅读、质量诊断和写作组织合在一起，提示当前最该推进的科研动作。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <a className="btn-ghost py-1 text-xs" href={researchProgressMarkdownExportUrl()} download>
            导出进展报告
          </a>
          <button onClick={load} className="btn-ghost py-1 text-xs">
            刷新进度
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
        <Metric label="论文总数" value={report.reading.total_papers} />
        <Metric label="已读比例" value={`${readRate}%`} />
        <Metric label="审阅矩阵覆盖" value={`${matrixRate}%`} />
        <Metric label="高相关" value={report.reading.high_relevance} />
        <Metric label="写作链接" value={report.writing.linked_papers} />
        <Metric label="质量待处理" value={report.quality.needs_action} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-lg border p-3 border-[var(--border)]">
          <div className="mb-2 text-sm font-medium">阅读状态</div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <State label="未读" value={report.reading.status_counts.unread} />
            <State label="待读" value={report.reading.status_counts.queued} />
            <State label="阅读中" value={report.reading.status_counts.reading} />
            <State label="已读" value={report.reading.status_counts.read} />
            <State label="跳过" value={report.reading.status_counts.skipped} />
            <State label="缺矩阵" value={report.reading.read_without_matrix} />
          </div>
        </div>

        <div className="rounded-lg border p-3 border-[var(--border)]">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-medium">下一步行动</span>
            <span className="text-xs text-faint">
              优先 {actionSummary.high} · 建议 {actionSummary.normal} · 维护 {actionSummary.low}
            </span>
          </div>
          <div className="space-y-2">
            {report.actions.map((action) => {
              const tone = progressPriorityTone(action.priority);
              return (
                <div key={action.id} className="rounded-lg px-3 py-2" style={{ backgroundColor: "var(--surface-2)" }}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className="rounded-full px-2 py-0.5 text-[11px]"
                      style={{
                        color: TONE_COLOR[tone],
                        backgroundColor: `color-mix(in srgb, ${TONE_COLOR[tone]} 12%, transparent)`,
                      }}
                    >
                      {progressPriorityLabel(action.priority)}
                    </span>
                    <span className="text-sm font-medium">{action.label}</span>
                    <button onClick={() => onNavigate?.(action.route)} className="btn-ghost ml-auto py-0.5 text-xs">
                      去处理
                    </button>
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-muted">
                    {action.detail}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border px-3 py-2 border-[var(--border)]">
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-[11px] text-faint">
        {label}
      </div>
    </div>
  );
}

function State({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between rounded-md px-2 py-1 text-muted" style={{ backgroundColor: "var(--surface-2)" }}>
      <span >{label}</span>
      <span className="font-semibold">{value}</span>
    </div>
  );
}
