import { useApi } from '../workspaceContext';
import { useEffect, useState } from 'react';
import { type Paper } from '../api';

/** Association pickers always search the library, independent of the parent view. */
export function usePaperSearch(query: string, enabled: boolean) {
  const api = useApi();
  const [result, setResult] = useState<{ query: string; papers: Paper[]; total: number; error: string }>({ query: '', papers: [], total: 0, error: '' });
  const [pending, setPending] = useState(false);
  const text = query.trim();
  useEffect(() => {
    if (!enabled || !text) { setPending(false); return; }
    let alive = true;
    setPending(true);
    const timer = setTimeout(() => {
      api.listPapers(50, 0, text).then(page => {
        if (alive) setResult({ query: text, papers: page.items, total: page.total, error: '' });
      }).catch((error: Error) => {
        if (alive) setResult({ query: text, papers: [], total: 0, error: error.message || '搜索失败，请重新输入关键词重试。' });
      }).finally(() => { if (alive) setPending(false); });
    }, 200);
    return () => { alive = false; clearTimeout(timer); };
  }, [text, enabled]);
  const current = enabled && !!text && result.query === text;
  return {
    papers: current ? result.papers : [],
    total: current ? result.total : 0,
    error: current ? result.error : '',
    searching: enabled && !!text && (pending || !current),
  };
}
