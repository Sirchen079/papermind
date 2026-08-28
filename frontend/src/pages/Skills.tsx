import { useEffect, useState } from "react";
import { api } from "../api";
import { Check, RotateCw, X } from "../icons";
import { useConfirm } from "../components/ui/ConfirmDialog";
import { useToast } from "../components/ui/Toast";
import { SkeletonGroup } from "../components/ui/Skeleton";
import { Shell } from "../components/layout/Shell";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";

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
}

interface ToolResult {
  ok: boolean;
  stdout: string;
  stderr: string;
  exit_code: number;
  duration_ms: number;
}

export default function Skills() {
  const [skills, setSkills] = useState<Skill[]>([]);
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
        name: form.name,
        type: form.type,
        trigger: form.trigger,
        keywords: form.keywords.split(",").map((k) => k.trim()).filter(Boolean),
        body: form.body,
        enabled: true,
      });
      setForm({ name: "", type: "instruction", trigger: "manual", keywords: "", body: "" });
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

  return (
    <Shell max="narrow" className="space-y-6">
      <PageHeader
        title="技能"
        subtitle="注入到助手中的声明式能力"
        actions={
          <button onClick={reload} className="btn-ghost">
            <RotateCw size={14} /> 从文件夹重新加载
          </button>
        }
      />
      <section className="card">
        <h3 className="mb-3 font-semibold">新建技能</h3>
        <div className="mb-3 grid grid-cols-1 gap-3 md:grid-cols-3">
          <input
            className="input"
            placeholder="名称"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <select className="input" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
            {["instruction", "template", "tool", "persona"].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <select className="input" value={form.trigger} onChange={(e) => setForm({ ...form, trigger: e.target.value })}>
            {["manual", "auto", "keyword", "pipeline"].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <input
            className="input md:col-span-3"
            placeholder="keyword 触发的关键词（逗号分隔，如 review, critique）"
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
        <button onClick={add} className="btn-primary mt-3">
          保存技能
        </button>
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
              <span className="chip">{s.type}</span>
              <span className="text-xs text-faint">
                {s.trigger}
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
