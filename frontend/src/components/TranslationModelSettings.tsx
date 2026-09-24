import { useEffect, useRef, useState } from 'react';
import type { ChatModel } from '../api';
import { useApi } from '../workspaceContext';

const SETTING_KEY = 'translation_model_config_id';

export function useTranslationModel(refreshKey?: unknown) {
  const api = useApi();
  const [models, setModels] = useState<ChatModel[]>([]);
  const [model, setModel] = useState('');
  const [loading, setLoading] = useState(true);
  const [ready, setReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const generation = useRef(0);
  useEffect(() => {
    const version = ++generation.current;
    setLoading(true); setReady(false); setSaving(false); setError('');
    Promise.all([api.chatModels(), api.listSettings()]).then(([rows, settings]) => {
      if (version !== generation.current) return;
      setModels(rows); setModel(settings[SETTING_KEY] || ''); setLoading(false); setReady(true);
    }).catch((e: Error) => {
      if (version === generation.current) { setError(e.message); setLoading(false); }
    });
    return () => { generation.current++; };
  }, [api, attempt, refreshKey]);
  async function choose(value: string) {
    if (saving || loading) return;
    const version = generation.current;
    setSaving(true); setError('');
    try {
      await api.putSetting(SETTING_KEY, value);
      if (version === generation.current) setModel(value);
    } catch (e: unknown) {
      if (version === generation.current) setError(e instanceof Error ? e.message : '翻译模型保存失败，请重试。');
    } finally {
      if (version === generation.current) setSaving(false);
    }
  }
  return { models, model, loading, ready, saving, error, choose, reload: () => setAttempt(n => n + 1) };
}

export function TranslationModelControl({ config }: { config: ReturnType<typeof useTranslationModel> }) {
  const missing = config.model && !config.models.some(model => String(model.id) === config.model);
  return <div className="space-y-1">
    <label className="block text-xs text-muted">翻译模型
      <select className="input mt-1 w-full text-xs" aria-label="翻译模型" value={config.model}
        disabled={config.loading || config.saving} onChange={e => void config.choose(e.target.value)}>
        <option value="">跟随默认文本 AI</option>
        {missing && <option value={config.model} disabled>已配置模型不可用，请重新选择</option>}
        {config.models.map(model => <option value={model.id} key={model.id}>{model.name} · {model.provider}</option>)}
      </select>
    </label>
    <p className="text-xs text-muted" role="status">{config.loading ? '正在加载模型…' : config.saving ? '正在保存…' : '选择后自动保存为本项目的翻译模型。'}</p>
    {config.error && <p role="alert" className="text-xs" style={{ color: 'var(--danger)' }}>{config.error}
      <button className="btn-ghost ml-1 text-xs" onClick={config.reload} disabled={config.saving}>重新加载模型</button>
    </p>}
  </div>;
}

export function TranslationModelSettings({ refreshKey }: { refreshKey?: unknown }) {
  const config = useTranslationModel(refreshKey);
  return <section className="card space-y-3" aria-labelledby="translation-model-heading">
    <div><h2 id="translation-model-heading" className="text-lg">划词翻译</h2>
      <p className="mt-1 text-sm text-muted">为 PDF 划词翻译单独选择模型。对话、总结和抽取继续使用原有模型配置。</p></div>
    <TranslationModelControl config={config} />
  </section>;
}
