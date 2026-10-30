import type { NavLocation } from '../pages/navigationModel';

export function SelectedPaperReviewActions({ paperIds, onNavigate }: {
  paperIds: number[]; onNavigate?: (target: NavLocation | string) => void;
}) {
  if (!paperIds.length || !onNavigate) return null;
  const open = (output: 'map' | 'review') => onNavigate({page: 'research', params: {
    mode: 'review', papers: paperIds.join(','), output,
  }});
  return <>
    <button className="btn-primary min-h-9 py-1 text-xs" disabled={paperIds.length > 1000} onClick={() => open('map')}>生成卡片与地图</button>
    <button className="btn-ghost min-h-9 py-1 text-xs" disabled={paperIds.length > 1000} onClick={() => open('review')}>整理为综述</button>
  </>;
}
