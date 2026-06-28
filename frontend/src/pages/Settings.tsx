import { useEffect, useState } from "react";
import { api, type Provider, type Model } from "../api";

const TYPES = ["openai_chat", "openai_responses", "anthropic", "openai_compat"];
const ROLES = ["summary", "extraction", "chat", "deep", "embedding"];

// 业界主流就是两种 API 格式：OpenAI 格式 与 Anthropic(Claude) 格式。很多厂商按其中
// 一种对外提供服务。这里把后端标识映射成「格式 + 是否支持自定义地址」的人话标签，
// 让用户知道：想接入任意厂商，选「…自定义地址」那两项并填 base_url 即可。
const TYPE_LABELS: Record<string, string> = {
  openai_chat: "OpenAI 格式（官方地址）",
  openai_responses: "OpenAI Responses 格式（官方地址）",
  openai_compat: "OpenAI 格式（自定义地址 · 任意厂商）",
  anthropic: "Anthropic / Claude 格式（可填自定义地址 · 任意厂商）",
};

/** Compact responsive SVG bar chart of daily token usage (no chart dependency). */
function UsageBars({ data }: { data: { day: string; tokens: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.tokens));
  const W = 100;
  const H = 36;
  const gap = data.length > 1 ? 0.4 : 0;
  const bw = (W - gap * (data.length - 1)) / data.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-20 w-full" preserveAspectRatio="none" role="img" aria-label="每日 token 用量">
      {data.map((d, i) => {
        const bh = (d.tokens / max) * H;
        const x = i * (bw + gap);
        return (
          <rect
            key={d.day}
            x={x}
            y={H - bh}
            width={Math.max(bw - 0.2, 0.1)}
            height={Math.max(bh, 0.1)}
            rx={0.4}
            fill="var(--accent)"
            opacity={0.4 + 0.6 * (d.tokens / max)}
          >
            <title>
              {d.day}: {d.tokens.toLocaleString()} tokens
            </title>
          </rect>
        );
      })}
    </svg>
  );
}

