import { useApi } from '../workspaceContext';
import { SharedConnectionsPanel } from '../components/SharedConnectionsPanel';
import { useEffect, useState } from "react";
import {
  type ArchiveStatus,
  type CacheDiagnostics,
  type BackupInfo,
  type BackupRestoreGuide,
  type BackupVerification,
  type Provider,
  type Model,
  type Subscription,
  type RadarStatus,
} from "../api";
import { restoreGuideStatusLabel, restoreGuideTone, type ArchiveTone } from "./archiveModel";
import { ApplicationBackupPanel } from '../components/ApplicationBackupPanel';
import { shouldSubmitOnEnter } from "./keyGuardModel";
import { modelRoleStatus } from "./readinessModel";
import { useToast } from "../components/ui/Toast";
import { useConfirm } from "../components/ui/ConfirmDialog";
import { Loader2, RefreshCw } from "../icons";
import { Skeleton } from "../components/ui/Skeleton";
import { Shell } from "../components/layout/Shell";
import { PageHeader } from "../components/ui/PageHeader";

const TYPES = ["openai_chat", "openai_responses", "anthropic", "openai_compat"];
// 只要两类：一个 LLM（对话/总结/抽取共用），一个向量模型（embedding）。
// 这就是 PaperQA2「一个 llm + 一个 embedder」模型——简单、足够。
const ROLES = ["chat", "embedding"];
const ROLE_LABELS: Record<string, string> = {
  chat: "文本 AI（对话 / 总结 / 抽取）",
  embedding: "全文检索（向量模型）",
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
  openai_responses: "OpenAI Responses 格式（支持自定义地址）",
  openai_compat: "OpenAI 格式（自定义地址 · 任意厂商）",
  anthropic: "Anthropic / Claude 格式（可填自定义地址 · 任意厂商）",
};

const QUERY_TYPES = ["keyword", "category", "author"];
const QUERY_TYPE_LABELS: Record<string, string> = {
  keyword: "关键词",
  category: "分类",
  author: "作者",
};

