/**
 * 页面标题区。标题 + 描述 + 右侧操作插槽 + 可选横向统计带。
 *
 *   <PageHeader title="论文库" subtitle="..." actions={<button/>} stats={[{label,value}]} />
 *
 * 标题用 .page-title / .page-subtitle；统计带用 Stat 组件，2/4 列响应式。
 */
import { type ReactNode } from "react";
import { Stat, type StatItem } from "./Stat";

export function PageHeader({
  title,
  subtitle,
  actions,
  stats,
  className = "",
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  stats?: StatItem[];
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="page-title">{title}</h1>
          {subtitle && <p className="page-subtitle mt-0.5">{subtitle}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {stats && stats.length > 0 && (
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {stats.map((s, i) => (
            <Stat key={i} label={s.label} value={s.value} accent={s.accent} />
          ))}
        </div>
      )}
    </div>
  );
}
