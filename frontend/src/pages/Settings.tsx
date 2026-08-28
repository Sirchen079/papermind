import { useEffect, useState } from "react";
import {
  api,
  type ArchiveStatus,
  type BackupInfo,
  type BackupRestoreGuide,
  type BackupVerification,
  type Provider,
  type Model,
} from "../api";
import { restoreGuideStatusLabel, restoreGuideTone, type ArchiveTone } from "./archiveModel";
import { useToast } from "../components/ui/Toast";
import { useConfirm } from "../components/ui/ConfirmDialog";
import { Skeleton } from "../components/ui/Skeleton";
import { Shell } from "../components/layout/Shell";
import { PageHeader } from "../components/ui/PageHeader";

const TYPES = ["openai_chat", "openai_responses", "anthropic", "openai_compat"];
// 只要两类：一个 LLM（对话/总结/抽取共用），一个向量模型（embedding）。
// 这就是 PaperQA2「一个 llm + 一个 embedder」模型——简单、足够。
const ROLES = ["chat", "embedding"];
const ROLE_LABELS: Record<string, string> = {
  chat: "LLM（对话 / 总结 / 抽取）",
  embedding: "向量（embedding）",
};

const ARCHIVE_TONE_COLOR: Record<ArchiveTone, string> = {
  success: "var(--success)",
  danger: "var(--danger)",
};

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

