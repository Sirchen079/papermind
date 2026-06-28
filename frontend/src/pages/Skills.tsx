import { useEffect, useState } from "react";
import { api } from "../api";

interface Skill {
  id: number;
  name: string;
  type: string;
  trigger: string;
  description: string | null;
  body: string | null;
  enabled: boolean;
  source: string;
}

export default function Skills() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", type: "instruction", trigger: "manual", body: "" });

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
        body: form.body,
        enabled: true,
      });
      setForm({ name: "", type: "instruction", trigger: "manual", body: "" });
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
      <div className="flex items-center gap-3">
        <h2 className="text-2xl font-bold">Skills</h2>
        <button onClick={reload} className="text-sm text-slate-600 underline">
          reload from folder
        </button>
      </div>
      {msg && <div className="text-green-700 text-sm">{msg}</div>}
      {err && <div className="text-red-600 text-sm">{err}</div>}

      <section className="bg-white rounded-lg shadow p-4">
        <h3 className="font-semibold mb-3">New Skill</h3>
        <div className="grid grid-cols-3 gap-3 mb-3">
          <input className="border rounded px-2 py-1.5 text-sm col-span-1" placeholder="name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select className="border rounded px-2 py-1.5 text-sm" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
            {["instruction", "template", "persona"].map((t) => <option key={t}>{t}</option>)}
          </select>
          <select className="border rounded px-2 py-1.5 text-sm" value={form.trigger} onChange={(e) => setForm({ ...form, trigger: e.target.value })}>
            {["manual", "auto", "keyword", "pipeline"].map((t) => <option key={t}>{t}</option>)}
          </select>
        </div>
        <textarea className="w-full border rounded p-2 text-sm font-mono h-28" placeholder="skill instructions (markdown)…" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
        <button onClick={add} className="mt-2 bg-slate-900 text-white px-3 py-1.5 rounded text-sm">Save</button>
      </section>

      <section className="space-y-2">
        {skills.length === 0 && <p className="text-slate-400 text-sm">No skills yet.</p>}
        {skills.map((s) => (
          <div key={s.id} className="bg-white rounded-lg shadow p-3">
            <div className="flex items-center gap-2">
              <span className="font-medium">{s.name}</span>
              <span className="text-xs bg-slate-100 px-2 py-0.5 rounded">{s.type}</span>
              <span className="text-xs text-slate-400">{s.trigger}</span>
              <span className="text-xs text-slate-400 ml-auto">{s.source}</span>
              <button onClick={() => remove(s.id)} className="text-sm text-red-500">delete</button>
            </div>
            {s.description && <p className="text-sm text-slate-500 mt-1">{s.description}</p>}
            {s.body && <pre className="text-xs text-slate-600 mt-2 whitespace-pre-wrap font-mono">{s.body.slice(0, 200)}{s.body.length > 200 ? "…" : ""}</pre>}
          </div>
        ))}
      </section>
    </div>
  );
}
