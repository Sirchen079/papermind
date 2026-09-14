import { useApi } from '../workspaceContext';
import { useEffect, useMemo, useRef, useState } from "react";
import { Idea, ResearchGap, ThesisWorkspace, type Experiment } from "../api";
import { Lightbulb, Loader2, Plus, RotateCw, Trash2, X } from "../icons";
import { useToast } from "../components/ui/Toast";
import { useConfirm } from "../components/ui/ConfirmDialog";
import { Tabs } from "../components/ui/Tabs";
import { Shell } from "../components/layout/Shell";
import { PageHeader } from "../components/ui/PageHeader";
import { EmptyState } from "../components/ui/EmptyState";
import { usePaperSearch } from "../components/usePaperSearch";
import { Drawer } from "../components/ui/Drawer";

// 状态/优先级/来源/角色是后端枚举，不能改；这里只做中文展示。
const STATUS_LABELS: Record<string, string> = {
  proposed: "已提出",
  refining: "打磨中",
  testing: "实验中",
  adopted: "已采纳",
  dropped: "已放弃",
};
const STATUS_ORDER = ["proposed", "refining", "testing", "adopted", "dropped"] as const;
const PRIORITY_LABELS: Record<string, string> = { low: "低", normal: "普通", high: "高" };
const ORIGIN_LABELS: Record<string, string> = {
  manual: "手动",
  matrix: "矩阵",
  suggestion: "建议",
  gap: "研究缺口",
};
const ROLE_LABELS: Record<string, string> = { basis: "基础", contrast: "对比", support: "支撑" };
const ROLE_OPTIONS = ["basis", "contrast", "support"] as const;

// P13：实验状态中文展示（与后端枚举一致）。
const EXPERIMENT_STATUS_LABELS: Record<string, string> = {
  planned: "已计划",
  running: "进行中",
  analyzing: "分析中",
  done: "已完成",
  abandoned: "已放弃",
};

// 与后端 IDEA_TRANSITIONS 保持一致（P9.1 状态机）。
const TRANSITIONS: Record<string, string[]> = {
  proposed: ["refining", "dropped"],
  refining: ["testing"],
  testing: ["adopted", "dropped"],
  adopted: [],
  dropped: [],
};

const GAP_TYPE_LABELS: Record<string, string> = {
  matrix_open_question: "矩阵遗留",
  stale_hub: "沉寂主题",
  off_topic_gem: "离题好文",
};

interface Draft {
  title: string;
  hypothesis: string;
  content: string;
  priority: string;
  project_id: string;
}

function draftFrom(idea: Idea | null): Draft {
  return {
    title: idea?.title ?? "",
    hypothesis: idea?.hypothesis ?? "",
    content: idea?.content ?? "",
    priority: idea?.priority ?? "normal",
    project_id: idea?.project_id != null ? String(idea.project_id) : "",
  };
}