function formatBytes(value: number | null | undefined) {
  if (!value) return "0 B";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = value / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unit]}`;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export default function Settings() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [models, setModels] = useState<Record<number, Model[]>>({});
  const [usage, setUsage] = useState<Usage | null>(null);
  const [archiveStatus, setArchiveStatus] = useState<ArchiveStatus | null>(null);
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [archiveBusy, setArchiveBusy] = useState(false);
  const [verifyingBackup, setVerifyingBackup] = useState<string | null>(null);
  const [loadingRestoreGuide, setLoadingRestoreGuide] = useState<string | null>(null);
  const [backupVerifications, setBackupVerifications] = useState<Record<string, BackupVerification>>({});
  const [restoreGuides, setRestoreGuides] = useState<Record<string, BackupRestoreGuide>>({});
  const [form, setForm] = useState({ name: "", type: "openai_chat", base_url: "", api_key: "" });
  const [indexing, setIndexing] = useState(false);
  const [loading, setLoading] = useState(true);
  const toast = useToast();
  const confirm = useConfirm();
  const [newModel, setNewModel] = useState<Record<number, { model_id: string; role: string }>>({});
  const [editing, setEditing] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({ name: "", base_url: "", api_key: "" });

  async function load() {
    try {
      const [nextProviders, nextUsage, nextArchiveStatus, nextBackups] = await Promise.all([
        api.listProviders(),
        api.usage(),
        api.archiveStatus(),
        api.listBackups(),
      ]);
      setProviders(nextProviders);
      setUsage(nextUsage);
      setArchiveStatus(nextArchiveStatus);
      setBackups(nextBackups);
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
      const body: Record<string, unknown> = { name: form.name, type: form.type };
      if (form.base_url) body.base_url = form.base_url;
      if (form.api_key) body.api_key = form.api_key;
      const p = await api.createProvider(body);
      toast.success(`已添加提供商「${p.name}」。`);
      setForm({ name: "", type: "openai_chat", base_url: "", api_key: "" });
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function refresh(id: number) {
    try {
      const r = await api.refreshModels(id);
      setModels({ ...models, [id]: await api.providerModels(id) });
      toast.success(`已获取 ${r.count} 个模型。`);
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function toggleProvider(p: Provider) {
    try {
      await api.patchProvider(p.id, { enabled: !p.enabled });
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function removeProvider(p: Provider) {
    const ok = await confirm({
      title: "删除提供商？",
      message: `将删除「${p.name}」及其模型配置，此操作不可撤销。`,
      variant: "danger",
      confirmText: "删除",
    });
    if (!ok) return;
    try {
      await api.deleteProvider(p.id);
      toast.success("已删除提供商。");
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  function startEdit(p: Provider) {
    setEditing(p.id);
    setEditForm({ name: p.name, base_url: p.base_url ?? "", api_key: "" });
  }

  async function saveEdit(id: number) {
    const body: Record<string, unknown> = {};
    if (editForm.name) body.name = editForm.name;
    if (editForm.base_url) body.base_url = editForm.base_url;
    if (editForm.api_key) body.api_key = editForm.api_key; // rotate the key
    try {
      await api.patchProvider(id, body);
      setEditing(null);
      toast.success("提供商已更新。");
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function addManualModel(pid: number) {
    const f = newModel[pid];
    if (!f?.model_id?.trim()) return;
    try {
      await api.addModel(pid, { model_id: f.model_id.trim(), role_default: f.role || undefined });
      setNewModel({ ...newModel, [pid]: { model_id: "", role: "" } });
      setModels({ ...models, [pid]: await api.providerModels(pid) });
      toast.success("已添加模型。");
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function setRole(id: number, mid: number, role: string) {
    await api.setModelRole(mid, role);
    setModels({ ...models, [id]: await api.providerModels(id) });
  }

  async function reindex() {
    setIndexing(true);
    try {
      const r = await api.reindexLibrary();
      if (!r.configured) {
        toast.error("未配置 embedding 模型——请在某个 OpenAI 格式的提供商上，把一个 embedding 模型（如 BAAI/bge-m3）的角色设为 embedding。");
      } else if (r.error) {
        toast.error(`索引失败：${r.error}（请检查 embedding 模型名称、地址与密钥）`);
      } else if (r.papers === 0) {
        toast.info("向量模型已就绪，但论文库为空——添加论文后再重建索引。");
      } else if (r.chunks === 0) {
        toast.warn(`已处理 ${r.papers} 篇论文，但都没有可提取的摘要/全文。`);
      } else {
        toast.success(`已索引 ${r.chunks} 个片段（来自 ${r.indexed_papers}/${r.papers} 篇论文）。`);
      }
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setIndexing(false);
    }
  }

  async function createArchiveBackup() {
    setArchiveBusy(true);
    try {
      const backup = await api.createBackup();
      const [nextArchiveStatus, nextBackups] = await Promise.all([
        api.archiveStatus(),
        api.listBackups(),
      ]);
      setArchiveStatus(nextArchiveStatus);
      setBackups(nextBackups);
      toast.success(`已创建备份 ${backup.filename}`);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setArchiveBusy(false);
    }
  }

  async function verifyArchiveBackup(filename: string) {
    setVerifyingBackup(filename);
    try {
      const result = await api.verifyBackup(filename);
      setBackupVerifications((prev) => ({ ...prev, [filename]: result }));
      if (result.ok) toast.success(`备份 ${filename} 校验通过。`);
      else toast.warn(`备份 ${filename} 校验发现问题。`);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setVerifyingBackup(null);
    }
  }

  async function loadRestoreGuide(filename: string) {
    setLoadingRestoreGuide(filename);
    try {
      const guide = await api.restoreGuide(filename);
      setRestoreGuides((prev) => ({ ...prev, [filename]: guide }));
      setBackupVerifications((prev) => ({ ...prev, [filename]: guide.verification }));
      if (guide.can_restore) toast.success(`备份 ${filename} 可以按指南恢复。`);
      else toast.warn(`备份 ${filename} 不建议恢复。`);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoadingRestoreGuide(null);
    }
  }

  return (
    <Shell max="narrow" className="space-y-6">
      <PageHeader title="设置" subtitle="模型提供商、检索索引与数据备份" />

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
        <p className="mb-3 text-xs text-faint">
          只需各设一个：给某个模型标 <b>LLM</b>（对话 / 总结 / 抽取共用），再给一个向量模型标
          <b> embedding</b>。除向量外，所有文本任务都复用同一个 LLM。
        </p>
        {loading ? (
          <div className="space-y-2">
            <Skeleton variant="row" />
            <Skeleton variant="row" />
          </div>
        ) : providers.length === 0 ? (
          <p className="text-sm text-muted">
            还没有提供商。
          </p>
        ) : null}
        <div className="space-y-3">
          {providers.map((p) => (
            <div key={p.id} className="rounded-lg border p-3 border-[var(--border)]">
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
                    onClick={() => removeProvider(p)}
                    className="btn-ghost py-1 text-[var(--danger)]"
                    
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
                        <option key={r} value={r}>{ROLE_LABELS[r] ?? r}</option>
                      ))}
                    </select>
                  </div>
                ))}
                {p.id in models && models[p.id].length === 0 && (
                  <p className="text-xs text-faint">
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
                    <option key={r} value={r}>{ROLE_LABELS[r] ?? r}</option>
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
        <p className="mb-3 text-sm text-muted">
          在上方为某个模型分配 <span className="chip">embedding</span> 角色，让对话能基于论文全文作答。
          任何 OpenAI 兼容的 embeddings 端点都行——例如通过{" "}
          <code>openai_compat</code> 提供商接入硅基流动的免费 <code>bge</code> 模型。配置后为论文库建立索引。
        </p>
        <button onClick={reindex} disabled={indexing} className="btn-primary">
          {indexing ? "索引中…" : "重建索引"}
        </button>
      </section>

      <section className="card">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold">数据安全</h3>
            <p className="mt-1 text-sm text-muted">
              本地备份与可移植导出，保障论文库可长期保存。
            </p>
          </div>
          <button onClick={createArchiveBackup} disabled={archiveBusy} className="btn-primary">
            {archiveBusy ? "创建中…" : "创建备份"}
          </button>
        </div>

        <div className="mb-3 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <div>
            <div className="label">论文</div>
            <div className="font-semibold">{archiveStatus?.paper_count ?? "-"}</div>
          </div>
          <div>
            <div className="label">片段</div>
            <div className="font-semibold">{archiveStatus?.chunk_count ?? "-"}</div>
          </div>
          <div>
            <div className="label">PDF</div>
            <div className="font-semibold">
              {archiveStatus ? `${archiveStatus.pdf_count} / ${formatBytes(archiveStatus.pdf_total_bytes)}` : "-"}
            </div>
          </div>
          <div>
            <div className="label">数据库</div>
            <div className="font-semibold">
              {archiveStatus?.database_exists ? formatBytes(archiveStatus.database_size_bytes) : "缺失"}
            </div>
          </div>
        </div>

        <div className="mb-3 rounded-lg border p-3 text-sm border-[var(--border)]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="chip">{archiveStatus?.master_key_exists ? "已包含 master.key" : "缺少 master.key"}</span>
            <span className="chip">
              最近备份：{archiveStatus?.latest_backup ? formatDate(archiveStatus.latest_backup.modified_at) : "无"}
            </span>
          </div>
          <p className="mt-2 text-muted">
            备份压缩包包含本地主密钥，必须妥善保管，不要外传。JSON 适合完整迁移，BibTeX/RIS 适合进入写作引用工具。
          </p>
        </div>

        <div className="mb-3 flex flex-wrap gap-2">
          <a className="btn-ghost" href={api.exportJsonUrl()} download>
            导出 JSON
          </a>
          <a className="btn-ghost" href={api.exportBibtexUrl()} download>
            导出 BibTeX
          </a>
          <a className="btn-ghost" href={api.exportRisUrl()} download>
            导出 RIS
          </a>
        </div>

        <div className="space-y-2">
          {backups.length === 0 && (
            <p className="text-sm text-faint">
              还没有备份。
            </p>
          )}
          {backups.map((backup) => (
            <div key={backup.filename} className="rounded-lg border px-3 py-2 text-sm border-[var(--border)]">
              <div className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 flex-1 break-all font-mono text-muted">{backup.filename}</span>
                <span >{formatBytes(backup.size_bytes)}</span>
                <span className="text-muted">{formatDate(backup.modified_at)}</span>
                {backup.error ? (
                  <span className="text-[var(--danger)]">已损坏</span>
                ) : (
                  <>
                    <button
                      onClick={() => verifyArchiveBackup(backup.filename)}
                      disabled={verifyingBackup === backup.filename}
                      className="btn-ghost py-1 text-xs"
                    >
                      {verifyingBackup === backup.filename ? "校验中…" : "校验"}
                    </button>
                    <button
                      onClick={() => loadRestoreGuide(backup.filename)}
                      disabled={loadingRestoreGuide === backup.filename}
                      className="btn-ghost py-1 text-xs"
                    >
                      {loadingRestoreGuide === backup.filename ? "生成中…" : "恢复指南"}
                    </button>
                    <a className="btn-ghost py-1 text-xs" href={api.downloadBackupUrl(backup.filename)} download>
                      下载
                    </a>
                  </>
                )}
              </div>
              {backupVerifications[backup.filename] && (
                <div
                  className="mt-2 rounded-lg px-2 py-1.5 text-xs"
                  style={{
                    backgroundColor: backupVerifications[backup.filename].ok
                      ? "color-mix(in srgb, var(--success) 10%, transparent)"
                      : "color-mix(in srgb, var(--danger) 10%, transparent)",
                    color: backupVerifications[backup.filename].ok ? "var(--success)" : "var(--danger)",
                  }}
                >
                  {backupVerifications[backup.filename].ok
                    ? `校验通过：数据库完整，PDF ${backupVerifications[backup.filename].pdfs.verified_count}/${backupVerifications[backup.filename].pdfs.expected_count} 个已验证。`
                    : `校验失败：${backupVerifications[backup.filename].errors.slice(0, 2).join("；")}`}
                </div>
              )}
              {restoreGuides[backup.filename] && (
                <div className="mt-2 rounded-lg border p-3 text-xs" style={{ borderColor: "var(--border)", backgroundColor: "var(--surface-2)" }}>
                  {(() => {
                    const guide = restoreGuides[backup.filename];
                    const tone = restoreGuideTone(guide.can_restore);
                    return (
                      <div className="space-y-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            className="rounded-full px-2 py-0.5 font-medium text-muted"
                            style={{
                              color: ARCHIVE_TONE_COLOR[tone],
                              backgroundColor: `color-mix(in srgb, ${ARCHIVE_TONE_COLOR[tone]} 12%, transparent)`,
                            }}
                          >
                            {restoreGuideStatusLabel(guide.can_restore)}
                          </span>
                          <span >{guide.summary}</span>
                        </div>
                        <div className="grid gap-1 font-mono text-muted">
                          <div>数据目录：{guide.paths.data_dir}</div>
                          <div>数据库：{guide.paths.database_path}</div>
                          <div>PDF 目录：{guide.paths.pdf_dir}</div>
                        </div>
                        <div>
                          <div className="mb-1 font-medium">恢复前风险提示</div>
                          <ul className="list-disc space-y-1 pl-5 text-muted">
                            {guide.warnings.map((warning) => (
                              <li key={warning}>{warning}</li>
                            ))}
                          </ul>
                        </div>
                        <div>
                          <div className="mb-1 font-medium">离线恢复步骤</div>
                          <ol className="list-decimal space-y-1 pl-5 text-muted">
                            {guide.steps.map((step) => (
                              <li key={step.title}>
                                <span className="font-medium text-[var(--text)]">{step.title}：</span>
                                {step.detail}
                              </li>
                            ))}
                          </ol>
                        </div>
                      </div>
                    );
                  })()}
                </div>
              )}
            </div>
          ))}
        </div>
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
                <div key={k} className="flex justify-between text-muted">
                  <span >{k}</span>
                  <span>{v.toLocaleString()}</span>
                </div>
              ))}
              {Object.keys(usage.by_kind).length === 0 && (
                <span className="text-faint">—</span>
              )}
            </div>
            <div>
              <div className="label">按模型</div>
              {Object.entries(usage.by_model).map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span className="font-mono text-muted">
                    {k}
                  </span>
                  <span>{v.toLocaleString()}</span>
                </div>
              ))}
              {Object.keys(usage.by_model).length === 0 && (
                <span className="text-faint">—</span>
              )}
            </div>
          </div>
        </section>
      )}
    </Shell>
  );
}
