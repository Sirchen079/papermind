import { useEffect, useState } from "react";
import { api, Suggestion } from "../api";

// 过滤值是后端状态标识，不能改；这里只做中文展示。
const FILTER_LABELS: Record<string, string> = {
  new: "新",
  all: "全部",
  accepted: "已采纳",
  dismissed: "已忽略",
};

export default function Suggestions({ onOpenPaper }: { onOpenPaper: (id: number) => void }) {
  const [items, setItems] = useState<Suggestion[]>([]);
  const [filter, setFilter] = useState<"new" | "all" | "accepted" | "dismissed">("new");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  async function load() {
    try {
      setItems(await api.listSuggestions(filter === "all" ? undefined : filter));
      setErr(null);
    } catch (e: any) {
      setErr(e.message);
    }
  }
  useEffect(() => {
    load();
  }, [filter]);

  async function scan() {
    setScanning(true);
    setErr(null);
    try {
      const r = await api.generateSuggestions();
      setMsg(r.created > 0 ? `找到 ${r.created} 条新建议。` : "论文库已是最新。");
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setScanning(false);
    }
  }

  async function act(id: number, status: "accepted" | "dismissed" | "seen") {
    try {
      await api.patchSuggestion(id, status);
      await load();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  return (
    <div className="max-w-3xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex overflow-hidden rounded-lg" style={{ border: "1px solid var(--border)" }}>
          {(["new", "all", "accepted", "dismissed"] as const).map((f) => {
            const isActive = filter === f;
            return (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className="px-3 py-1.5 text-sm transition-colors"
                style={
                  isActive
                    ? { backgroundColor: "var(--accent)", color: "var(--accent-contrast)" }
                    : { backgroundColor: "var(--surface)", color: "var(--muted)" }
                }
              >
                {FILTER_LABELS[f] ?? f}
              </button>
            );
          })}
        </div>
        <button onClick={scan} disabled={scanning} className="btn-primary">
          {scanning ? "扫描中…" : "↻ 扫描论文库"}
        </button>
      </div>

      <p className="text-sm" style={{ color: "var(--muted)" }}>
        Agent 从你的概念图谱中主动发现的关系——主题相关的论文，以及横跨多篇论文的核心概念。
      </p>

      {msg && (
        <div
          className="rounded-lg px-3 py-2 text-sm"
          style={{ backgroundColor: "color-mix(in srgb, var(--success) 14%, transparent)", color: "var(--success)" }}
        >
          {msg}
        </div>
      )}
      {err && (
        <div
          className="rounded-lg px-3 py-2 text-sm"
          style={{ backgroundColor: "color-mix(in srgb, var(--danger) 12%, transparent)", color: "var(--danger)" }}
        >
          {err}
        </div>
      )}

      <div className="space-y-2">
        {items.length === 0 && (
          <div className="card text-center text-sm" style={{ color: "var(--muted)" }}>
            {filter === "new"
              ? "暂无新建议。请配置提供商后导入论文，或扫描论文库。"
              : `没有「${FILTER_LABELS[filter] ?? filter}」建议。`}
          </div>
        )}
        {items.map((s) => (
          <div key={s.id} className="card-tight" style={{ boxShadow: "var(--shadow)" }}>
            <div className="flex items-start gap-3">
              <div
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-sm"
                style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}
              >
                {s.kind === "concept_hub" ? "★" : "🔗"}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{s.title}</span>
                  <span className="chip">{s.kind === "concept_hub" ? "主题" : "关联"}</span>
                  {s.status !== "new" && (
                    <span className="text-xs" style={{ color: "var(--faint)" }}>
                      {FILTER_LABELS[s.status] ?? s.status}
                    </span>
                  )}
                </div>
                <div className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
                  {s.kind === "concept_link" && s.detail.shared_concepts && (
                    <span>
                      共享 {s.detail.count} 个概念：{s.detail.shared_concepts.join("、")}
                    </span>
                  )}
                  {s.kind === "concept_hub" && (
                    <span>出现在你论文库中的 {s.detail.papers} 篇论文里。</span>
                  )}
                </div>
                {s.status === "new" && (
                  <div className="mt-2 flex gap-2">
                    <button onClick={() => act(s.id, "accepted")} className="btn-primary py-1 text-xs">
                      有用
                    </button>
                    <button onClick={() => act(s.id, "dismissed")} className="btn-ghost py-1 text-xs">
                      忽略
                    </button>
                  </div>
                )}
                {s.kind === "concept_link" && (s.paper || s.related_paper) && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {s.paper && (
                      <button
                        onClick={() => onOpenPaper(s.paper!.id)}
                        className="inline-flex max-w-[220px] items-center gap-1 rounded-full px-2.5 py-1 text-xs"
                        style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}
                        title={s.paper.title ?? `#${s.paper.id}`}
                      >
                        📚 <span className="truncate">{s.paper.title ?? `#${s.paper.id}`}</span>
                      </button>
                    )}
                    {s.related_paper && (
                      <button
                        onClick={() => onOpenPaper(s.related_paper!.id)}
                        className="inline-flex max-w-[220px] items-center gap-1 rounded-full px-2.5 py-1 text-xs"
                        style={{ backgroundColor: "var(--accent-soft)", color: "var(--accent)" }}
                        title={s.related_paper.title ?? `#${s.related_paper.id}`}
                      >
                        📚 <span className="truncate">
                          {s.related_paper.title ?? `#${s.related_paper.id}`}
                        </span>
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
