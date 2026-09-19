import { useEffect, useRef, useState } from 'react';

// Images can exceed localStorage's quota. Keep one ordered IndexedDB store and
// a memory cache so page changes cannot race a pending write or hydration.
const cache = new Map<string, unknown>();
const listeners = new Map<string, Set<(value: unknown) => void>>();
const reads = new Map<string, Promise<unknown>>();
let database: Promise<IDBDatabase> | undefined;
function db() {
  return database ??= new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open('papermind-chat-drafts', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('drafts');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => { database = undefined; reject(request.error); };
  });
}
async function read(key: string) {
  if (cache.has(key)) return cache.get(key);
  let pending = reads.get(key);
  if (!pending) {
    pending = db().then(database => new Promise<unknown>((resolve, reject) => {
      const request = database.transaction('drafts').objectStore('drafts').get(key);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    })).then(value => { if (!cache.has(key)) cache.set(key, value); return cache.get(key); })
      .finally(() => reads.delete(key));
    reads.set(key, pending);
  }
  return pending;
}
let writes: Promise<void> = Promise.resolve();
function write(key: string, value: unknown) {
  cache.set(key, value);
  const result = writes.catch(() => {}).then(async () => {
    const database = await db();
    await new Promise<void>((resolve, reject) => {
      const tx = database.transaction('drafts', 'readwrite');
      tx.objectStore('drafts').put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror = tx.onabort = () => reject(tx.error ?? new Error('保存失败'));
    });
  });
  writes = result;
  return result;
}
export function useChatDraft<T extends object>(key: string, empty: T) {
  const [state, setState] = useState<{key: string; value: T; ready: boolean}>({key, value: (cache.get(key) as T) ?? empty, ready: cache.has(key)});
  const [error, setError] = useState(false);
  const [saving, setSaving] = useState(0);
  const current = useRef(key); current.current = key;
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    let active = true;
    const receive = (value: unknown) => setState({key, value: value as T, ready: true});
    const subscribers = listeners.get(key) ?? new Set();
    subscribers.add(receive); listeners.set(key, subscribers);
    setError(false);
    read(key).then(value => { if (active) setState({key, value: (value as T) ?? empty, ready: true}); })
      .catch(() => { if (active) { setState({key, value: (cache.get(key) as T) ?? empty, ready: true}); setError(true); } });
    return () => { active = false; subscribers.delete(receive); if (!subscribers.size) listeners.delete(key); };
  }, [key]);
  function update(change: (previous: T) => T) {
    const previous = (cache.get(key) as T) ?? (state.key === key ? state.value : empty);
    const value = change(previous);
    cache.set(key, value);
    listeners.get(key)?.forEach(receive => receive(value));
    if (alive.current && current.current === key) setSaving(n => n + 1);
    return write(key, value).then(() => { if (alive.current && current.current === key) setError(false); return true; })
      .catch(() => { if (alive.current && current.current === key) setError(true); return false; })
      .finally(() => { if (alive.current) setSaving(n => Math.max(0, n - 1)); });
  }
  useEffect(() => {
    if (!error && !saving) return;
    const protect = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', protect);
    return () => window.removeEventListener('beforeunload', protect);
  }, [error, saving]);
  return { value: state.key === key ? state.value : empty, ready: state.key === key && state.ready, update, error, saving: !!saving };
}
