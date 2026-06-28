import { useEffect, useState } from "react";
import { api, type Provider, type Model } from "../api";

const TYPES = ["openai_chat", "openai_responses", "anthropic", "openai_compat"];
const ROLES = ["summary", "extraction", "chat", "deep", "embedding"];

interface Usage {
  total_tokens: number;
  by_kind: Record<string, number>;
  by_model: Record<string, number>;
}

export default function Settings() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [models, setModels] = useState<Record<number, Model[]>>({});
  const [usage, setUsage] = useState<Usage | null>(null);
  const [form, setForm] = useState({ name: "", type: "openai_chat", base_url: "", api_key: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setProviders(await api.listProviders());
    setUsage(await api.usage());
  }
  useEffect(() => {
    load();
  }, []);

  async function add() {
    setErr(null);
    setMsg(null);
    try {
      const body: Record<string, unknown> = { name: form.name, type: form.type };
      if (form.base_url) body.base_url = form.base_url;
      if (form.api_key) body.api_key = form.api_key;
      const p = await api.createProvider(body);
      setMsg(`Added provider "${p.name}".`);
      setForm({ name: "", type: "openai_chat", base_url: "", api_key: "" });
      await load();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function refresh(id: number) {
    setErr(null);
    try {
      const r = await api.refreshModels(id);
      setModels({ ...models, [id]: await api.providerModels(id) });
      setMsg(`Fetched ${r.count} models.`);
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function setRole(id: number, mid: number, role: string) {
    await api.setModelRole(mid, role);
    setModels({ ...models, [id]: await api.providerModels(id) });
  }

  return (
    <div className="max-w-3xl space-y-6">
      <h2 className="text-2xl font-bold">Settings</h2>
      {msg && <div className="text-green-700 text-sm">{msg}</div>}
      {err && <div className="text-red-600 text-sm">{err}</div>}

      <section className="bg-white rounded-lg shadow p-4">
        <h3 className="font-semibold mb-3">Add LLM Provider</h3>
        <div className="grid grid-cols-2 gap-3">
          <input className="border rounded px-2 py-1.5 text-sm" placeholder="name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select className="border rounded px-2 py-1.5 text-sm" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
            {TYPES.map((t) => <option key={t}>{t}</option>)}
          </select>
          <input className="border rounded px-2 py-1.5 text-sm" placeholder="base_url (required for openai_compat)" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
          <input className="border rounded px-2 py-1.5 text-sm" type="password" placeholder="api_key" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
        </div>
        <button onClick={add} className="mt-3 bg-slate-900 text-white px-3 py-1.5 rounded text-sm">Add</button>
      </section>

      <section className="bg-white rounded-lg shadow p-4">
        <h3 className="font-semibold mb-3">Providers & Models</h3>
        {providers.length === 0 && <p className="text-slate-400 text-sm">No providers yet.</p>}
        <div className="space-y-3">
          {providers.map((p) => (
            <div key={p.id} className="border rounded p-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="font-medium">{p.name}</span>
                <span className="text-xs bg-slate-100 px-2 py-0.5 rounded">{p.type}</span>
                <button onClick={() => refresh(p.id)} className="ml-auto text-sm text-slate-600 underline">refresh models</button>
              </div>
              <div className="space-y-1">
                {(models[p.id] ?? []).map((m) => (
                  <div key={m.id} className="flex items-center gap-2 text-sm">
                    <span className="flex-1">{m.display_name ?? m.model_id}</span>
                    <select
                      className="border rounded px-1 py-0.5 text-xs"
                      value={m.role_default ?? ""}
                      onChange={(e) => setRole(p.id, m.id, e.target.value)}
                    >
                      <option value="">— role —</option>
                      {ROLES.map((r) => <option key={r}>{r}</option>)}
                    </select>
                  </div>
                ))}
                {p.id in models && models[p.id].length === 0 && (
                  <p className="text-xs text-slate-400">No models. Click "refresh models".</p>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      {usage && (
        <section className="bg-white rounded-lg shadow p-4">
          <h3 className="font-semibold mb-3">Token Usage (30d)</h3>
          <div className="text-2xl font-bold mb-2">{usage.total_tokens.toLocaleString()} tokens</div>
          <div className="flex gap-4 text-sm">
            <div>
              <div className="text-slate-500 mb-1">by kind</div>
              {Object.entries(usage.by_kind).map(([k, v]) => (
                <div key={k}>{k}: {v.toLocaleString()}</div>
              ))}
              {Object.keys(usage.by_kind).length === 0 && <span className="text-slate-400">—</span>}
            </div>
            <div>
              <div className="text-slate-500 mb-1">by model</div>
              {Object.entries(usage.by_model).map(([k, v]) => (
                <div key={k}>{k}: {v.toLocaleString()}</div>
              ))}
              {Object.keys(usage.by_model).length === 0 && <span className="text-slate-400">—</span>}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
