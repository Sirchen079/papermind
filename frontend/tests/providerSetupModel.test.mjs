import test from 'node:test';
import assert from 'node:assert/strict';
import { PROVIDER_PRESETS, applyPreset, testResultText } from '../.tmp_graph_test_dist/providerSetupModel.js';

function presetByKey(key) {
  return PROVIDER_PRESETS.find((p) => p.key === key);
}

test('preset list covers the documented vendors with official base urls', () => {
  const keys = PROVIDER_PRESETS.map((p) => p.key);
  for (const key of ['zhipu', 'openai', 'anthropic', 'deepseek', 'openrouter', 'moonshot', 'siliconflow', 'ollama', 'custom']) {
    assert.ok(keys.includes(key), `missing preset: ${key}`);
  }
  assert.equal(presetByKey('zhipu').type, 'openai_compat');
  assert.equal(presetByKey('zhipu').base_url, 'https://open.bigmodel.cn/api/paas/v4');
  assert.equal(presetByKey('openai').type, 'openai_chat');
  assert.equal(presetByKey('openai').base_url, '');
  assert.ok(presetByKey('openai').note);
  assert.equal(presetByKey('anthropic').type, 'anthropic');
  assert.equal(presetByKey('anthropic').base_url, 'https://api.anthropic.com');
  assert.equal(presetByKey('deepseek').base_url, 'https://api.deepseek.com');
  assert.equal(presetByKey('openrouter').base_url, 'https://openrouter.ai/api/v1');
  assert.equal(presetByKey('moonshot').base_url, 'https://api.moonshot.cn/v1');
  assert.equal(presetByKey('siliconflow').base_url, 'https://api.siliconflow.cn/v1');
  assert.equal(presetByKey('ollama').base_url, 'http://localhost:11434/v1');
  assert.ok(presetByKey('ollama').note);
  assert.equal(presetByKey('custom').type, '');
  assert.equal(presetByKey('custom').base_url, '');
});

test('applyPreset fills type and base_url, names empty forms with the preset label', () => {
  const filled = applyPreset(
    { name: '', type: 'openai_chat', base_url: '', api_key: '' },
    presetByKey('deepseek')
  );
  assert.deepEqual(filled, { name: 'DeepSeek', type: 'openai_compat', base_url: 'https://api.deepseek.com', api_key: '' });
});

test('applyPreset keeps a user-typed name and never touches the api key', () => {
  const kept = applyPreset(
    { name: '我的中转', type: 'anthropic', base_url: 'https://example.com', api_key: 'sk-secret' },
    presetByKey('zhipu')
  );
  assert.deepEqual(kept, { name: '我的中转', type: 'openai_compat', base_url: 'https://open.bigmodel.cn/api/paas/v4', api_key: 'sk-secret' });
});

test('applyPreset with the custom preset leaves the form exactly as-is', () => {
  const form = { name: 'x', type: 'openai_responses', base_url: 'https://example.com', api_key: 'k' };
  assert.equal(applyPreset(form, presetByKey('custom')), form);
});

test('testResultText renders latency and model on success', () => {
  assert.equal(testResultText({ ok: true, latency_ms: 123, model_id: 'glm-4' }), '连接正常 · 123ms · glm-4');
});

test('testResultText appends the empty-reply hint only when a note is present', () => {
  const withNote = testResultText({ ok: true, latency_ms: 0, model_id: 'glm-4', note: '回复为空' });
  assert.ok(withNote.startsWith('连接正常 · 0ms · glm-4'));
  assert.ok(withNote.includes('回复为空'));
  assert.ok(withNote.includes('思考型模型'));
  const withoutNote = testResultText({ ok: true, latency_ms: 5, model_id: 'm', note: undefined });
  assert.equal(withoutNote, '连接正常 · 5ms · m');
});

test('testResultText renders the error message on failure', () => {
  assert.equal(testResultText({ ok: false, latency_ms: 12, model_id: 'gpt-4o', error: '409 还没有可测试的模型' }), '连接失败：409 还没有可测试的模型');
  assert.equal(testResultText({ ok: false, latency_ms: 12, model_id: 'gpt-4o' }), '连接失败：未知错误');
});