interface Usage {
  total_tokens: number;
  by_kind: Record<string, number>;
  by_model: Record<string, number>;
  by_day: { day: string; tokens: number }[];
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
  const [newModel, setNewModel] = useState<Record<number, { model_id: string; role: string }>>({});
  const [editing, setEditing] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({ name: "", base_url: "", api_key: "" });

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
      setMsg(`已添加提供商「${p.name}」。`);
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
      setMsg(`已获取 ${r.count} 个模型。`);
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function toggleProvider(p: Provider) {
    setErr(null);
    try {
      await api.patchProvider(p.id, { enabled: !p.enabled });
      await load();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function removeProvider(id: number) {
    setErr(null);
    try {
      await api.deleteProvider(id);
      await load();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  function startEdit(p: Provider) {
    setEditing(p.id);
    setEditForm({ name: p.name, base_url: p.base_url ?? "", api_key: "" });
  }

  async function saveEdit(id: number) {
    setErr(null);
    const body: Record<string, unknown> = {};
    if (editForm.name) body.name = editForm.name;
    if (editForm.base_url) body.base_url = editForm.base_url;
    if (editForm.api_key) body.api_key = editForm.api_key; // rotate the key
    try {
      await api.patchProvider(id, body);
      setEditing(null);
      setMsg("提供商已更新。");
      await load();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function addManualModel(pid: number) {
    const f = newModel[pid];
    if (!f?.model_id?.trim()) return;
    setErr(null);
    try {
      await api.addModel(pid, { model_id: f.model_id.trim(), role_default: f.role || undefined });
      setNewModel({ ...newModel, [pid]: { model_id: "", role: "" } });
      setModels({ ...models, [pid]: await api.providerModels(pid) });
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
        r.chunks > 0 ? `已索引 ${r.chunks} 个片段。` : "未配置 embedding 模型。",
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
        <h3 className="mb-3 font-semibold">添加 LLM 提供商</h3>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <input
            className="input"
            placeholder="名称"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <select className="input" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {TYPE_LABELS[t] ?? t}
              </option>
            ))}
          </select>
          <input
            className="input"
            placeholder="base_url（openai_compat 必填；anthropic 可填 Claude 中转地址）"
            value={form.base_url}
            onChange={(e) => setForm({ ...form, base_url: e.target.value })}
          />
          <input
            className="input"
            type="password"
            placeholder="api_key（落盘加密）"
            value={form.api_key}
            onChange={(e) => setForm({ ...form, api_key: e.target.value })}
          />
        </div>
        <button onClick={add} className="btn-primary mt-3">
          添加提供商
        </button>
      </section>

      <section className="card">
        <h3 className="mb-3 font-semibold">提供商与模型</h3>
        {providers.length === 0 && (
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            还没有提供商。
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
                  {p.enabled ? "已启用" : "已禁用"}
                </span>
                <div className="ml-auto flex items-center gap-1">
                  <button onClick={() => refresh(p.id)} className="btn-ghost py-1">
                    刷新模型
                  </button>
                  <button onClick={() => toggleProvider(p)} className="btn-ghost py-1">
                    {p.enabled ? "禁用" : "启用"}
                  </button>
                  <button onClick={() => startEdit(p)} className="btn-ghost py-1">
                    编辑
                  </button>
                  <button
                    onClick={() => removeProvider(p.id)}
                    className="btn-ghost py-1"
                    style={{ color: "var(--danger)" }}
                  >
                    删除
                  </button>
                </div>
              </div>
              {editing === p.id && (
                <div className="mb-2 grid grid-cols-1 gap-2 rounded-lg p-2 md:grid-cols-2" style={{ backgroundColor: "var(--surface-2)" }}>
                  <input
                    className="input py-1 text-sm"
                    placeholder="名称"
                    value={editForm.name}
                    onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                  />
                  <input
                    className="input py-1 text-sm"
                    placeholder="base_url"
                    value={editForm.base_url}
                    onChange={(e) => setEditForm({ ...editForm, base_url: e.target.value })}
                  />
                  <input
                    className="input py-1 text-sm md:col-span-2"
                    type="password"
                    placeholder="轮换 api key（留空则不修改）"
                    value={editForm.api_key}
                    onChange={(e) => setEditForm({ ...editForm, api_key: e.target.value })}
                  />
                  <div className="md:col-span-2 flex gap-2">
                    <button onClick={() => saveEdit(p.id)} className="btn-primary py-1 text-sm">
                      保存
                    </button>
                    <button onClick={() => setEditing(null)} className="btn-ghost py-1 text-sm">
                      取消
                    </button>
                  </div>
                </div>
              )}
              <div className="space-y-1">
                {(models[p.id] ?? []).map((m) => (
                  <div key={m.id} className="flex items-center gap-2 text-sm">
                    <span className="flex-1 font-mono">{m.display_name ?? m.model_id}</span>
                    <select
                      className="input w-32 py-1 text-xs"
                      value={m.role_default ?? ""}
                      onChange={(e) => setRole(p.id, m.id, e.target.value)}
                    >
                      <option value="">— 角色 —</option>
                      {ROLES.map((r) => (
                        <option key={r}>{r}</option>
                      ))}
                    </select>
                  </div>
                ))}
                {p.id in models && models[p.id].length === 0 && (
                  <p className="text-xs" style={{ color: "var(--faint)" }}>
                    暂无模型。点击「刷新模型」，或在下方手动添加。
                  </p>
                )}
              </div>
              <div className="mt-2 flex items-center gap-2">
                <input
                  className="input flex-1 py-1 text-xs"
                  placeholder="按 id 添加模型（如 gpt-4o、llama3:8b）"
                  value={newModel[p.id]?.model_id ?? ""}
                  onChange={(e) =>
                    setNewModel({
                      ...newModel,
                      [p.id]: { model_id: e.target.value, role: newModel[p.id]?.role ?? "" },
                    })
                  }
                  onKeyDown={(e) => e.key === "Enter" && addManualModel(p.id)}
                />
                <select
                  className="input w-28 py-1 text-xs"
                  value={newModel[p.id]?.role ?? ""}
                  onChange={(e) =>
                    setNewModel({
                      ...newModel,
                      [p.id]: { model_id: newModel[p.id]?.model_id ?? "", role: e.target.value },
                    })
                  }
                >
                  <option value="">— 角色 —</option>
                  {ROLES.map((r) => (
                    <option key={r}>{r}</option>
                  ))}
                </select>
                <button onClick={() => addManualModel(p.id)} className="btn-ghost py-1 text-xs">
                  添加
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <h3 className="mb-1 font-semibold">检索（RAG）</h3>
        <p className="mb-3 text-sm" style={{ color: "var(--muted)" }}>
          在上方为某个模型分配 <span className="chip">embedding</span> 角色，让对话能基于论文全文作答。
          任何 OpenAI 兼容的 embeddings 端点都行——例如通过{" "}
          <code>openai_compat</code> 提供商接入硅基流动的免费 <code>bge</code> 模型。配置后为论文库建立索引。
        </p>
        <button onClick={reindex} disabled={indexing} className="btn-primary">
          {indexing ? "索引中…" : "重建索引"}
        </button>
        {indexMsg && (
          <span className="ml-3 text-sm" style={{ color: "var(--muted)" }}>
            {indexMsg}
          </span>
        )}
      </section>

      {usage && (
        <section className="card">
          <h3 className="mb-3 font-semibold">Token 用量（近 30 天）</h3>
          <div className="mb-3 text-2xl font-bold">{usage.total_tokens.toLocaleString()} tokens</div>
          {usage.by_day.length > 0 && (
            <div className="mb-4">
              <div className="label">每日用量</div>
              <UsageBars data={usage.by_day} />
            </div>
          )}
          <div className="grid grid-cols-2 gap-6 text-sm">
            <div>
              <div className="label">按类型</div>
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
              <div className="label">按模型</div>
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
