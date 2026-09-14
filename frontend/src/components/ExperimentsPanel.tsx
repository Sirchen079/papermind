import { useApi } from '../workspaceContext';
import { useEffect, useState } from "react";
import { type Experiment, type ExperimentLog, type Idea, type Paper } from "../api";
import { Plus, Trash2, X } from "../icons";
import { useToast } from "./ui/Toast";
import { useConfirm } from "./ui/ConfirmDialog";
import { Drawer } from "./ui/Drawer";
import { usePaperSearch } from "./usePaperSearch";
import { shouldSubmitOnEnter } from "../pages/keyGuardModel";

// 与后端枚举一致，仅做中文展示。
export const EXPERIMENT_STATUS_LABELS: Record<string, string> = {
  planned: "已计划",
  running: "进行中",
  analyzing: "分析中",
  done: "已完成",
  abandoned: "已放弃",
};
const STATUS_ORDER = ["planned", "running", "analyzing", "done", "abandoned"] as const;

// 与后端 EXPERIMENT_TRANSITIONS 保持一致（P13.2 状态机）。
const TRANSITIONS: Record<string, string[]> = {
  planned: ["running"],
  running: ["analyzing"],
  analyzing: ["done", "abandoned"],
  done: [],
  abandoned: [],
};

const ROLE_LABELS: Record<string, string> = {
  baseline: "基线",
  method: "方法",
  dataset: "数据集",
};
const ROLE_OPTIONS = ["baseline", "method", "dataset"] as const;

function statusChip(status: string) {
  const color =
    status === "done"
      ? "var(--success)"
      : status === "abandoned"
        ? "var(--danger)"
        : status === "planned"
          ? "var(--faint)"
          : "var(--accent)";
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[11px]"
      style={{ color, backgroundColor: `color-mix(in srgb, ${color} 12%, transparent)` }}
    >
      {EXPERIMENT_STATUS_LABELS[status] ?? status}
    </span>
  );
}

interface Props {
  projectId: number;
  papers: Paper[];
}