function formatSubDate(value: string | null | undefined) {
  if (!value) return "从未运行";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

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
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  cache_reported_calls: number;
  cache_reported_input_tokens: number;
  call_count: number;
  cache_diagnostics?: CacheDiagnostics;
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
  const api = useApi();
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
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [radarStatus, setRadarStatus] = useState<RadarStatus | null>(null);
  const [radarBusy, setRadarBusy] = useState(false);
  // P10.3 研究方向描述：雷达初筛用它判断新论文相关度。
  const [interests, setInterests] = useState("");
  const [interestsSaving, setInterestsSaving] = useState(false);
  // P12 论断抽取开关（默认关，控成本）：开启后入库时自动提炼论断。
  const [claimExtraction, setClaimExtraction] = useState(false);
  const [claimExtractionSaving, setClaimExtractionSaving] = useState(false);
  const [subForm, setSubForm] = useState({
    name: "",
    query_type: "keyword",
    query_value: "",
    max_results: 20,
    lookback_days: 7,
  });
  const [editingSub, setEditingSub] = useState<number | null>(null);
  const [editSubForm, setEditSubForm] = useState({
    name: "",
    query_type: "keyword",
    query_value: "",
    max_results: 20,
    lookback_days: 7,
  });

  async function load() {
    try {
      const [nextProviders, nextUsage, nextArchiveStatus, nextBackups, nextSubscriptions, nextRadarStatus, nextSettings] = await Promise.all([
        api.listProviders(),
        api.usage(),
        api.archiveStatus(),
        api.listBackups(),
        api.listSubscriptions(),
        api.radarStatus(),
        api.listSettings(),
      ]);
      setProviders(nextProviders);
      const savedModels = await Promise.all(nextProviders.map(async provider =>
        [provider.id, await api.providerModels(provider.id)] as const));
      setModels(Object.fromEntries(savedModels));
      setUsage(nextUsage);
      setArchiveStatus(nextArchiveStatus);
      setBackups(nextBackups);
      setSubscriptions(nextSubscriptions);
      setRadarStatus(nextRadarStatus);
      setInterests(nextSettings.research_interests ?? "");
      setClaimExtraction((nextSettings.claim_extraction_enabled ?? "").trim().toLowerCase() === "true");
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

  async function addSubscription() {
    if (!subForm.name.trim() || !subForm.query_value.trim()) {
      toast.warn("请填写订阅名称和查询内容。");
      return;
    }
    try {
      await api.createSubscription(subForm);
      setSubForm({ name: "", query_type: "keyword", query_value: "", max_results: 20, lookback_days: 7 });
      toast.success("已添加订阅。");
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function toggleSubscription(s: Subscription) {
    try {
      await api.patchSubscription(s.id, { enabled: !s.enabled });
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  async function removeSubscription(s: Subscription) {
    const ok = await confirm({
      title: "删除订阅？",
      message: `将删除订阅「${s.name}」，此操作不可撤销。`,
      variant: "danger",
      confirmText: "删除",
    });
    if (!ok) return;
    try {
      await api.deleteSubscription(s.id);
      toast.success("已删除订阅。");
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  function startSubEdit(s: Subscription) {
    setEditingSub(s.id);
    setEditSubForm({
      name: s.name,
      query_type: s.query_type,
      query_value: s.query_value,
      max_results: s.max_results,
      lookback_days: s.lookback_days,
    });
  }

  async function saveSubEdit(id: number) {
    try {
      await api.patchSubscription(id, editSubForm);
      setEditingSub(null);
      toast.success("订阅已更新。");
      await load();
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  // P10.3 保存研究方向描述，雷达初筛据此给新论文打相关度。
  async function saveInterests() {
    setInterestsSaving(true);
    try {
      await api.putSetting("research_interests", interests.trim());
      toast.success("研究方向已保存，下次雷达刷新时生效。");
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setInterestsSaving(false);
    }
  }

  // P12 论断抽取开关：开启后入库时自动用对话模型提炼论断（默认关，控成本）。
  async function toggleClaimExtraction(enabled: boolean) {
    setClaimExtractionSaving(true);
    try {
      await api.putSetting("claim_extraction_enabled", enabled ? "true" : "false");
      setClaimExtraction(enabled);
      toast.success(enabled ? "论断抽取已开启，之后导入的论文会自动提炼论断。" : "论断抽取已关闭。");
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setClaimExtractionSaving(false);
    }
  }

  // P10.2 手动刷新：强制拉取所有启用的订阅，新条目进「建议中心」。
  async function refreshRadar() {
    setRadarBusy(true);
    try {
      const r = await api.radarRefresh();
      const failed = r.results.filter((x) => x.status === "error");
      if (failed.length > 0) {
        toast.warn(
          `检查了 ${r.ran} 个订阅，新增 ${r.created} 条；${failed.length} 个订阅失败（${failed.map((f) => f.name).join("、")}）。`
        );
      } else if (r.created > 0) {
        toast.success(`检查了 ${r.ran} 个订阅，新增 ${r.created} 条建议，请到「建议中心」查看。`);
      } else {
        toast.success(`检查了 ${r.ran} 个订阅，暂无新论文。`);
      }
      await load();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setRadarBusy(false);
    }
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

  async function downloadArchiveBackup(filename: string) {
    try {
      await api.downloadBackup(filename);
    } catch (e: any) {
      toast.error(e.message);
    }
  }

  return (
    <Shell max="narrow" className="space-y-6">
      <PageHeader title="设置" subtitle="连接 AI 服务，或管理本地资料备份" />
      <SharedConnectionsPanel providers={providers} onChanged={load}/>
      <p className="text-sm text-muted">首次使用 AI：填写服务商信息 → 添加提供商 → 获取或添加模型 → 选择文本 AI 角色。导入、阅读与笔记可以先使用，不必配齐所有功能。</p>

      <section className="card">
        <h3 className="mb-3 font-semibold">连接一个 AI 服务</h3>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <label className="text-sm">服务名称<input
            className="input"
            aria-label="服务名称" placeholder="给这个服务起个便于识别的名字"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          /></label>
          <label className="text-sm">接口类型<select aria-label="接口类型" className="input w-full" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {TYPE_LABELS[t] ?? t}
              </option>
            ))}
          </select><span className="text-xs text-muted">按服务商文档选择。</span></label>
          <label className="text-sm">接口地址<input
            className="input"
            aria-label="接口地址" placeholder="填写服务商提供的完整地址"
            value={form.base_url}
            onChange={(e) => setForm({ ...form, base_url: e.target.value })}
          /></label>
          <label className="text-sm">API key<input
            className="input"
            type="password"
            aria-label="API key" placeholder="粘贴服务商提供的密钥"
            value={form.api_key}
            onChange={(e) => setForm({ ...form, api_key: e.target.value })}
          /></label>
        </div>
        <button onClick={add} className="btn-primary mt-3">
          添加提供商
        </button>
      </section>

      <section className="card">
        <h3 className="mb-3 font-semibold">提供商与模型</h3>
        <p className="mb-3 text-xs text-faint">
          先把一个文本模型设为“文本 AI”，就能用于摘要与论文研究。需要全文检索问答时，再添加向量模型。
        </p>
        {!loading && (() => {
          const status = modelRoleStatus(Object.values(models).flat());
          return (
            <div
              className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg px-3 py-2 text-xs"
              style={{ backgroundColor: "var(--surface-2)" }}
              aria-live="polite"
            >
              <span>
                文本 AI：
              {status.llm ? (
                  <span style={{ color: "var(--success)" }}>已分配（{status.llm.model_id}）</span>
                ) : (
                  <span className="text-[var(--danger)]">未选择，请给一个模型选择“文本 AI”角色</span>
                )}
              </span>
              <span>
                全文检索：
              {status.embedding ? (
                  <span style={{ color: "var(--success)" }}>已分配（{status.embedding.model_id}）</span>
                ) : (
                  <span style={{ color: "var(--accent)" }}>可稍后配置向量模型</span>
                )}
              </span>
            </div>
          );
        })()}
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
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="font-medium break-all">{p.name}</span>
                <span className="chip">{p.type}</span>
                {p.shared_connection_id&&<span className="chip">{p.shared_unavailable?'共享配置不可用':'共享连接'}</span>}
                <span
                  className="text-xs"
                  style={{ color: p.enabled ? "var(--success)" : "var(--faint)" }}
                >
                  {p.enabled ? "已启用" : "已禁用"}
                </span>
                <div className="ml-auto flex flex-wrap items-center gap-1">
                  <button onClick={() => refresh(p.id)} className="btn-ghost py-1">
                    刷新模型
                  </button>
                  <button onClick={() => toggleProvider(p)} className="btn-ghost py-1">
                    {p.enabled ? "禁用" : "启用"}
                  </button>
                  <button onClick={() => startEdit(p)} className="btn-ghost py-1" disabled={!!p.shared_connection_id} title={p.shared_connection_id?'请在共享模型连接面板编辑，或转为项目专用连接':undefined}>
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
                    <span className="min-w-0 flex-1 break-all font-mono">{m.display_name ?? m.model_id}</span>
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
                  onKeyDown={(e) =>
                    shouldSubmitOnEnter(e.key, false, e.nativeEvent.isComposing) && addManualModel(p.id)
                  }
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
        <h3 className="mb-1 font-semibold">研究方向</h3>
        <p className="mb-2 text-sm text-muted">
          用一段话描述你的研究方向（中文即可），文献雷达会用它与 arXiv 新论文比对相关度：
          高/中相关的进入「建议中心」，无关的不打扰。
        </p>
        <textarea
          className="input min-h-20"
          placeholder="例如：我在研究检索增强生成（RAG）中的多轮对话记忆管理，关注 agent 记忆机制与知识库问答。"
          value={interests}
          onChange={(e) => setInterests(e.target.value)}
        />
        <div className="mt-2 flex justify-end">
          <button onClick={saveInterests} disabled={interestsSaving} className="btn-primary py-1 text-sm">
            {interestsSaving ? "保存中…" : "保存研究方向"}
          </button>
        </div>
      </section>

      <section className="card">
        <div className="mb-1 flex items-start justify-between gap-3">
          <h3 className="font-semibold">论断抽取</h3>
          <label className="flex shrink-0 items-center gap-2 text-sm text-muted">
            <input
              type="checkbox"
              checked={claimExtraction}
              disabled={claimExtractionSaving}
              onChange={(e) => toggleClaimExtraction(e.target.checked)}
            />
            {claimExtraction ? "已开启" : "已关闭"}
          </label>
        </div>
        <p className="text-sm text-muted">
          开启后，导入论文时会用对话模型自动提炼 1–3 条主要论断，并在论断之间检测支持/矛盾/延伸关系
          （「图谱」页的论断图与「建议中心」的论断矛盾提醒依赖它）。默认关闭以节省 token；
          已入库论文可用详情页「重新分析」补抽。
        </p>
      </section>

      <section className="card">
        <div className="mb-1 flex items-start justify-between gap-3">
          <h3 className="font-semibold">文献雷达</h3>
          <button onClick={refreshRadar} disabled={radarBusy} className="btn-primary py-1 text-sm shrink-0">
            {radarBusy ? (<><Loader2 size={14} className="animate-spin" /> 刷新中…</>) : (<><RefreshCw size={14} /> 立即刷新</>)}
          </button>
        </div>
        <p className="mb-2 text-sm text-muted">
          保存 arXiv 跟踪查询，应用启动时自动检查最近新提交的论文，高相关的会进入「建议中心」。
          关键词示例：<code>retrieval augmented generation</code>；分类示例：<code>cs.IR</code>；作者示例：<code>J. Smith</code>。
        </p>
        {radarStatus && (
          <p className="mb-3 text-xs text-faint">
            共 {radarStatus.total} 个订阅（启用 {radarStatus.enabled} 个）
            {radarStatus.due > 0 ? ` · ${radarStatus.due} 个待检查` : ""}
            {" · "}上次运行：{formatSubDate(radarStatus.last_run_at)}
          </p>
        )}

        <div className="mb-3 grid grid-cols-1 gap-2 md:grid-cols-6">
          <input
            className="input md:col-span-1"
            placeholder="名称"
            value={subForm.name}
            onChange={(e) => setSubForm({ ...subForm, name: e.target.value })}
          />
          <select
            className="input md:col-span-1"
            value={subForm.query_type}
            onChange={(e) => setSubForm({ ...subForm, query_type: e.target.value })}
          >
            {QUERY_TYPES.map((t) => (
              <option key={t} value={t}>
                {QUERY_TYPE_LABELS[t] ?? t}
              </option>
            ))}
          </select>
          <input
            className="input md:col-span-2"
            placeholder="查询内容"
            value={subForm.query_value}
            onChange={(e) => setSubForm({ ...subForm, query_value: e.target.value })}
          />
          <input
            className="input md:col-span-1"
            type="number"
            min={1}
            max={100}
            title="每次拉取条数上限"
            value={subForm.max_results}
            onChange={(e) => setSubForm({ ...subForm, max_results: Number(e.target.value) })}
          />
          <input
            className="input md:col-span-1"
            type="number"
            min={1}
            max={365}
            title="回看天数"
            value={subForm.lookback_days}
            onChange={(e) => setSubForm({ ...subForm, lookback_days: Number(e.target.value) })}
          />
        </div>
        <button onClick={addSubscription} className="btn-primary mb-3">
          添加订阅
        </button>

        <div className="space-y-2">
          {subscriptions.length === 0 && <p className="text-sm text-faint">还没有订阅。</p>}
          {subscriptions.map((s) => (
            <div key={s.id} className="rounded-lg border p-3 border-[var(--border)]">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{s.name}</span>
                <span className="chip">{QUERY_TYPE_LABELS[s.query_type] ?? s.query_type}</span>
                <span className="font-mono text-xs text-muted">{s.query_value}</span>
                <span
                  className="text-xs"
                  style={{ color: s.enabled ? "var(--success)" : "var(--faint)" }}
                >
                  {s.enabled ? "已启用" : "已停用"}
                </span>
                <div className="ml-auto flex items-center gap-1">
                  <button onClick={() => toggleSubscription(s)} className="btn-ghost py-1">
                    {s.enabled ? "停用" : "启用"}
                  </button>
                  <button onClick={() => startSubEdit(s)} className="btn-ghost py-1">
                    编辑
                  </button>
                  <button onClick={() => removeSubscription(s)} className="btn-ghost py-1 text-[var(--danger)]">
                    删除
                  </button>
                </div>
              </div>
              <div className="mt-1 text-xs text-faint">
                每次最多 {s.max_results} 条 · 回看 {s.lookback_days} 天 · 上次运行：{formatSubDate(s.last_run_at)}
              </div>
              {editingSub === s.id && (
                <div className="mt-2 grid grid-cols-1 gap-2 rounded-lg p-2 md:grid-cols-2" style={{ backgroundColor: "var(--surface-2)" }}>
                  <input
                    className="input py-1 text-sm"
                    placeholder="名称"
                    value={editSubForm.name}
                    onChange={(e) => setEditSubForm({ ...editSubForm, name: e.target.value })}
                  />
                  <select
                    className="input py-1 text-sm"
                    value={editSubForm.query_type}
                    onChange={(e) => setEditSubForm({ ...editSubForm, query_type: e.target.value })}
                  >
                    {QUERY_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {QUERY_TYPE_LABELS[t] ?? t}
                      </option>
                    ))}
                  </select>
                  <input
                    className="input py-1 text-sm md:col-span-2"
                    placeholder="查询内容"
                    value={editSubForm.query_value}
                    onChange={(e) => setEditSubForm({ ...editSubForm, query_value: e.target.value })}
                  />
                  <label className="flex items-center gap-2 text-xs text-muted">
                    每次条数上限
                    <input
                      className="input flex-1 py-1 text-sm"
                      type="number"
                      min={1}
                      max={100}
                      value={editSubForm.max_results}
                      onChange={(e) => setEditSubForm({ ...editSubForm, max_results: Number(e.target.value) })}
                    />
                  </label>
                  <label className="flex items-center gap-2 text-xs text-muted">
                    回看天数
                    <input
                      className="input flex-1 py-1 text-sm"
                      type="number"
                      min={1}
                      max={365}
                      value={editSubForm.lookback_days}
                      onChange={(e) => setEditSubForm({ ...editSubForm, lookback_days: Number(e.target.value) })}
                    />
                  </label>
                  <div className="md:col-span-2 flex gap-2">
                    <button onClick={() => saveSubEdit(s.id)} className="btn-primary py-1 text-sm">
                      保存
                    </button>
                    <button onClick={() => setEditingSub(null)} className="btn-ghost py-1 text-sm">
                      取消
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      <ApplicationBackupPanel />
      <section className="card">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold">当前项目备份与导出</h3>
            <p className="mt-1 text-sm text-muted">
              保存当前项目的资料；整体迁移可使用上方的全部项目备份。
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
            完整迁移请使用备份压缩包及恢复向导；其中包含原文、数据库和本地主密钥，请妥善保管，不要外传。JSON 用于查阅和交换结构化记录，不包含原文文件、密钥或向量，不能直接恢复整个工作空间。BibTeX/RIS 用于写作引用工具。
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
                    <button
                      onClick={() => downloadArchiveBackup(backup.filename)}
                      className="btn-ghost py-1 text-xs"
                    >
                      下载
                    </button>
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
          <div className="cache-summary mb-4" aria-label="输入缓存用量">
            <span>输入 <b>{(usage.input_tokens??0).toLocaleString()}</b></span>
            <span>缓存读取 <b>{(usage.cached_input_tokens??0).toLocaleString()}</b></span>
            <span>缓存写入 <b>{(usage.cache_write_tokens??0).toLocaleString()}</b></span>
            {usage.cache_diagnostics && <>
              <span>大模型输入命中率 <b>{usage.cache_diagnostics.input_token_hit_rate == null ? '暂无可靠数据' : `${(100 * usage.cache_diagnostics.input_token_hit_rate).toFixed(1)}%`}</b></span>
              <span>90% 目标 <b>{usage.cache_diagnostics.target_met == null ? '数据不足，暂不能判断' : usage.cache_diagnostics.target_met ? '已达到' : '尚未达到'}</b></span>
              <small>{usage.cache_diagnostics.reported_calls} / {usage.cache_diagnostics.calls} 次大模型调用返回了缓存信息，包含首次冷启动；向量检索等 {usage.cache_diagnostics.excluded_non_llm_calls ?? 0} 次调用单独计入总用量。缺失报告不当作命中或未命中。缓存读写仍可能收费，本地结果复用不计入此命中率。</small>
              {usage.cache_diagnostics.invalid_usage_calls > 0 && <small role="alert">{usage.cache_diagnostics.invalid_usage_calls} 次调用返回的缓存用量不一致，暂不据此判断是否达标。</small>}
            </>}
          </div>
          {usage.cache_diagnostics && usage.cache_diagnostics.by_provider_model_kind.length > 0 && <details className="mb-4">
            <summary className="cursor-pointer text-sm">按模型查看缓存命中</summary>
            <div className="overflow-auto mt-3"><table className="w-full text-left text-sm"><thead><tr><th className="p-2">模型 / 用途</th><th className="p-2">输入命中率</th><th className="p-2">有报告的调用</th><th className="p-2">90% 目标</th></tr></thead><tbody>
              {usage.cache_diagnostics.by_provider_model_kind.map(row => <tr key={`${row.provider_id}-${row.model}-${row.request_kind}`} className="border-t border-[var(--border)]">
                <td className="p-2 break-words">{row.model}<span className="block text-xs text-muted">{providers.find(provider => provider.id === row.provider_id)?.name ?? '已移除的提供商'} · {({ chat:'问答', research:'论文研究', summary:'摘要', summarize:'摘要', concepts:'概念抽取', report:'组会报告', reports:'组会报告' } as Record<string,string>)[row.request_kind] ?? row.request_kind}</span></td>
                <td className="p-2">{row.input_token_hit_rate == null ? '未知' : `${(row.input_token_hit_rate * 100).toFixed(1)}%`}</td>
                <td className="p-2">{row.reported_calls} / {row.calls}</td>
                <td className="p-2">{row.target_met == null ? '暂不能判断' : row.target_met ? '已达到' : '尚未达到'}</td>
              </tr>)}
            </tbody></table></div>
          </details>}

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
