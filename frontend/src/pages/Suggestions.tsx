import { useApi } from '../workspaceContext';
import { useEffect, useRef, useState } from "react";
import { Suggestion } from "../api";
import { AlertTriangle, BookOpen, Inbox, LinkIcon, Loader2, RotateCw, Star } from "../icons";
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

// P9.2 引入的 AI 关联建议类型（method_conflict / combination）。
const KIND_LABELS: Record<string, string> = {
  concept_link: "关联",
  concept_hub: "主题",
  method_conflict: "冲突",
  combination: "可结合",
  radar: "雷达",
  claim_relation: "论断关系",
};

// P12 论断关系三类型（与后端 ClaimRelation.type 对应）。
const CLAIM_RELATION_LABELS: Record<string, string> = {
  supports: "支持",
  contradicts: "矛盾",
  extends: "延伸",
};

// P10.3 雷达初筛三档（low 不会出现在建议里）。
const GRADE_LABELS: Record<string, string> = {
  high: "高相关",
  medium: "中相关",
};

export default function Suggestions({ onOpenPaper }: { onOpenPaper: (id: number) => void }) {
  const api = useApi();
  const [items, setItems] = useState<Suggestion[]>([]);
  const [filter, setFilter] = useState<"new" | "all" | "accepted" | "dismissed">("new");
  const [scanning, setScanning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [ingesting, setIngesting] = useState<number | null>(null);
  const toast = useToast();
  const listState=useRef({generation:0,mounted:true,filter});listState.current.filter=filter;
  useEffect(()=>{listState.current.mounted=true;return()=>{listState.current.mounted=false;++listState.current.generation;};},[]);

  async function load() {
    if(!listState.current.mounted)return;
    const selected=listState.current.filter,generation=++listState.current.generation;
    const current=()=>listState.current.mounted&&generation===listState.current.generation&&selected===listState.current.filter;
    setLoading(true);
    try {
      const rows=await api.listSuggestions(selected === "all" ? undefined : selected);
      if(current())setItems(rows);
    } catch (e: any) {
      if(current())toast.error(e.message);
    } finally {
      if(current())setLoading(false);
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

  // P10.3：雷达建议一键入库——复用现有 arXiv 入库，成功后建议标记已处理。
  async function ingestRadar(s: Suggestion) {
    const arxivId = s.detail?.arxiv_id as string | undefined;
    if (!arxivId) return;
    setIngesting(s.id);
    try {
      const paper = await api.ingestArxiv(arxivId);
      if (s.status === "new") await api.patchSuggestion(s.id, "accepted");
      toast.success(`已入库「${paper.title ?? arxivId}」，可在论文库查看。`);
      await load();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setIngesting(null);
    }
  }

  // P9：AI 关联建议一键转为 Idea（origin=suggestion，自动带出双方论文）。
  async function convertToIdea(s: Suggestion) {
    const fromId = s.detail?.from_paper_id ?? s.paper?.id;
    const toId = s.detail?.to_paper_id ?? s.related_paper?.id;
    // P12 论断关系建议附带两条论断原文，转 Idea 时一并带入内容。
    const claimContext =
      s.kind === "claim_relation" && (s.detail?.claim_a_text || s.detail?.claim_b_text)
        ? `\n\n论断 A：${s.detail?.claim_a_text ?? ""}\n论断 B：${s.detail?.claim_b_text ?? ""}`
        : "";
    try {
      await api.createIdea({
        title: s.title,
        content: `来源：AI 关联建议。\n\n${s.detail?.reason ?? ""}${claimContext}`,
        origin: "suggestion",
        papers: [
          ...(fromId != null ? [{ paper_id: fromId, role: "basis" }] : []),
          ...(toId != null
            ? [
                {
                  paper_id: toId,
                  role:
                    s.kind === "method_conflict" || s.detail?.type === "contradicts"
                      ? "contrast"
                      : "support",
                },
              ]
            : []),
        ],
      });
      if (s.status === "new") await api.patchSuggestion(s.id, "accepted");
      toast.success("已转为 Idea，可在 Idea 工作台继续推进。");
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
                {s.kind === "concept_hub" ? (
                  <Star size={15} />
                ) : s.kind === "method_conflict" ? (
                  <AlertTriangle size={15} />
                ) : (
                  <LinkIcon size={15} />
                )}
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{s.title}</span>
                  <span className="chip">{KIND_LABELS[s.kind] ?? s.kind}</span>
                  {s.kind === "radar" && s.detail?.grade && (
                    <span className="chip">{GRADE_LABELS[s.detail.grade] ?? s.detail.grade}</span>
                  )}
                  {s.kind === "claim_relation" && s.detail?.type && (
                    <span className="chip">{CLAIM_RELATION_LABELS[s.detail.type] ?? s.detail.type}</span>
                  )}
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
                  {(s.kind === "method_conflict" || s.kind === "combination") && s.detail.reason && (
                    <span>{s.detail.reason}</span>
                  )}
                  {s.kind === "claim_relation" && (
                    <div className="space-y-1">
                      {s.detail.reason && <p>{s.detail.reason}</p>}
                      {(s.detail.claim_a_text || s.detail.claim_b_text) && (
                        <div className="space-y-0.5 text-xs text-faint">
                          {s.detail.claim_a_text && <p>论断 A：{s.detail.claim_a_text}</p>}
                          {s.detail.claim_b_text && <p>论断 B：{s.detail.claim_b_text}</p>}
                        </div>
                      )}
                    </div>
                  )}
                  {s.kind === "radar" && (
                    <div className="space-y-1">
                      {s.detail.abstract && (
                        <p className="line-clamp-3 text-sm text-muted">{s.detail.abstract}</p>
                      )}
                      {s.detail.grade_reason && (
                        <p className="text-xs text-faint">相关度理由：{s.detail.grade_reason}</p>
                      )}
                      {s.detail.url && (
                        <a
                          href={s.detail.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs text-[var(--accent)] underline-offset-2 hover:underline"
                        >
                          在 arXiv 打开 ↗
                        </a>
                      )}
                    </div>
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
                    {(s.kind === "method_conflict" || s.kind === "combination" || s.kind === "claim_relation") && (
                      <button onClick={() => convertToIdea(s)} className="btn-ghost py-1 text-xs">
                        转为 Idea
                      </button>
                    )}
                    {s.kind === "radar" && s.detail?.arxiv_id && (
                      <button
                        onClick={() => ingestRadar(s)}
                        disabled={ingesting === s.id}
                        className="btn-ghost py-1 text-xs"
                      >
                        {ingesting === s.id ? (
                          <><Loader2 size={12} className="animate-spin" /> 入库中…</>
                        ) : (
                          <><Inbox size={12} /> 一键入库</>
                        )}
                      </button>
                    )}
                  </div>
                )}
                {s.kind !== "concept_hub" && (s.paper || s.related_paper) && (
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
