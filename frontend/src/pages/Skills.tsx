import { useEffect, useState } from "react";
import { api } from "../api";

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

export default function Skills() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", type: "instruction", trigger: "manual", keywords: "", body: "" });

  async function load() {
    try {
      setSkills(await api.listSkills());
    } catch (e: any) {
      setErr(e.message);
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function add() {
    setErr(null);
    setMsg(null);
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
      await load();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function reload() {
    try {
      const r = await api.reloadSkills();
      setMsg(`Loaded ${r.loaded} skill(s) from user_skills/.`);
      await load();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function remove(id: number) {
    await api.deleteSkill(id);
    await load();
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          Declarative capabilities injected into the assistant.
        </p>
        <button onClick={reload} className="btn-ghost">
          ↻ Reload from folder
        </button>
      </div>
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

      <section className="card">
        <h3 className="mb-3 font-semibold">New skill</h3>
        <div className="mb-3 grid grid-cols-1 gap-3 md:grid-cols-3">
          <input
            className="input"
            placeholder="name"
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
            placeholder="keywords for keyword trigger (comma-separated, e.g. review, critique)"
            value={form.keywords}
            onChange={(e) => setForm({ ...form, keywords: e.target.value })}
          />
        </div>
        <textarea
          className="input h-28 resize-none font-mono"
          placeholder="skill instructions (markdown)…"
          value={form.body}
          onChange={(e) => setForm({ ...form, body: e.target.value })}
        />
        <button onClick={add} className="btn-primary mt-3">
          Save skill
        </button>
      </section>

      <section className="space-y-2">
        {skills.length === 0 && (
          <div className="card text-center text-sm" style={{ color: "var(--muted)" }}>
            No skills yet.
          </div>
        )}
        {skills.map((s) => (
          <div key={s.id} className="card-tight" style={{ boxShadow: "var(--shadow)" }}>
            <div className="flex items-center gap-2">
              <span className="font-medium">{s.name}</span>
              <span className="chip">{s.type}</span>
              <span className="text-xs" style={{ color: "var(--faint)" }}>
                {s.trigger}
              </span>
              {s.keywords.length > 0 && (
                <span className="text-xs" style={{ color: "var(--faint)" }}>
                  · {s.keywords.join(", ")}
                </span>
              )}
              <span className="ml-auto text-xs" style={{ color: "var(--faint)" }}>
                {s.source}
              </span>
              <button onClick={() => remove(s.id)} className="btn-subtle px-2 text-sm" style={{ color: "var(--danger)" }}>
                delete
              </button>
            </div>
            {s.description && (
              <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
                {s.description}
              </p>
            )}
            {s.body && (
              <pre
                className="mt-2 whitespace-pre-wrap font-mono text-xs"
                style={{ color: "var(--muted)" }}
              >
                {s.body.slice(0, 200)}
                {s.body.length > 200 ? "…" : ""}
              </pre>
            )}
          </div>
        ))}
      </section>
    </div>
  );
}
