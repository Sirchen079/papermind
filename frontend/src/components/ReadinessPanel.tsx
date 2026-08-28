import { useEffect, useMemo, useState } from "react";
import { api, type ReadinessReport } from "../api";
import {
  buildFirstUseGuide,
  readinessLevelLabel,
  readinessStatusTone,
  summarizeReadinessChecks,
  type ReadinessTone,
} from "../pages/readinessModel";

const TONE_COLOR: Record<ReadinessTone, string> = {
  success: "var(--success)",
  warning: "var(--accent)",
  danger: "var(--danger)",
  muted: "var(--faint)",
};

const STATUS_LABELS: Record<string, string> = {
  done: "已就绪",
  warning: "需完善",
  action: "待处理",
};

const GUIDE_STATUS_LABELS: Record<string, string> = {
  done: "完成",
  warning: "完善中",
  action: "待推进",
};

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border px-3 py-2 border-[var(--border)]">
      <div className="text-base font-semibold">{value}</div>
      <div className="text-[11px] text-faint">
        {label}
      </div>
    </div>
  );
}

export default function ReadinessPanel({ onNavigate }: { onNavigate?: (page: string) => void }) {
  const [report, setReport] = useState<ReadinessReport | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setReport(await api.readiness());
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const summary = useMemo(() => summarizeReadinessChecks(report?.checks ?? []), [report]);
  const guide = useMemo(() => buildFirstUseGuide(report?.checks ?? []), [report]);
  if (error) {
    return (
      <section className="card mb-4" style={{ borderColor: "var(--danger)" }}>
        <div className="text-sm text-[var(--danger)]">
          科研准备度检查加载失败：{error}
        </div>
      </section>
    );
  }
  if (!report) {
    return (
      <section className="card mb-4">
        <div className="text-sm text-faint">
          正在检查科研工作台状态...
        </div>
      </section>
    );
  }

  const levelTone = report.level === "ready" ? "success" : report.level === "usable" ? "warning" : "danger";
  const visibleChecks = collapsed ? report.checks.filter((check) => check.status !== "done") : report.checks;

  return (
    <section className="card mb-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold">科研准备度</h3>
            <span
              className="rounded-full px-2 py-0.5 text-xs font-medium"
              style={{
                backgroundColor: `color-mix(in srgb, ${TONE_COLOR[levelTone]} 12%, transparent)`,
                color: TONE_COLOR[levelTone],
              }}
            >
              {readinessLevelLabel(report.level)}
            </span>
          </div>
          <p className="max-w-3xl text-sm leading-relaxed text-muted">
            {report.summary}
          </p>
          {summary.nextAction && (
            <button
              className="btn-primary mt-3 py-1 text-xs"
              onClick={() => onNavigate?.(summary.nextAction?.route ?? "library")}
            >
              下一步：{summary.nextAction.label}
            </button>
          )}
        </div>
        <div className="w-28 shrink-0 text-right">
          <div className="text-3xl font-bold leading-none">{report.score}</div>
          <div className="mt-1 text-xs text-faint">
            / 100
          </div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-6">
        <Stat label="论文" value={report.stats.papers} />
        <Stat label="有文本" value={report.stats.papers_with_text} />
        <Stat label="摘要" value={report.stats.summaries} />
        <Stat label="索引块" value={report.stats.indexed_chunks} />
        <Stat label="审阅矩阵" value={report.stats.review_matrices} />
        <Stat label="写作链接" value={report.stats.paper_links} />
      </div>

      <div className="mt-4 rounded-lg border p-4 border-[var(--border)] bg-[var(--surface-2)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h4 className="text-sm font-semibold">首次使用向导</h4>
            <p className="mt-1 text-xs leading-relaxed text-muted">
              按研究生真实上手顺序，把模型配置、论文导入、AI 分析、阅读沉淀和写作组织串起来。
            </p>
          </div>
          <div className="shrink-0 text-right">
            <div className="text-lg font-semibold">{guide.percent}%</div>
            <div className="text-[11px] text-faint">
              {guide.completed}/{guide.total} 步
            </div>
          </div>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-[var(--surface)]">
          <div
            className="h-full rounded-full transition-all"
            style={{ width: `${guide.percent}%`, backgroundColor: TONE_COLOR[levelTone] }}
          />
        </div>
        {guide.nextStep && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border px-3 py-2" style={{ borderColor: "var(--border)", backgroundColor: "var(--surface)" }}>
            <div className="min-w-0">
              <div className="text-xs text-faint">当前建议</div>
              <div className="mt-0.5 text-sm font-medium">{guide.nextStep.title}</div>
              <p className="mt-1 text-xs leading-relaxed text-muted">{guide.nextStep.detail}</p>
            </div>
            <button className="btn-primary shrink-0 py-1 text-xs" onClick={() => onNavigate?.(guide.nextStep?.route ?? "library")}>
              {guide.nextStep.action}
            </button>
          </div>
        )}
        <div className="mt-3 grid grid-cols-1 gap-2 lg:grid-cols-5">
          {guide.steps.map((step, index) => {
            const tone = readinessStatusTone(step.status);
            return (
              <div key={step.id} className="rounded-lg border p-3" style={{ borderColor: "var(--border)", backgroundColor: "var(--surface)" }}>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-xs font-semibold" style={{ backgroundColor: `color-mix(in srgb, ${TONE_COLOR[tone]} 12%, transparent)`, color: TONE_COLOR[tone] }}>
                    {index + 1}
                  </span>
                  <span className="text-[11px]" style={{ color: TONE_COLOR[tone] }}>
                    {GUIDE_STATUS_LABELS[step.status]}
                  </span>
                </div>
                <div className="text-sm font-medium leading-snug">{step.title}</div>
                <p className="mt-1 text-xs leading-relaxed text-muted">
                  {step.detail}
                </p>
              </div>
            );
          })}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs text-faint">
          已就绪 {summary.counts.done} 项 · 需完善 {summary.counts.warning} 项 · 待处理 {summary.counts.action} 项
        </div>
        <button className="btn-ghost py-1 text-xs" onClick={() => setCollapsed(!collapsed)}>
          {collapsed ? "显示全部检查" : "只看待办"}
        </button>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-2 lg:grid-cols-2">
        {visibleChecks.map((check) => {
          const tone = readinessStatusTone(check.status);
          return (
            <div
              key={check.id}
              className="rounded-lg border p-3"
              style={{
                borderColor: "var(--border)",
                backgroundColor: check.status === "done" ? "transparent" : "var(--surface-2)",
              }}
            >
              <div className="mb-1 flex items-center gap-2">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: TONE_COLOR[tone] }} />
                <span className="text-sm font-medium">{check.label}</span>
                <span className="ml-auto text-xs" style={{ color: TONE_COLOR[tone] }}>
                  {STATUS_LABELS[check.status] ?? check.status}
                </span>
              </div>
              <p className="text-xs leading-relaxed text-muted">
                {check.detail}
              </p>
              {check.status !== "done" && (
                <button className="btn-ghost mt-2 py-1 text-xs" onClick={() => onNavigate?.(check.route)}>
                  {check.action}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
