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
  const [indexing, setIndexing] = useState(false);
  const [indexMsg, setIndexMsg] = useState<string | null>(null);

  async function load() {
    try {
      setProviders(await api.listProviders());
      setUsage(await api.usage());
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

  async function reindex() {
    setIndexing(true);
    setIndexMsg(null);
    setErr(null);
    try {
      const r = await api.reindexLibrary();
      setIndexMsg(
        r.chunks > 0 ? `${r.chunks} chunk(s) indexed.` : "No embedding model configured.",
      );
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setIndexing(false);
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
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
        <h3 className="mb-3 font-semibold">Add LLM provider</h3>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <input
            className="input"
            placeholder="name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <select className="input" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
            {TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <input
            className="input"
            placeholder="base_url (required for openai_compat)"
            value={form.base_url}
            onChange={(e) => setForm({ ...form, base_url: e.target.value })}
          />
          <input
            className="input"
            type="password"
            placeholder="api_key (encrypted at rest)"
            value={form.api_key}
            onChange={(e) => setForm({ ...form, api_key: e.target.value })}
          />
        </div>
        <button onClick={add} className="btn-primary mt-3">
          Add provider
        </button>
      </section>

      <section className="card">
        <h3 className="mb-3 font-semibold">Providers &amp; models</h3>
        {providers.length === 0 && (
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            No providers yet.
          </p>
        )}
        <div className="space-y-3">
          {providers.map((p) => (
            <div key={p.id} className="rounded-lg border p-3" style={{ borderColor: "var(--border)" }}>
              <div className="mb-2 flex items-center gap-2">
                <span className="font-medium">{p.name}</span>
                <span className="chip">{p.type}</span>
                <span
                  className="text-xs"
                  style={{ color: p.enabled ? "var(--success)" : "var(--faint)" }}
                >
                  {p.enabled ? "enabled" : "disabled"}
                </span>
                <button onClick={() => refresh(p.id)} className="btn-ghost ml-auto py-1">
                  Refresh models
                </button>
              </div>
              <div className="space-y-1">
                {(models[p.id] ?? []).map((m) => (
                  <div key={m.id} className="flex items-center gap-2 text-sm">
                    <span className="flex-1 font-mono">{m.display_name ?? m.model_id}</span>
                    <select
                      className="input w-32 py-1 text-xs"
                      value={m.role_default ?? ""}
                      onChange={(e) => setRole(p.id, m.id, e.target.value)}
                    >
                      <option value="">— role —</option>
                      {ROLES.map((r) => (
                        <option key={r}>{r}</option>
                      ))}
                    </select>
                  </div>
                ))}
                {p.id in models && models[p.id].length === 0 && (
                  <p className="text-xs" style={{ color: "var(--faint)" }}>
                    No models. Click “Refresh models”.
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <h3 className="mb-1 font-semibold">Retrieval (RAG)</h3>
        <p className="mb-3 text-sm" style={{ color: "var(--muted)" }}>
          Assign a dedicated model the <span className="chip">embedding</span> role above so chat can
          answer from your papers' full text. Any OpenAI-compatible embeddings endpoint works — e.g.
          a free SiliconFlow <code>bge</code> model via an{" "}
          <code>openai_compat</code> provider. Then index the library.
        </p>
        <button onClick={reindex} disabled={indexing} className="btn-primary">
          {indexing ? "Indexing…" : "Re-index library"}
        </button>
        {indexMsg && (
          <span className="ml-3 text-sm" style={{ color: "var(--muted)" }}>
            {indexMsg}
          </span>
        )}
      </section>

      {usage && (
        <section className="card">
          <h3 className="mb-3 font-semibold">Token usage (30d)</h3>
          <div className="mb-3 text-2xl font-bold">{usage.total_tokens.toLocaleString()} tokens</div>
          <div className="grid grid-cols-2 gap-6 text-sm">
            <div>
              <div className="label">By kind</div>
              {Object.entries(usage.by_kind).map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span style={{ color: "var(--muted)" }}>{k}</span>
                  <span>{v.toLocaleString()}</span>
                </div>
              ))}
              {Object.keys(usage.by_kind).length === 0 && (
                <span style={{ color: "var(--faint)" }}>—</span>
              )}
            </div>
            <div>
              <div className="label">By model</div>
              {Object.entries(usage.by_model).map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span className="font-mono" style={{ color: "var(--muted)" }}>
                    {k}
                  </span>
                  <span>{v.toLocaleString()}</span>
                </div>
              ))}
              {Object.keys(usage.by_model).length === 0 && (
                <span style={{ color: "var(--faint)" }}>—</span>
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
