/**
 * 「连接一个 AI 服务」表单的纯逻辑：常用服务商预设与连通性测试结果的文案。
 * base_url 取各厂商公开文档值；预设不含任何 API key。
 */

export type ProviderPreset = {
  key: string;
  label: string;
  type: string;
  base_url: string;
  note?: string;
};

export const PROVIDER_PRESETS: ProviderPreset[] = [
  { key: "zhipu", label: "智谱 GLM", type: "openai_compat", base_url: "https://open.bigmodel.cn/api/paas/v4" },
  { key: "openai", label: "OpenAI", type: "openai_chat", base_url: "", note: "官方地址，无需填接口地址" },
  { key: "anthropic", label: "Anthropic / Claude", type: "anthropic", base_url: "https://api.anthropic.com" },
  { key: "deepseek", label: "DeepSeek", type: "openai_compat", base_url: "https://api.deepseek.com" },
  { key: "openrouter", label: "OpenRouter", type: "openai_compat", base_url: "https://openrouter.ai/api/v1" },
  { key: "moonshot", label: "Moonshot Kimi", type: "openai_compat", base_url: "https://api.moonshot.cn/v1" },
  { key: "siliconflow", label: "硅基流动", type: "openai_compat", base_url: "https://api.siliconflow.cn/v1" },
  { key: "ollama", label: "Ollama 本地", type: "openai_compat", base_url: "http://localhost:11434/v1", note: "需先启动 Ollama" },
  { key: "custom", label: "自定义", type: "", base_url: "" },
];

export type ProviderForm = { name: string; type: string; base_url: string; api_key: string };

/** 选中预设后填表：自定义原样返回；否则填 type、base_url，name 为空时用预设名，api_key 不动。 */
export function applyPreset(form: ProviderForm, preset: ProviderPreset): ProviderForm {
  if (preset.key === "custom" || (!preset.type && !preset.base_url)) return form;
  return {
    name: form.name.trim() === "" ? preset.label : form.name,
    type: preset.type,
    base_url: preset.base_url,
    api_key: form.api_key,
  };
}

export type ProviderTestResult = {
  ok: boolean;
  latency_ms: number;
  model_id: string;
  note?: string;
  error?: string;
};

/** 测试结果的人话文案：成功显示延迟与所用模型，失败显示原因。 */
export function testResultText(result: ProviderTestResult): string {
  if (!result.ok) return `连接失败：${result.error ?? "未知错误"}`;
  const base = `连接正常 · ${result.latency_ms}ms · ${result.model_id}`;
  return result.note ? `${base}（回复为空，可能是思考型模型）` : base;
}
