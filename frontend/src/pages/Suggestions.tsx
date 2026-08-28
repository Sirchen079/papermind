import { useEffect, useState } from "react";
import { api, Suggestion } from "../api";
import { BookOpen, LinkIcon, Loader2, RotateCw, Star } from "../icons";
import { useToast } from "../components/ui/Toast";
import { SkeletonGroup } from "../components/ui/Skeleton";
import { Shell } from "../components/layout/Shell";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";

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
  const [scanning, setScanning] = useState(false);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  async function load() {
    try {
      setItems(await api.listSuggestions(filter === "all" ? undefined : filter));
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    load();
  }, [filter]);

  async function scan() {
    setScanning(true);
    try {
      const r = await api.generateSuggestions();
      toast.success(r.created > 0 ? `找到 ${r.created} 条新建议。` : "论文库已是最新。");
      await load();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setScanning(false);
    }
  }

  async function act(id: number, status: "accepted" | "dismissed" | "seen") {
    try {
      await api.patchSuggestion(id, status);
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  return (
    <Shell max="narrow" className="space-y-5">
      <PageHeader
        title="建议"
        subtitle="Agent 从你的概念图谱中主动发现的关系——主题相关的论文，以及横跨多篇论文的核心概念"
        actions={
          <button onClick={scan} disabled={scanning} className="btn-primary">
            {scanning ? (<><Loader2 size={14} className="animate-spin" /> 扫描中…</>) : (<><RotateCw size={14} /> 扫描论文库</>)}
          </button>
        }
      />

      <div className="inline-flex overflow-hidden rounded-lg border border-[var(--border)]">
        {(["new", "all", "accepted", "dismissed"] as const).map((f) => {
          const isActive = filter === f;
          return (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 text-sm transition-colors ${
                isActive ? "bg-[var(--accent)] text-[var(--accent-contrast)]" : "bg-[var(--surface)] text-muted"
              }`}
            >
              {FILTER_LABELS[f] ?? f}
            </button>
          );
        })}
      </div>

      <div className="space-y-2">
        {loading ? (
          <SkeletonGroup variant="row" count={4} />
        ) : items.length === 0 ? (
          <EmptyState
            icon={<LinkIcon size={20} />}
            title={filter === "new" ? "暂无新建议" : `没有「${FILTER_LABELS[filter] ?? filter}」建议`}
            hint={filter === "new" ? "配置提供商后导入论文，或点击「扫描论文库」。" : undefined}
          />
        ) : null}
        {items.map((s) => (
          <div key={s.id} className="card-tight" style={{ boxShadow: "var(--shadow)" }}>
            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--accent-soft)] text-sm text-[var(--accent)]">
                {s.kind === "concept_hub" ? <Star size={15} /> : <LinkIcon size={15} />}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{s.title}</span>
                  <span className="chip">{s.kind === "concept_hub" ? "主题" : "关联"}</span>
                  {s.status !== "new" && (
                    <span className="text-xs text-faint">
                      {FILTER_LABELS[s.status] ?? s.status}
                    </span>
                  )}
                </div>
                <div className="mt-1 text-sm text-muted">
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
                        className="inline-flex max-w-[220px] items-center gap-1 rounded-full bg-[var(--accent-soft)] px-2.5 py-1 text-xs text-[var(--accent)]"
                        title={s.paper.title ?? `#${s.paper.id}`}
                      >
                        <BookOpen size={12} /> <span className="truncate">{s.paper.title ?? `#${s.paper.id}`}</span>
                      </button>
                    )}
                    {s.related_paper && (
                      <button
                        onClick={() => onOpenPaper(s.related_paper!.id)}
                        className="inline-flex max-w-[220px] items-center gap-1 rounded-full bg-[var(--accent-soft)] px-2.5 py-1 text-xs text-[var(--accent)]"
                        title={s.related_paper.title ?? `#${s.related_paper.id}`}
                      >
                        <BookOpen size={12} /> <span className="truncate">
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
    </Shell>
  );
}
