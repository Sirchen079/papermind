export type ReadinessTone = "success" | "warning" | "danger" | "muted";

export interface ReadinessCheckLike {
  id: string;
  label?: string;
  status: string;
  action: string;
  route: string;
}

export interface FirstUseGuideStep {
  id: string;
  title: string;
  detail: string;
  status: "done" | "warning" | "action";
  action: string;
  route: string;
  checkIds: string[];
}

export interface FirstUseGuide {
  steps: FirstUseGuideStep[];
  completed: number;
  total: number;
  percent: number;
  nextStep: FirstUseGuideStep | null;
}

const GUIDE_DEFS = [
  {
    id: "models",
    title: "配置模型能力",
    detail: "接入 Kimi 等 LLM 和硅基流动等向量模型，后续摘要、问答、索引和图谱才有基础。",
    checkIds: ["llm", "embedding"],
  },
  {
    id: "library",
    title: "导入第一批论文",
    detail: "先导入 20-50 篇与课题直接相关的 PDF、BibTeX、arXiv 或手动文献。",
    checkIds: ["library"],
  },
  {
    id: "analysis",
    title: "生成摘要、图谱和检索索引",
    detail: "让系统完成 AI 摘要、概念抽取、RAG 索引和图谱关系，后续检索与对话才可靠。",
    checkIds: ["analysis", "rag", "graph"],
  },
  {
    id: "reading",
    title: "开始精读沉淀",
    detail: "给论文标记状态、优先级、相关度，并补充笔记、摘录和审阅矩阵。",
    checkIds: ["reading"],
  },
  {
    id: "writing",
    title: "建立论文写作结构",
    detail: "建立研究方向、章节和论文链接，把阅读材料持续沉淀到写作位置。",
    checkIds: ["writing"],
  },
];

export function readinessLevelLabel(level: string): string {
  if (level === "setup") return "待配置";
  if (level === "usable") return "可试用";
  if (level === "ready") return "可持续使用";
  return "未知状态";
}

export function readinessStatusTone(status: string): ReadinessTone {
  if (status === "done") return "success";
  if (status === "warning") return "warning";
  if (status === "action") return "danger";
  return "muted";
}

export function summarizeReadinessChecks(checks: ReadinessCheckLike[]) {
  const counts = { done: 0, warning: 0, action: 0 };
  for (const check of checks) {
    if (check.status === "done") counts.done += 1;
    else if (check.status === "warning") counts.warning += 1;
    else if (check.status === "action") counts.action += 1;
  }
  const next = checks.find((check) => check.status === "action") ?? checks.find((check) => check.status === "warning");
  return {
    counts,
    nextAction: next ? { label: next.action, route: next.route } : null,
  };
}

// 导入抽屉顶部的 AI 分析提示：未配置模型时明确"允许导入但跳过分析"。
export function aiAnalysisHint(llmConfigured: boolean): string {
  return llmConfigured
    ? "已配置模型：导入完成后会自动生成 AI 摘要与概念。"
    : "尚未配置模型：仍可导入论文，AI 摘要将跳过，之后在「设置」中配置模型即可重新分析。";
}

export type PaperAnalysisState = "done" | "failed" | "skipped" | "pending";

export interface PaperAnalysisView {
  state: PaperAnalysisState;
  label: string;
  detail: string;
  canRetry: boolean;
}

export interface PaperAnalysisInput {
  hasSummary: boolean;
  analysisStatus: string | null;
  analysisError: string | null;
  llmConfigured: boolean;
}

// 论文详情的三态分析状态：完成 / 失败可重试 / 未配置已跳过 / 待分析。
export function paperAnalysisView(input: PaperAnalysisInput): PaperAnalysisView {
  if (input.hasSummary) {
    return { state: "done", label: "分析完成", detail: "已生成 AI 摘要。", canRetry: true };
  }
  if (input.analysisStatus === "failed") {
    return {
      state: "failed",
      label: "分析失败",
      detail: input.analysisError ? `上次分析失败：${input.analysisError}` : "上次分析失败，可重试。",
      canRetry: true,
    };
  }
  if (!input.llmConfigured) {
    return {
      state: "skipped",
      label: "未配置模型，已跳过",
      detail: "尚未配置可用模型，AI 分析已跳过；先在设置中配置模型，再回来分析。",
      canRetry: false,
    };
  }
  return { state: "pending", label: "待分析", detail: "尚未生成 AI 摘要。", canRetry: true };
}

export interface ModelRoleLike {
  model_id: string;
  role_default: string | null;
}

export interface ModelRoleStatus {
  llm: ModelRoleLike | null;
  embedding: ModelRoleLike | null;
}

// 设置页角色分配总览：LLM（对话/总结/抽取共用）与向量模型是否已各就其位。
export function modelRoleStatus(models: ModelRoleLike[]): ModelRoleStatus {
  return {
    llm: models.find((model) => model.role_default === "chat") ?? null,
    embedding: models.find((model) => model.role_default === "embedding") ?? null,
  };
}

export function buildFirstUseGuide(checks: ReadinessCheckLike[]): FirstUseGuide {
  const byId = new Map(checks.map((check) => [check.id, check]));
  const steps = GUIDE_DEFS.map((definition) => {
    const related = definition.checkIds.map((id) => byId.get(id)).filter((check): check is ReadinessCheckLike => Boolean(check));
    const unfinished = related.find((check) => check.status === "action") ?? related.find((check) => check.status === "warning");
    const status: FirstUseGuideStep["status"] = related.some((check) => check.status === "action")
      ? "action"
      : related.some((check) => check.status === "warning")
        ? "warning"
        : "done";
    return {
      id: definition.id,
      title: definition.title,
      detail: definition.detail,
      status,
      action: unfinished?.action ?? "查看状态",
      route: unfinished?.route ?? related[0]?.route ?? "library",
      checkIds: definition.checkIds,
    };
  });
  const completed = steps.filter((step) => step.status === "done").length;
  return {
    steps,
    completed,
    total: steps.length,
    percent: Math.round((completed / steps.length) * 100),
    nextStep: steps.find((step) => step.status !== "done") ?? null,
  };
}