export default function Ideas() {
  const api = useApi();
  const [tab, setTab] = useState<"ideas" | "gaps">("ideas");
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("all");
  const [priorityFilter, setPriorityFilter] = useState("all");
  const [gaps, setGaps] = useState<ResearchGap[] | null>(null);
  const [gapsLoading, setGapsLoading] = useState(false);
  const [editing, setEditing] = useState<Idea | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [draft, setDraft] = useState<Draft>(draftFrom(null));
  const [saving, setSaving] = useState(false);
  const [workspace, setWorkspace] = useState<ThesisWorkspace | null>(null);
  const [linkQuery, setLinkQuery] = useState("");
  const [linkRole, setLinkRole] = useState<string>("basis");
  // P13：该 Idea 关联的实验（只读展示）。
  const [ideaExperiments, setIdeaExperiments] = useState<Experiment[]>([]);
  const toast = useToast();
  const confirm = useConfirm();
  const listState = useRef({generation:0, mounted:true, statusFilter, priorityFilter});
  listState.current.statusFilter=statusFilter;listState.current.priorityFilter=priorityFilter;
  useEffect(()=>{listState.current.mounted=true;return()=>{listState.current.mounted=false;++listState.current.generation;};},[]);

  async function load() {
    if(!listState.current.mounted)return;
    const {statusFilter:status,priorityFilter:priority}=listState.current;
    const generation=++listState.current.generation;
    const current=()=>listState.current.mounted&&generation===listState.current.generation&&status===listState.current.statusFilter&&priority===listState.current.priorityFilter;
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (status !== "all") params.status = status;
      if (priority !== "all") params.priority = priority;
      const rows=await api.listIdeas(params);
      if(current())setIdeas(rows);
    } catch (e: any) {
      if(current())toast.error(e.message);
    } finally {
      if(current())setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, priorityFilter]);

  useEffect(() => {
    api
      .thesisWorkspace()
      .then(setWorkspace)
      .catch(() => setWorkspace(null));
  }, []);

  // P13：抽屉打开的 Idea 变化时拉取关联实验。
  useEffect(() => {
    if (!drawerOpen || !editing) {
      setIdeaExperiments([]);
      return;
    }
    let cancelled = false;
    api
      .listExperiments({ idea_id: editing.id, include_hidden: true })
      .then((rows) => {
        if (!cancelled) setIdeaExperiments(rows);
      })
      .catch(() => {
        if (!cancelled) setIdeaExperiments([]);
      });
    return () => {
      cancelled = true;
    };
  }, [drawerOpen, editing?.id, editing?.updated_at]);

  async function loadGaps() {
    setGapsLoading(true);
    try {
      setGaps(await api.researchGaps());
    } catch (e: any) {
      toast.error(e.message);
      setGaps([]);
    } finally {
      setGapsLoading(false);
    }
  }

  useEffect(() => {
    if (tab === "gaps" && gaps === null) loadGaps();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const projectOptions = useMemo(() => {
    const out: { id: number; label: string }[] = [];
    function walk(projects: ThesisWorkspace["projects"], prefix: string[]) {
      for (const project of projects ?? []) {
        out.push({ id: project.id, label: [...prefix, project.name].join(" / ") });
        walk(project.children, [...prefix, project.name]);
      }
    }
    walk(workspace?.projects ?? [], []);
    return out;
  }, [workspace]);

  const grouped = useMemo(() => {
    const by: Record<string, Idea[]> = {};
    for (const idea of ideas) {
      by[idea.status] = by[idea.status] ?? [];
      by[idea.status].push(idea);
    }
    return by;
  }, [ideas]);

  function openIdea(idea: Idea) {
    setEditing(idea);
    setDraft(draftFrom(idea));
    setLinkQuery("");
    setLinkRole("basis");
    setDrawerOpen(true);
  }

  function startCreate() {
    setEditing(null);
    setDraft(draftFrom(null));
    setLinkQuery("");
    setLinkRole("basis");
    setDrawerOpen(true);
  }

  async function save() {
    if (!draft.title.trim()) {
      toast.error("标题不能为空。");
      return;
    }
    setSaving(true);
    try {
      const body = {
        title: draft.title.trim(),
        hypothesis: draft.hypothesis.trim() || null,
        content: draft.content,
        priority: draft.priority,
        project_id: draft.project_id ? Number(draft.project_id) : null,
      };
      const saved = editing
        ? await api.patchIdea(editing.id, body)
        : await api.createIdea({ ...body, origin: "manual" });
      toast.success(editing ? "已保存。" : "想法已创建。");
      await load();
      if (saved) openIdea(saved);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function transition(status: string) {
    if (!editing) return;
    try {
      const next = await api.patchIdea(editing.id, { status });
      toast.success(`已流转到「${STATUS_LABELS[status] ?? status}」。`);
      await load();
      openIdea(next);
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function remove() {
    if (!editing) return;
    const ok = await confirm({
      title: "删除想法？",
      message: `将移除「${editing.title}」，此操作不可撤销。`,
      variant: "danger",
      confirmText: "删除",
    });
    if (!ok) return;
    try {
      await api.deleteIdea(editing.id);
      setDrawerOpen(false);
      setEditing(null);
      toast.success("已删除。");
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function linkPaper(paperId: number, role: string) {
    if (!editing) return;
    try {
      await api.linkIdeaPaper(editing.id, paperId, role);
      const refreshed = await api.getIdea(editing.id);
      setEditing(refreshed);
      setLinkQuery("");
      toast.success("已关联论文。");
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function unlinkPaper(paperId: number, role: string) {
    if (!editing) return;
    try {
      await api.unlinkIdeaPaper(editing.id, paperId, role);
      const refreshed = await api.getIdea(editing.id);
      setEditing(refreshed);
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function ideaFromGap(gap: ResearchGap) {
    try {
      await api.createIdea({
        title: gap.title,
        content: `来源：研究缺口（${GAP_TYPE_LABELS[gap.type] ?? gap.type}）。\n\n${gap.rationale}`,
        origin: "gap",
        papers: gap.paper_ids.slice(0, 3).map((paperId) => ({ paper_id: paperId, role: "basis" })),
      });
      toast.success("已从缺口创建想法。");
      setTab("ideas");
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  const linkedIds = new Set((editing?.papers ?? []).map((p) => `${p.paper_id}:${p.role}`));
  const search = usePaperSearch(linkQuery, drawerOpen && !!editing);
  const linkCandidates = search.papers.filter(p => !linkedIds.has(`${p.id}:${linkRole}`));

  return (
    <Shell max="narrow" className="space-y-5">
      <PageHeader
        title="Idea 工作台"
        subtitle="研究想法的生命周期管理：从研究缺口或 AI 建议出发，关联证据论文，一路推进到采纳或放弃"
        actions={
          <button onClick={startCreate} className="btn-primary">
            <Plus size={14} /> 新建想法
          </button>
        }
      />

      <Tabs
        tabs={[
          { key: "ideas", label: "想法", count: ideas.length },
          { key: "gaps", label: "研究缺口", count: gaps?.length },
        ]}
        value={tab}
        onChange={(v) => setTab(v as typeof tab)}
      />

      {tab === "ideas" ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <select className="input max-w-[10rem]" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="all">全部状态</option>
              {STATUS_ORDER.map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABELS[s]}
                </option>
              ))}
            </select>
            <select className="input max-w-[10rem]" value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)}>
              <option value="all">全部优先级</option>
              {Object.entries(PRIORITY_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <button onClick={load} disabled={loading} className="btn-ghost py-1.5 text-xs">
              {loading ? "加载中…" : "刷新"}
            </button>
          </div>

          {loading ? (
            <p className="text-sm text-faint">加载中…</p>
          ) : ideas.length === 0 ? (
            <EmptyState
              icon={<Lightbulb size={20} />}
              title="还没有研究想法"
              hint="从「研究缺口」一键创建，或在建议中心把 AI 关联建议转为想法。"
            />
          ) : (
            STATUS_ORDER.filter((status) => grouped[status]?.length).map((status) => (
              <section key={status} className="space-y-2">
                <h3 className="text-sm font-semibold text-muted">
                  {STATUS_LABELS[status]}
                  <span className="ml-2 text-xs text-faint">{grouped[status].length}</span>
                </h3>
                {grouped[status].map((idea) => (
                  <button
                    key={idea.id}
                    onClick={() => openIdea(idea)}
                    className="card-tight block w-full text-left transition hover:translate-y-[-1px]"
                    style={{ boxShadow: "var(--shadow)" }}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{idea.title}</span>
                      {idea.priority !== "normal" && (
                        <span className="chip">{PRIORITY_LABELS[idea.priority]}</span>
                      )}
                      <span className="chip">{ORIGIN_LABELS[idea.origin] ?? idea.origin}</span>
                      {idea.papers.length > 0 && <span className="chip">论文 ×{idea.papers.length}</span>}
                    </div>
                    {idea.hypothesis && (
                      <p className="mt-1 line-clamp-2 text-sm text-muted">假设：{idea.hypothesis}</p>
                    )}
                    {idea.content && (
                      <p className="mt-1 line-clamp-2 text-sm text-faint">{idea.content}</p>
                    )}
                  </button>
                ))}
              </section>
            ))
          )}
        </>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs text-faint">
              由矩阵遗留、沉寂主题与离题好文确定性聚合，不调用 AI。
            </p>
            <button onClick={loadGaps} disabled={gapsLoading} className="btn-ghost py-1 text-xs">
              {gapsLoading ? "计算中…" : "重新计算"}
            </button>
          </div>
          {gapsLoading && <p className="text-sm text-faint">加载中…</p>}
          {!gapsLoading && gaps !== null && gaps.length === 0 && (
            <EmptyState
              icon={<Lightbulb size={20} />}
              title="暂无研究缺口"
              hint="填写论文的审阅矩阵（局限/未来工作）、多读多评，缺口会自动浮现。"
            />
          )}
          {(gaps ?? []).map((gap, index) => (
            <div key={`${gap.type}-${index}`} className="card-tight" style={{ boxShadow: "var(--shadow)" }}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="chip">{GAP_TYPE_LABELS[gap.type] ?? gap.type}</span>
                <span className="font-medium">{gap.title}</span>
              </div>
              <p className="mt-1 text-sm text-muted">{gap.rationale}</p>
              <button onClick={() => ideaFromGap(gap)} className="btn-primary mt-2 py-1 text-xs">
                创建 Idea
              </button>
            </div>
          ))}
        </div>
      )}

      {/* 新建/编辑抽屉（selected=null 表示新建） */}
      <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} title={editing ? "编辑想法" : "新建想法"} width="max-w-xl">
        <div className="space-y-4">
          <label className="block">
            <span className="label">标题</span>
            <input
              className="input"
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              placeholder="一句话概括这个想法"
            />
          </label>
          <label className="block">
            <span className="label">假设（可选）</span>
            <input
              className="input"
              value={draft.hypothesis}
              onChange={(e) => setDraft({ ...draft, hypothesis: e.target.value })}
              placeholder="可验证的研究假设"
            />
          </label>
          <label className="block">
            <span className="label">内容（Markdown）</span>
            <textarea
              className="input min-h-[120px]"
              value={draft.content}
              onChange={(e) => setDraft({ ...draft, content: e.target.value })}
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="label">优先级</span>
              <select
                className="input"
                value={draft.priority}
                onChange={(e) => setDraft({ ...draft, priority: e.target.value })}
              >
                {Object.entries(PRIORITY_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="label">挂靠项目（可选）</span>
              <select
                className="input"
                value={draft.project_id}
                onChange={(e) => setDraft({ ...draft, project_id: e.target.value })}
              >
                <option value="">不挂靠</option>
                {projectOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="flex flex-wrap gap-2">
            <button onClick={save} disabled={saving} className="btn-primary py-1.5 text-sm">
              {saving ? "保存中…" : editing ? "保存" : "创建"}
            </button>
            {editing && (
              <>
                {(TRANSITIONS[editing.status] ?? []).map((status) => (
                  <button key={status} onClick={() => transition(status)} className="btn-ghost py-1.5 text-sm">
                    → {STATUS_LABELS[status]}
                  </button>
                ))}
                <button onClick={remove} className="btn-ghost py-1.5 text-sm text-[var(--danger)]" title="删除想法">
                  <Trash2 size={14} />
                </button>
              </>
            )}
          </div>

          {editing && (
            <div className="border-t pt-3 border-[var(--border)]">
              <h4 className="mb-2 text-sm font-semibold">关联实验</h4>
              {ideaExperiments.length === 0 ? (
                <p className="text-xs text-faint">
                  还没有关联实验。可在「论文库 → 课题与章节」的课题详情中打开「实验」，把实验关联到这个研究想法。
                </p>
              ) : (
                <ul className="space-y-1">
                  {ideaExperiments.map((experiment) => (
                    <li
                      key={experiment.id}
                      className="flex items-center gap-2 rounded-lg bg-[var(--surface-2)] px-2.5 py-1.5 text-sm"
                    >
                      <span className="chip shrink-0">
                        {EXPERIMENT_STATUS_LABELS[experiment.status] ?? experiment.status}
                      </span>
                      <span className="min-w-0 flex-1 truncate">{experiment.name}</span>
                      {experiment.log_count > 0 && (
                        <span className="shrink-0 text-[11px] text-faint">日志 ×{experiment.log_count}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {editing && (
            <div className="border-t pt-3 border-[var(--border)]">
              <h4 className="mb-2 text-sm font-semibold">关联论文</h4>
              <ul className="mb-2 space-y-1">
                {editing.papers.map((link) => (
                  <li key={`${link.paper_id}-${link.role}`} className="flex items-center gap-2 rounded-lg bg-[var(--surface-2)] px-2.5 py-1.5 text-sm">
                    <span className="chip shrink-0">{ROLE_LABELS[link.role] ?? link.role}</span>
                    <span className="min-w-0 flex-1 truncate">{link.title ?? `#${link.paper_id}`}</span>
                    <button
                      onClick={() => unlinkPaper(link.paper_id, link.role)}
                      className="shrink-0 text-faint hover:text-[var(--danger)]"
                      title="解除关联"
                    >
                      <X size={14} />
                    </button>
                  </li>
                ))}
                {editing.papers.length === 0 && (
                  <li className="text-xs text-faint">还没有关联论文。搜索并选择角色后添加。</li>
                )}
              </ul>
              <div className="flex gap-2">
                <input
                  className="input"
                  placeholder="按标题搜索论文…"
                  value={linkQuery}
                  onChange={(e) => setLinkQuery(e.target.value)}
                />
                <select className="input max-w-[7rem]" value={linkRole} onChange={(e) => setLinkRole(e.target.value)}>
                  {ROLE_OPTIONS.map((role) => (
                    <option key={role} value={role}>
                      {ROLE_LABELS[role]}
                    </option>
                  ))}
                </select>
              </div>
              {linkQuery.trim() && <p role={search.error ? "alert" : "status"} className="mt-2 text-xs text-muted">{search.searching ? "正在搜索整个论文库…" : search.error || (linkCandidates.length ? (search.total > 50 ? "显示前 50 篇匹配论文，请增加关键词缩小范围。" : "以下结果来自整个论文库。") : "没有可关联的匹配论文；已关联到该角色的论文不会重复显示。")}</p>}
              {linkCandidates.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {linkCandidates.map((paper) => (
                    <li key={paper.id}>
                      <button
                        onClick={() => linkPaper(paper.id, linkRole)}
                        className="w-full rounded-lg px-2.5 py-1.5 text-left text-sm hover:bg-[var(--surface-2)]"
                        title={linkedIds.has(`${paper.id}:${linkRole}`) ? "已在该角色关联" : `以「${ROLE_LABELS[linkRole]}」角色关联`}
                      >
                        {paper.title ?? `#${paper.id}`}
                        {paper.year ? ` · ${paper.year}` : ""}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </Drawer>
    </Shell>
  );
}
