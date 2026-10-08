import { useEffect, useRef, useState } from 'react';
import type { DocumentModel } from '../api';
import { useApi } from '../workspaceContext';

export function DocumentModelSettings({ refreshKey, ocrOnly = false, onSaved }: { refreshKey?: unknown; ocrOnly?: boolean; onSaved?: () => void }) {
  const api = useApi();
  const [choices, setChoices] = useState<{ocr: DocumentModel[]; rerank: DocumentModel[]; rerank_llm: DocumentModel[]}>({ocr: [], rerank: [], rerank_llm: []});
  const [values, setValues] = useState<Record<string, string | null>>({});
  const [loading, setLoading] = useState(true);
  const [ready, setReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const generation = useRef(0);
  useEffect(() => {
    const version = ++generation.current;
    setLoading(true); setReady(false); setSaving(false); setError('');
    Promise.all([api.documentModels(), api.listSettings()]).then(([models, settings]) => {
      if (version === generation.current) { setChoices(models); setValues(settings); setLoading(false); setReady(true); }
    }).catch((e: Error) => { if (version === generation.current) { setError(e.message); setLoading(false); } });
    return () => { generation.current++; };
  }, [api, refreshKey, attempt]);
  async function choose(key: string, value: string) {
    if (!ready || loading || saving) return;
    const version = generation.current;
    setSaving(true); setError('');
    try {
      await api.putSetting(key, value);
      if (version === generation.current) { setAttempt(n => n + 1); onSaved?.(); }
    } catch (e: unknown) {
      if (version === generation.current) setError(e instanceof Error ? e.message : '保存失败');
    } finally { if (version === generation.current) setSaving(false); }
  }
  const mode = values.rerank_mode || (values.rerank_model_config_id ? 'dedicated' : 'off');
  function modelControl(purpose: 'ocr' | 'rerank' | 'rerank_llm') {
      const value = values[`${purpose}_model_config_id`] || '';
      const label = purpose === 'ocr' ? 'OCR 模型' : purpose === 'rerank_llm' ? '用于重排序的大模型' : '重排序模型';
      return <div key={purpose} className="space-y-1">
        <label className="block text-xs text-muted">{label}
          <select className="input mt-1 w-full text-xs" aria-label={label} value={value} disabled={!ready || loading || saving}
            onChange={e => void choose(`${purpose}_model_config_id`, e.target.value)}>
            <option value="">{purpose === 'ocr' ? '未配置（新导入 PDF 等待配置）' : purpose === 'rerank_llm' ? '跟随默认文本 AI（可共用同一个模型）' : '请选择专用重排序模型'}</option>
            {value && !choices[purpose].some(m => String(m.id) === value) && <option value={value} disabled>已配置模型不可用，请重新选择</option>}
            {choices[purpose].map(m => <option key={m.id} value={m.id}>{m.name} · {m.provider}{purpose === 'ocr' && m.supports_images == null ? '（图片能力未确认）' : ''}</option>)}
          </select>
        </label>
        <p className="text-xs text-muted">{purpose === 'ocr' ? '选择专用 OCR 或支持图片输入的多模态模型。识别时会将页面图片发送至所选连接，按其规则计费。' : purpose === 'rerank_llm' ? '让文本 AI 按问题相关性筛选候选片段，可与对话、翻译和 OCR 共用模型。专题综述的中文问题会额外调用一次模型补充英文检索，再合并原查询的候选统一排序。改写或排序失败时仍保留已有结果。有候选时排序另需一次模型请求。' : '需要支持 /rerank 接口的专用模型。对已召回的候选按问题相关性重新排序；专题综述同时使用向量与关键词候选。排序失败时保留已有结果。'}</p>
        {purpose === 'rerank_llm' && ready && !choices.rerank_llm.length && <p className="text-xs text-muted">尚无可用文本模型，请先添加或启用模型连接。</p>}
      </div>;
  }
  return <section className={ocrOnly ? 'space-y-3' : 'card space-y-3'} aria-label="文档与检索模型">
    {!ocrOnly && <div><h2 className="text-lg">文档与检索</h2><p className="mt-1 text-sm text-muted">复用已添加连接的地址和密钥，模型选择按项目保存。</p></div>}
    {modelControl('ocr')}
    {!ocrOnly && <label className="block text-xs text-muted">新导入 PDF 的解析方式
      <select className="input mt-1 w-full text-xs" aria-label="新导入 PDF 的解析方式" value={values.pdf_ingest_mode || 'ocr'} disabled={!ready || loading || saving} onChange={e => void choose('pdf_ingest_mode', e.target.value)}>
        <option value="ocr">全文 OCR → Markdown → 向量索引（默认）</option>
        <option value="auto">自动转换：文字页直接提取，扫描页 OCR</option>
        <option value="advanced">高级解析引擎 → Markdown → 向量索引</option>
        <option value="manual">直接提取文字，之后手动转换</option>
      </select>
      <p className="mt-1 text-xs text-muted">全文 OCR 会识别所有页面。缺少模型时先保存 PDF；选好 OCR 模型后自动继续待处理的导入。已有文献不会自动重识别。</p>
    </label>}
    <div className="space-y-1">
      <label className="block text-xs text-muted">高级解析引擎地址（可选）
        <input className="input mt-1 w-full text-xs" type="url" placeholder="例如 http://127.0.0.1:8765" aria-label="高级解析引擎地址"
          value={values.advanced_parser_url || ''} disabled={!ready || loading || saving}
          onChange={e => setValues(current => ({...current, advanced_parser_url: e.target.value}))}
          onBlur={e => {const next = (e.target.value || '').trim(); if (next !== (values.advanced_parser_url || '')) void choose('advanced_parser_url', next);}} />
      </label>
      <p className="text-xs text-muted">填写本地或云端版面解析服务的 http(s) 地址后，可在文档转换中选择“高级解析引擎”整册处理扫描件与复杂表格；留空不启用。页面图像仍由本机保留，来源回查不受影响。</p>
    </div>
    {!ocrOnly && <div className="space-y-3">
      <label className="block text-xs text-muted">重排序方式
        <select className="input mt-1 w-full text-xs" aria-label="重排序方式" value={mode} disabled={!ready || loading || saving} onChange={e => void choose('rerank_mode', e.target.value)}>
          <option value="off">关闭重排序</option><option value="dedicated">专用重排序模型</option><option value="llm">大模型重排序（可共用文本 AI）</option>
        </select>
      </label>
      {mode === 'dedicated' && modelControl('rerank')}
      {mode === 'llm' && modelControl('rerank_llm')}
    </div>}
    {(loading || saving) && <p role="status" className="text-xs text-muted">{saving ? '正在保存…' : '正在加载…'}</p>}
    {error && <p role="alert" className="text-xs" style={{color: 'var(--danger)'}}>{error} <button className="btn-ghost" disabled={saving} onClick={() => setAttempt(n => n + 1)}>重新加载</button></p>}
  </section>;
}
