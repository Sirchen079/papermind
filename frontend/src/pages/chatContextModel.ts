// T5：论文上下文对话的前端纯模型。
// paper_id/selected_text 按 Conversation ID 在前端保存，只随该会话请求携带。
// 新建空白对话不继承；显式从论文提问会创建独立会话。摘录按应用、项目及会话保存。

export const SELECTED_TEXT_LIMIT = 4000;

export interface PaperChatContext {
  paperId: number;
  paperTitle: string | null;
  selectedText: string | null;
}

export interface ChatMessageExtra {
  paper_id?: number;
  selected_text?: string;
}

export function selectedTextOverLimit(text: string | null | undefined): boolean {
  return typeof text === "string" && text.length > SELECTED_TEXT_LIMIT;
}

export function contextBadgeLabel(ctx: PaperChatContext): string {
  const title = ctx.paperTitle?.trim() || `论文 #${ctx.paperId}`;
  return ctx.selectedText ? `正在就《${title}》选中的内容提问` : `正在就《${title}》提问`;
}

export function chatMessagePayload(
  content: string,
  ctx: PaperChatContext | null,
): { content: string } & ChatMessageExtra {
  const payload: { content: string } & ChatMessageExtra = { content };
  if (ctx) {
    payload.paper_id = ctx.paperId;
    if (ctx.selectedText && !selectedTextOverLimit(ctx.selectedText)) {
      payload.selected_text = ctx.selectedText;
    }
  }
  return payload;
}

// 首条消息发出后选中文本即被消费：后续消息继续带 paper_id，但不再重复选中文本。
export function consumeSelection(ctx: PaperChatContext): PaperChatContext {
  return ctx.selectedText ? { ...ctx, selectedText: null } : ctx;
}
