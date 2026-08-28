export type ProgressTone = "success" | "warning" | "danger" | "muted";

export interface ProgressActionLike {
  id: string;
  priority: string;
}

export function progressPriorityLabel(priority: string): string {
  if (priority === "high") return "优先处理";
  if (priority === "normal") return "建议推进";
  if (priority === "low") return "持续维护";
  return "待处理";
}

export function progressPriorityTone(priority: string): ProgressTone {
  if (priority === "high") return "danger";
  if (priority === "normal") return "warning";
  if (priority === "low") return "success";
  return "muted";
}

export function summarizeProgressActions(actions: ProgressActionLike[]) {
  return actions.reduce(
    (acc, action) => {
      if (action.priority === "high") acc.high += 1;
      else if (action.priority === "normal") acc.normal += 1;
      else if (action.priority === "low") acc.low += 1;
      return acc;
    },
    { high: 0, normal: 0, low: 0 },
  );
}

export function researchProgressMarkdownExportUrl(apiBase = "/api"): string {
  const base = apiBase.replace(/\/$/, "");
  return `${base}/research/progress/markdown`;
}
