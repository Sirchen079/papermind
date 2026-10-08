import { useEffect, useRef, useState } from 'react';
import type { ChatModel } from '../api';
import { useApi } from '../workspaceContext';

const KEY = 'review_writing_model_config_id';

export function ReviewModelSettings({ refreshKey }: { refreshKey?: unknown }) {
  const api = useApi();
  const [models, setModels] = useState<ChatModel[]>([]);
  const [value, setValue] = useState('');
  const [loading, setLoading] = useState(true);
  const [ready, setReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const generation = useRef(0);
  useEffect(() => {
    const version = ++generation.current;
    setLoading(true); setReady(false); setSaving(false); setError('');
    Promise.all([api.chatModels(), api.listSettings()]).then(([choices, settings]) => {
      if (version !== generation.current) return;
      setModels(choices); setValue(settings[KEY] || ''); setLoading(false); setReady(true);
    }).catch((e: Error) => {
      if (version === generation.current) { setError(e.message); setLoading(false); }
    });
    return () => { generation.current++; };
  }, [api, refreshKey, attempt]);
  async function choose(next: string) {
    if (!ready || loading || saving) return;
    const version = generation.current;
    setSaving(true); setError('');
    try {
      await api.putSetting(KEY, next);
      if (version === generation.current) setValue(next);
    } catch (e: unknown) {
      if (version === generation.current) setError(e instanceof Error ? e.message : '写作模型保存失败');
    } finally { if (version === generation.current) setSaving(false); }
  }
  const missing = value && !models.some(model => String(model.id) === value);
  return <section className="card space-y-3" aria-labelledby="review-model-heading">
    <div><h2 id="review-model-heading" className="text-lg">专题综述写作</h2>
      <p className="mt-1 text-sm text-muted">逐篇分析使用默认文本 AI；可单独选择用于综合、章节写作和修订的模型。更换写作模型后，未改变的逐篇分析仍可复用。</p></div>
    <label className="block text-xs text-muted">综述写作模型
      <select className="input mt-1 w-full text-xs" aria-label="综述写作模型" value={value}
        disabled={!ready || loading || saving} onChange={e => void choose(e.target.value)}>
        <option value="">跟随默认文本 AI</option>
        {missing && <option value={value} disabled>已配置模型不可用，请重新选择</option>}
        {models.map(model => <option value={model.id} key={model.id}>{model.name} · {model.provider}</option>)}
      </select>
    </label>
    <p className="text-xs text-muted" role="status">{loading ? '正在加载模型…' : saving ? '正在保存…' : '按项目自动保存，也用于综述的按段 AI 修改；从下一次生成或修改请求生效。'}</p>
    {error && <p role="alert" className="text-xs" style={{ color: 'var(--danger)' }}>{error}
      <button className="btn-ghost ml-1 text-xs" disabled={saving} onClick={() => setAttempt(n => n + 1)}>重新加载</button>
    </p>}
  </section>;
}
