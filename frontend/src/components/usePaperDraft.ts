import { useEffect, useState } from 'react';
import { clearMatchingDraft, readDraft, writeDraft } from '../pages/draftStorageModel';
import { useWorkspace, workspaceDraftKey } from '../workspaceContext';

export function localStore() { try { return window.localStorage; } catch { return null; } }
export function libraryScope() {
  const token = document.querySelector('meta[name="papermind-local-token"]')?.getAttribute('content') ?? '';
  let hash = 2166136261;
  for (const character of token) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619);
  return (hash >>> 0).toString(16);
}

export function usePaperDraft<T extends object>(paperId: number | string | undefined, empty: T, kind: string, scope: 'workspace' | 'application' = 'workspace') {
  const {workspace}=useWorkspace();
  const [, refresh] = useState(0);
  const [storageError, setStorageError] = useState(false);
  const base = `pm-paper-draft-${libraryScope()}-${kind}-${paperId}`;
  const key = scope === 'application' ? `application:${base}` : workspaceDraftKey(workspace.id,base);
  const storage = localStore();
  const draft = paperId === undefined ? empty : readDraft(storage, key, empty);
  function setDraft(value: T) {
    if (paperId === undefined) return;
    setStorageError(!writeDraft(storage, key, value));
    refresh(revision => revision + 1);
  }
  function clearSavedDraft(saved: T) {
    if (paperId === undefined) return;
    clearMatchingDraft(storage, key, saved, empty);
    refresh(revision => revision + 1);
  }
  useEffect(() => {
    if (!storageError) return;
    const protect = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', protect);
    return () => window.removeEventListener('beforeunload', protect);
  }, [storageError]);
  return [draft, setDraft, clearSavedDraft, storageError] as const;
}
