import { readDraft, writeDraft, type DraftStorage } from './draftStorageModel';
import type { PaperChatContext } from './chatContextModel';

function key(scope: string, workspace: string, conversation: number) {
  return `pm-conversation-context-${scope}-${workspace}-${conversation}`;
}

export function readConversationContext(storage: DraftStorage | null, scope: string, workspace: string, conversation: number): PaperChatContext | null {
  const value = readDraft<Partial<PaperChatContext>>(storage, key(scope, workspace, conversation), {});
  if (!Number.isSafeInteger(value.paperId) || (value.paperId ?? 0) <= 0) return null;
  if (value.paperTitle !== null && typeof value.paperTitle !== 'string') return null;
  if (value.selectedText !== null && typeof value.selectedText !== 'string') return null;
  return value as PaperChatContext;
}

export function saveConversationContext(storage: DraftStorage | null, scope: string, workspace: string, conversation: number, context: PaperChatContext | null): boolean {
  return writeDraft(storage, key(scope, workspace, conversation), context);
}

export function restoreConversationContext(saved: PaperChatContext | null, current: PaperChatContext | null): PaperChatContext | null {
  if (!current) return null;
  return { ...current, selectedText: saved?.paperId === current.paperId ? saved.selectedText : null };
}
