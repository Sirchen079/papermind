export const MAX_QUEUED_TURNS = 10;
export interface QueueItem { id: string; state: 'waiting' | 'sending'; }
export function appendQueued<T extends QueueItem>(items: T[], item: T): T[] {
  if (items.length >= MAX_QUEUED_TURNS) throw new Error('最多排队 10 条，请先发送或移除部分消息');
  return [...items, item];
}
export function nextQueued<T extends QueueItem>(items: T[], paused: boolean, blocked: boolean): T | undefined {
  if (paused || blocked || items[0]?.state !== 'waiting') return undefined;
  return items[0];
}
export function finishQueued<T extends QueueItem>(items: T[], id: string): T[] {
  return items.filter(item => item.id !== id);
}
