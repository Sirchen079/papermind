export interface DraftStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

// This fallback survives route unmounts if browser storage is unavailable.
const fallback = new Map<string, string>();
const unsynced = new Set<string>();
const protectUnsyncedDrafts = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
function updateUnloadProtection() {
  if (typeof window === 'undefined') return;
  window.removeEventListener('beforeunload', protectUnsyncedDrafts);
  if ([...unsynced].some(key => fallback.has(key))) window.addEventListener('beforeunload', protectUnsyncedDrafts);
}

export function readDraft<T>(storage: DraftStorage | null, key: string, empty: T): T {
  let raw: string | null | undefined;
  try { raw = unsynced.has(key) || !storage ? fallback.get(key) : storage.getItem(key); }
  catch { raw = fallback.get(key); }
  try {
    if (!raw) return empty;
    const value = JSON.parse(raw);
    if (!value || typeof value !== 'object') return empty;
    for (const [field, initial] of Object.entries(empty as object)) {
      if (typeof value[field] !== typeof initial) return empty;
      if (initial !== null && typeof initial === 'object' &&
          (value[field] === null || Array.isArray(value[field]) !== Array.isArray(initial))) return empty;
    }
    fallback.set(key, raw);
    return value as T;
  } catch { return empty; }
}

export function writeDraft<T>(storage: DraftStorage | null, key: string, value: T | null): boolean {
  if (value === null) fallback.delete(key);
  else fallback.set(key, JSON.stringify(value));
  try {
    if (!storage) throw new Error('Storage unavailable');
    if (value === null) storage.removeItem(key);
    else storage.setItem(key, JSON.stringify(value));
    unsynced.delete(key);
    updateUnloadProtection();
    return true;
  } catch { unsynced.add(key); updateUnloadProtection(); return false; }
}

export function clearMatchingDraft<T>(storage: DraftStorage | null, key: string, saved: T, empty: T): boolean {
  if (JSON.stringify(readDraft(storage, key, empty)) !== JSON.stringify(saved)) return false;
  writeDraft(storage, key, null);
  return true;
}

export interface ResearchDraft {baseVersion: number; content: string; refs: string[]}
export function readResearchDraft(storage: DraftStorage | null, key: string): ResearchDraft | null {
  const value = readDraft(storage, key, {baseVersion: -1, content: '', refs: [] as string[]});
  return Number.isInteger(value.baseVersion) && value.baseVersion >= 0 && value.refs.every(ref => typeof ref === 'string') ? value : null;
}

export function sameResearchEdit(left: Pick<ResearchDraft, 'content' | 'refs'>, right: Pick<ResearchDraft, 'content' | 'refs'>) {
  return left.content === right.content && JSON.stringify(left.refs) === JSON.stringify(right.refs);
}

export function syncResearchDraft(storage: DraftStorage | null, key: string, draft: ResearchDraft, dirty: boolean): boolean {
  if (dirty) return writeDraft(storage, key, draft);
  else {
    const prior = readResearchDraft(storage, key);
    if (prior?.baseVersion === draft.baseVersion) return writeDraft(storage, key, null);
  }
  return true;
}
