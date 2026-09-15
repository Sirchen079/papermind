import { useApi } from '../workspaceContext';
import { useEffect, useState } from "react";
import {} from "../api";
import { Check, RotateCw, X } from "../icons";
import { useConfirm } from "../components/ui/ConfirmDialog";
import { useToast } from "../components/ui/Toast";
import { SkeletonGroup } from "../components/ui/Skeleton";
import { Shell } from "../components/layout/Shell";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";

const TYPE_LABELS: Record<string, string> = { instruction: "回答指令", template: "内容模板", tool: "代码工具", persona: "助手角色" };
const TRIGGER_LABELS: Record<string, string> = { manual: "手动选择", auto: "自动应用", keyword: "关键词触发", pipeline: "处理流程" };

interface Skill {
  id: number;
  name: string;
  type: string;
  trigger: string;
  keywords: string[];
  description: string | null;
  body: string | null;
  enabled: boolean;
  source: string;
  model_role?: string | null;
}

interface ToolResult {
  ok: boolean;
  stdout: string;
  stderr: string;
  exit_code: number;
  duration_ms: number;
}

export default function Skills() {
  const api = useApi();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [editing, setEditing] = useState<Skill | null>(null);
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [form, setForm] = useState({ name: "", type: "instruction", trigger: "manual", keywords: "", body: "" });
  const [runningId, setRunningId] = useState<number | null>(null);
  const [results, setResults] = useState<Record<number, ToolResult>>({});
  const [loading, setLoading] = useState(true);
  const toast = useToast();
  const confirm = useConfirm();

  async function load() {
    try {
      setSkills(await api.listSkills());
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function add() {
    try {
      await api.upsertSkill({
        description: editing?.description ?? null,
        model_role: editing?.model_role ?? null,
        name: form.name,
        type: form.type,
        trigger: form.trigger,
        keywords: form.keywords.split(",").map((k) => k.trim()).filter(Boolean),
        body: form.body,
        enabled: editing?.enabled ?? true,
      });
      setForm({ name: "", type: "instruction", trigger: "manual", keywords: "", body: "" });
      setEditing(null);
      toast.success("已保存技能。");
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function reload() {
    try {
      const r = await api.reloadSkills();
      toast.success(`已从 user_skills/ 加载 ${r.loaded} 个技能。`);
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function remove(s: Skill) {
    const ok = await confirm({
      title: "删除技能？",
      message: `将删除「${s.name}」，此操作不可撤销。`,
      variant: "danger",
      confirmText: "删除",
    });
    if (!ok) return;
    try {
      await api.deleteSkill(s.id);
      toast.success("已删除技能。");
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function runSkill(id: number) {
    setRunningId(id);
    try {
      const r = await api.runSkill(id);
      setResults((prev) => ({ ...prev, [id]: r }));
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setRunningId(null);
    }
  }

  async function toggleSkill(s: Skill) {
    if (updatingId !== null) return;
    setUpdatingId(s.id);
    try {
      await api.upsertSkill({ ...s, enabled: !s.enabled });
      await load();
      setEditing(current => current?.id === s.id ? { ...current, enabled: !s.enabled } : current);
    } catch (error: any) { toast.error(error.message); }
    finally { setUpdatingId(null); }
  }

  return (
    <Shell max="narrow" className="space-y-6">
      <PageHeader
        title="技能"
        subtitle="设置助手的回答要求、角色与可复用模板"
        actions={
          <button onClick={reload} className="btn-ghost">
            <RotateCw size={14} /> 从文件夹重新加载
          </button>
        }
      />
      <section className="card">
        <h3 className="mb-3 font-semibold">{editing ? `编辑技能：${editing.name}` : "新建技能"}</h3>
        <p className="mb-3 text-xs text-muted">手动选择的回答指令与助手角色保存后，在问答输入框上方的「本轮技能」中选择，再发送问题。</p>
        <div className="mb-3 grid grid-cols-1 gap-3 md:grid-cols-3">
          <input
            className="input"
            placeholder="名称"
            readOnly={!!editing}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <select className="input" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
            {["instruction", "template", "tool", "persona"].map((t) => (
              <option key={t} value={t}>{TYPE_LABELS[t] ?? t}</option>
            ))}
          </select>
          <select className="input" value={form.trigger} onChange={(e) => setForm({ ...form, trigger: e.target.value })}>
            {["manual", "auto", "keyword", "pipeline"].map((t) => (
              <option key={t} value={t}>{TRIGGER_LABELS[t] ?? t}</option>
            ))}
          </select>
          <input
            className="input md:col-span-3"
            placeholder="触发关键词（逗号分隔，如 文献评述, 方法比较）"
            value={form.keywords}
            onChange={(e) => setForm({ ...form, keywords: e.target.value })}
          />
        </div>
        <textarea
          className="input h-28 resize-none font-mono"
          placeholder={
            form.type === "tool"
              ? "Python 代码——library/papers/user_input 已预加载；用 print() 返回结果"
              : "技能指令（markdown）…"
          }
          value={form.body}
          onChange={(e) => setForm({ ...form, body: e.target.value })}
        />
        <button onClick={add} disabled={updatingId !== null} className="btn-primary mt-3">
          保存技能
        </button>
        {editing && <button className="btn-ghost ml-2" onClick={() => { setEditing(null); setForm({ name: "", type: "instruction", trigger: "manual", keywords: "", body: "" }); }}>取消编辑</button>}
      </section>

      <section className="space-y-2">
        {loading ? (
          <SkeletonGroup variant="row" count={4} />
        ) : skills.length === 0 ? (
          <EmptyState title="还没有技能" hint="新建一个指令、模板、工具或人格技能。" />
        ) : null}
        {skills.map((s) => (
          <div key={s.id} className="card-tight" style={{ boxShadow: "var(--shadow)" }}>
            <div className="flex items-center gap-2">
              <span className="font-medium">{s.name}</span>
              <span className="chip">{TYPE_LABELS[s.type] ?? s.type}</span>
              <span className="chip">{s.enabled ? "已启用" : "已停用"}</span>
              <span className="text-xs text-faint">
                {TRIGGER_LABELS[s.trigger] ?? s.trigger}
              </span>
              {s.keywords.length > 0 && (
                <span className="text-xs text-faint">
                  · {s.keywords.join(", ")}
                </span>
              )}
              <span className="ml-auto text-xs text-faint">
                {s.source}
              </span>
              {s.type === "tool" && (
                <button
                  onClick={() => runSkill(s.id)}
                  disabled={runningId === s.id}
                  className="btn-subtle px-2 text-sm"
                >
                  {runningId === s.id ? "运行中…" : "运行"}
                </button>
              )}
              <button className="btn-subtle px-2 text-sm" disabled={updatingId !== null} onClick={() => { setEditing(s); setForm({ name: s.name, type: s.type, trigger: s.trigger, keywords: s.keywords.join(", "), body: s.body ?? "" }); document.querySelector('main')?.scrollTo({ top: 0 }); }}>编辑</button>
              <button className="btn-subtle px-2 text-sm" disabled={updatingId !== null} onClick={() => toggleSkill(s)}>{updatingId === s.id ? "更新中…" : s.enabled ? "停用" : "启用"}</button>
              <button onClick={() => remove(s)} className="btn-subtle px-2 text-sm text-[var(--danger)]">
                删除
              </button>
            </div>
            {s.description && (
              <p className="mt-1 text-sm text-muted">
                {s.description}
              </p>
            )}
            {s.body && (
              <pre className="mt-2 whitespace-pre-wrap font-mono text-xs text-muted">
                {s.body.slice(0, 200)}
                {s.body.length > 200 ? "…" : ""}
              </pre>
            )}
            {s.type === "tool" && results[s.id] && (
              <div
                className="mt-2 rounded-lg p-2.5 text-xs"
                style={{ backgroundColor: "var(--surface-2)" }}
              >
                <div className="mb-1 flex items-center gap-2 text-faint">
                  <span>
                    {results[s.id].ok ? (<><Check size={11} /> 正常退出</>) : (<><X size={11} /> 退出码 {results[s.id].exit_code}</>)}
                  </span>
                  <span>· {results[s.id].duration_ms} ms</span>
                </div>
                {results[s.id].stdout && (
                  <pre className="whitespace-pre-wrap font-mono text-[var(--text)]">
                    {results[s.id].stdout.slice(-2000)}
                  </pre>
                )}
                {results[s.id].stderr && (
                  <pre className="whitespace-pre-wrap font-mono text-[var(--danger)]">
                    {results[s.id].stderr.slice(-2000)}
                  </pre>
                )}
              </div>
            )}
          </div>
        ))}
      </section>
    </Shell>
  );
}
