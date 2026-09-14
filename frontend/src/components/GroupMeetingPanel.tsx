import { useApi } from '../workspaceContext';
import { useEffect, useState } from "react";
import { type Report, type WeeklyAggregate } from "../api";
import { Copy, FileText, RotateCw } from "../icons";
import { useToast } from "./ui/Toast";

function fmtDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function pastWeek(): { since: string; until: string } {
  const until = new Date();
  const since = new Date(until.getTime() - 6 * 24 * 3600 * 1000);
  return { since: fmtDate(since), until: fmtDate(until) };
}

export default function GroupMeetingPanel() {
  const api = useApi();
  const initial = pastWeek();
  const [since, setSince] = useState(initial.since);
  const [until, setUntil] = useState(initial.until);
  const [aggregate, setAggregate] = useState<WeeklyAggregate | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [history, setHistory] = useState<Report[]>([]);
  const toast = useToast();

  async function loadHistory() {
    try {
      setHistory(await api.listReports());
    } catch {
      setHistory([]);
    }
  }

  useEffect(() => {
    loadHistory();
  }, []);

  async function preview() {
    setPreviewing(true);
    try {
      setAggregate(await api.weeklyAggregate(since, until));
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setPreviewing(false);
    }
  }

  async function generate() {
    setGenerating(true);
    try {
      const created = await api.generateWeeklyReport({ since, until });
      setReport(created);
      setAggregate(await api.weeklyAggregate(since, until));
      await loadHistory();
      toast.success("组会汇报已生成。");
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setGenerating(false);
    }
  }

  async function viewReport(id: number) {
    try {
      setReport(await api.getReport(id));
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function copyContent() {
    if (!report) return;
    try {
      await navigator.clipboard.writeText(report.content);
      toast.success("汇报已复制到剪贴板。");
    } catch {
      toast.error("复制失败，请手动选择文本复制。");
    }
  }

  function fmtWindow(r: { since: string; until: string }): string {
    return `${(r.since ?? "").slice(0, 10)} 至 ${(r.until ?? "").slice(0, 10)}`;
  }

  return (
    <section className="card mb-4">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold">组会汇报</h3>
          <p className="mt-1 text-sm text-muted">
            选日期区间聚合本周科研活动，AI 按内置模板生成中文汇报，可下载 markdown 与 PPTX。聚合为零 AI 的确定性统计。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="date"
            className="input max-w-[10rem] py-1 text-xs"
            value={since}
            onChange={(e) => setSince(e.target.value)}
          />
          <span className="text-xs text-faint">至</span>
          <input
            type="date"
            className="input max-w-[10rem] py-1 text-xs"
            value={until}
            onChange={(e) => setUntil(e.target.value)}
          />
          <button onClick={preview} disabled={previewing} className="btn-ghost py-1 text-xs">
            {previewing ? "统计中…" : "预览聚合数据"}
          </button>
          <button onClick={generate} disabled={generating} className="btn-primary py-1 text-xs">
            {generating ? "生成中…" : "生成汇报"}
          </button>
        </div>
      </div>

      {aggregate && (
        <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-6">
          <Metric label="新入库" value={aggregate.papers_new.count} />
          <Metric label="读完" value={aggregate.papers_read.count} />
          <Metric label="新增笔记/摘录" value={`${aggregate.notes_new.count}/${aggregate.excerpts_new.count}`} />
          <Metric label="Idea 新建/完结" value={`${aggregate.ideas.created.count}/${aggregate.ideas.closed.count}`} />
          <Metric label="实验新建/完结" value={`${aggregate.experiments.created.count}/${aggregate.experiments.finished.count}`} />
          <Metric label="雷达 high / AI 建议" value={`${aggregate.radar_high.count}/${aggregate.suggestions_ai.count}`} />
        </div>
      )}

      {report && (
        <div className="mb-4 space-y-2 rounded-lg border p-3 border-[var(--border)]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="label flex-1">
              汇报 {fmtWindow(report)}
              {report.model ? ` · ${report.model}` : ""}
            </span>
            <button onClick={copyContent} className="btn-ghost py-1 text-xs">
              <Copy size={13} className="inline" /> 复制
            </button>
            <a className="btn-ghost py-1 text-xs" href={api.reportMarkdownUrl(report.id)} download>
              下载 .md
            </a>
            <a className="btn-ghost py-1 text-xs" href={api.reportPptxUrl(report.id)} download>
              下载 .pptx
            </a>
            <button onClick={() => setReport(null)} className="btn-ghost py-1 text-xs">
              收起
            </button>
          </div>
          <pre
            className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg p-3 text-xs"
            style={{ backgroundColor: "var(--surface-2)" }}
          >
            {report.content}
          </pre>
        </div>
      )}

      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-medium">历史汇报</span>
          <button onClick={loadHistory} className="btn-ghost py-0.5 text-xs">
            <RotateCw size={12} className="inline" /> 刷新
          </button>
        </div>
        {history.length === 0 ? (
          <p className="text-xs text-faint">还没有生成过汇报。</p>
        ) : (
          <ul className="space-y-1">
            {history.map((item) => (
              <li
                key={item.id}
                className="flex flex-wrap items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm"
                style={{ backgroundColor: "var(--surface-2)" }}
              >
                <FileText size={14} className="shrink-0 text-faint" />
                <button onClick={() => viewReport(item.id)} className="min-w-0 flex-1 truncate text-left hover:underline">
                  {fmtWindow(item)}
                  {item.created_at ? ` · 生成于 ${new Date(item.created_at).toLocaleString()}` : ""}
                </button>
                <a className="btn-ghost shrink-0 py-0.5 text-xs" href={api.reportMarkdownUrl(item.id)} download>
                  .md
                </a>
                <a className="btn-ghost shrink-0 py-0.5 text-xs" href={api.reportPptxUrl(item.id)} download>
                  .pptx
                </a>
              </li>
            ))}
          </ul>
        )}
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
