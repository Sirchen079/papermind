// T6：聊天回答回流——把助手回答沉淀为阅读笔记或研究想法。
// 论文选择规则：有论文上下文→默认该论文；只有 RAG 来源→用户必须明确选择
// （不静默选第一篇）；两者皆无→可从全库选择笔记归属，想法默认不挂论文。

export interface ChatSourceLike {
  paper_id: number;
  title: string | null;
}

export type CaptureFlow =
  | { flow: "paper"; paperId: number }
  | { flow: "pick"; sources: ChatSourceLike[] }
  | { flow: "free" };

export function captureFlow(paperContextId: number | null, sources: ChatSourceLike[]): CaptureFlow {
  if (paperContextId != null) return { flow: "paper", paperId: paperContextId };
  if (sources.length > 0) return { flow: "pick", sources };
  return { flow: "free" };
}

export type PaperChoice = number | "required" | null;

// pick 流程未选择时返回 "required"，调用方据此展示提示并阻止保存。
export function resolveCapturePaper(
  flow: CaptureFlow,
  chosenPaperId: number | null,
): PaperChoice {
  if (flow.flow === "paper") return flow.paperId;
  if (flow.flow === "pick") return chosenPaperId == null ? "required" : chosenPaperId;
  return chosenPaperId;
}

export function notePayloadFromAnswer(answer: string): Record<string, unknown> {
  return { kind: "note", content: answer, tags: [] };
}

export function ideaTitleFromAnswer(answer: string): string {
  const firstLine =
    answer
      .split("\n")
      .map((line) => line.trim())
      .find(Boolean) ?? "来自对话的研究想法";
  return firstLine.length > 60 ? `${firstLine.slice(0, 59)}…` : firstLine;
}

export function ideaPayloadFromAnswer(
  answer: string,
  paperId: number | null,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    title: ideaTitleFromAnswer(answer),
    content: answer,
    origin: "manual",
  };
  if (paperId != null) {
    payload.papers = [{ paper_id: paperId, role: "basis" }];
  }
  return payload;
}