export default function ExperimentsPanel({ projectId }: Props) {
  const api = useApi();
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<Experiment | null>(null);
  const [logs, setLogs] = useState<ExperimentLog[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [draft, setDraft] = useState<{ name: string; hypothesis: string; idea_id: string }>({
    name: "",
    hypothesis: "",
    idea_id: "",
  });
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [logText, setLogText] = useState("");
  const [linkQuery, setLinkQuery] = useState("");
  const [linkRole, setLinkRole] = useState<string>("baseline");
  const [saving, setSaving] = useState(false);
  const toast = useToast();
  const confirm = useConfirm();

  async function load() {
    setLoading(true);
    try {
      const params: Record<string, string> = { project_id: String(projectId) };
      if (statusFilter !== "all") params.status = statusFilter;
      setExperiments(await api.listExperiments(params));
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, statusFilter]);

  useEffect(() => {
    api
      .listIdeas()
      .then(setIdeas)
      .catch(() => setIdeas([]));
  }, []);

  function openExperiment(experiment: Experiment) {
    setEditing(experiment);
    setDraft({
      name: experiment.name,
      hypothesis: experiment.hypothesis ?? "",
      idea_id: experiment.idea_id != null ? String(experiment.idea_id) : "",
    });
    setLogText("");
    setLinkQuery("");
    setDrawerOpen(true);
    api
      .listExperimentLogs(experiment.id)
      .then(setLogs)
      .catch(() => setLogs([]));
  }

  function startCreate() {
    setEditing(null);
    setLogs([]);
    setDraft({ name: "", hypothesis: "", idea_id: "" });
    setLogText("");
    setLinkQuery("");
    setDrawerOpen(true);
  }

  async function refreshEditing(id: number) {
    const fresh = await api.getExperiment(id);
    setEditing(fresh);
    return fresh;
  }

  async function save() {
    if (!draft.name.trim()) {
      toast.error("实验名称不能为空。");
      return;
    }
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        name: draft.name.trim(),
        hypothesis: draft.hypothesis.trim() || null,
        project_id: projectId,
        idea_id: draft.idea_id ? Number(draft.idea_id) : null,
      };
      const saved = editing
        ? await api.patchExperiment(editing.id, body)
        : await api.createExperiment(body);
      toast.success(editing ? "实验已保存。" : "实验已创建。");
      await load();
      openExperiment(await refreshEditing(saved.id));
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function transition(status: string) {
    if (!editing) return;
    try {
      await api.patchExperiment(editing.id, { status });
      toast.success(`已流转到「${EXPERIMENT_STATUS_LABELS[status] ?? status}」。`);
      await load();
      openExperiment(await refreshEditing(editing.id));
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function remove() {
    if (!editing) return;
    const ok = await confirm({
      title: "删除实验？",
      message: `将移除「${editing.name}」及其入口（时间线数据保留在备份中），此操作不可撤销。`,
      variant: "danger",
      confirmText: "删除",
    });
    if (!ok) return;
    try {
      await api.deleteExperiment(editing.id);
      setDrawerOpen(false);
      setEditing(null);
      toast.success("已删除。");
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function appendLog() {
    if (!editing || !logText.trim()) return;
    try {
      await api.addExperimentLog(editing.id, logText.trim());
      setLogText("");
      setLogs(await api.listExperimentLogs(editing.id));
      await refreshEditing(editing.id);
      await load();
      toast.success("已追加一条日志。");
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function deleteLog(logId: number) {
    if (!editing) return;
    try {
      await api.deleteExperimentLog(editing.id, logId);
      setLogs(await api.listExperimentLogs(editing.id));
      await refreshEditing(editing.id);
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function linkPaper(paperId: number, role: string) {
    if (!editing) return;
    try {
      await api.linkExperimentPaper(editing.id, paperId, role);
      await refreshEditing(editing.id);
      setLinkQuery("");
      toast.success("已关联论文。");
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function unlinkPaper(paperId: number, role: string) {
    if (!editing) return;
    try {
      await api.unlinkExperimentPaper(editing.id, paperId, role);
      await refreshEditing(editing.id);
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  const linkedIds = new Set((editing?.papers ?? []).map((p) => `${p.paper_id}:${p.role}`));
  const search = usePaperSearch(linkQuery, drawerOpen && !!editing);
  const linkCandidates = search.papers.filter(p => !linkedIds.has(`${p.id}:${linkRole}`));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="input max-w-[9rem] py-1 text-xs"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="all">全部状态</option>
          {STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {EXPERIMENT_STATUS_LABELS[s]}
            </option>
          ))}
        </select>
        <button onClick={startCreate} className="btn-primary py-1 text-xs">
          <Plus size={13} className="inline" /> 新建实验
        </button>
        <button onClick={load} disabled={loading} className="btn-ghost py-1 text-xs">
          {loading ? "加载中…" : "刷新"}
        </button>
        <span className="chip">{experiments.length} 个实验</span>
      </div>

      {experiments.length === 0 ? (
        <p className="text-sm text-muted">
          本项目还没有实验。实验记录「做了什么、为什么做、对照哪篇基线论文」。
        </p>
      ) : (
        <div className="space-y-2">
          {experiments.map((experiment) => (
            <button
              key={experiment.id}
              onClick={() => openExperiment(experiment)}
              className="block w-full rounded-lg border px-3 py-2 text-left"
              style={{ borderColor: "var(--border)", backgroundColor: "var(--surface)" }}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{experiment.name}</span>
                {statusChip(experiment.status)}
                {experiment.log_count > 0 && <span className="chip">日志 ×{experiment.log_count}</span>}
                {experiment.papers.length > 0 && (
                  <span className="chip">论文 ×{experiment.papers.length}</span>
                )}
              </div>
              {experiment.hypothesis && (
                <p className="mt-1 line-clamp-1 text-xs text-muted">假设：{experiment.hypothesis}</p>
              )}
            </button>
          ))}
        </div>
      )}

      {/* 实验编辑抽屉（editing=null 表示新建） */}
      <Drawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title={editing ? "编辑实验" : "新建实验"}
        width="max-w-xl"
      >
        <div className="space-y-4">
          <label className="block">
            <span className="label">名称</span>
            <input
              className="input"
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              placeholder="例如：两级缓存消融实验"
            />
          </label>
          <label className="block">
            <span className="label">假设（可选）</span>
            <input
              className="input"
              value={draft.hypothesis}
              onChange={(e) => setDraft({ ...draft, hypothesis: e.target.value })}
              placeholder="这个实验要验证什么"
            />
          </label>
          <label className="block">
            <span className="label">关联研究想法（可选）</span>
            <select
              className="input"
              value={draft.idea_id}
              onChange={(e) => setDraft({ ...draft, idea_id: e.target.value })}
            >
              <option value="">不关联</option>
              {ideas.map((idea) => (
                <option key={idea.id} value={idea.id}>
                  {idea.title}
                </option>
              ))}
            </select>
          </label>

          <div className="flex flex-wrap gap-2">
            <button onClick={save} disabled={saving} className="btn-primary py-1.5 text-sm">
              {saving ? "保存中…" : editing ? "保存" : "创建"}
            </button>
            {editing && (
              <>
                {(TRANSITIONS[editing.status] ?? []).map((status) => (
                  <button key={status} onClick={() => transition(status)} className="btn-ghost py-1.5 text-sm">
                    → {EXPERIMENT_STATUS_LABELS[status]}
                  </button>
                ))}
                <button
                  onClick={remove}
                  className="btn-ghost py-1.5 text-sm text-[var(--danger)]"
                  title="删除实验"
                >
                  <Trash2 size={14} />
                </button>
              </>
            )}
          </div>

          {editing && (
            <>
              <div className="border-t pt-3 border-[var(--border)]">
                <h4 className="mb-2 text-sm font-semibold">关联论文</h4>
                <ul className="mb-2 space-y-1">
                  {editing.papers.map((link) => (
                    <li
                      key={`${link.paper_id}-${link.role}`}
                      className="flex items-center gap-2 rounded-lg bg-[var(--surface-2)] px-2.5 py-1.5 text-sm"
                    >
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
                    <li className="text-xs text-faint">还没有关联论文。可标注基线 / 方法 / 数据集。</li>
                  )}
                </ul>
                <div className="flex gap-2">
                  <input
                    className="input"
                    placeholder="按标题搜索论文…"
                    value={linkQuery}
                    onChange={(e) => setLinkQuery(e.target.value)}
                  />
                  <select
                    className="input max-w-[7rem]"
                    value={linkRole}
                    onChange={(e) => setLinkRole(e.target.value)}
                  >
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
                          title={`以「${ROLE_LABELS[linkRole]}」角色关联`}
                        >
                          {paper.title ?? `#${paper.id}`}
                          {paper.year ? ` · ${paper.year}` : ""}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="border-t pt-3 border-[var(--border)]">
                <h4 className="mb-2 text-sm font-semibold">时间线日志</h4>
                <div className="mb-2 flex gap-2">
                  <input
                    className="input"
                    placeholder="记录一条进展（不可再编辑）…"
                    value={logText}
                    onChange={(e) => setLogText(e.target.value)}
                    onKeyDown={(e) => {
                      if (shouldSubmitOnEnter(e.key, false, e.nativeEvent.isComposing)) appendLog();
                    }}
                  />
                  <button onClick={appendLog} disabled={!logText.trim()} className="btn-primary shrink-0 py-1 text-xs">
                    追加
                  </button>
                </div>
                {logs.length === 0 ? (
                  <p className="text-xs text-faint">还没有日志。日志按时间正序展示，只能追加或删除。</p>
                ) : (
                  <ul className="max-h-56 space-y-1 overflow-auto">
                    {logs.map((log) => (
                      <li
                        key={log.id}
                        className="flex items-start gap-2 rounded-lg bg-[var(--surface-2)] px-2.5 py-1.5 text-sm"
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block whitespace-pre-wrap">{log.content}</span>
                          <span className="text-[11px] text-faint">
                            {log.created_at ? new Date(log.created_at).toLocaleString() : ""}
                          </span>
                        </span>
                        <button
                          onClick={() => deleteLog(log.id)}
                          className="shrink-0 text-faint hover:text-[var(--danger)]"
                          title="删除该条日志"
                        >
                          <Trash2 size={13} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </div>
      </Drawer>
    </div>
  );
}
