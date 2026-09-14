/**
 * 空状态 / 零数据占位。图示 + 标题 + 说明 + 可选行动按钮，居中布局。
 *
 *   <EmptyState icon={<BookOpen/>} title="论文库还是空的"
 *      hint="导入你的第一篇论文开始管理"
 *      action={<button onClick={...}>导入论文</button>} />
 */
import { type ReactNode } from "react";
import { ResearchMotif } from './ResearchMotif';

export function EmptyState({
  icon,
  title,
  hint,
  action,
  className = "",
}: {
  icon?: ReactNode;
  title: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`research-empty flex flex-col items-center justify-center px-6 py-12 text-center ${className}`.trim()}
    >
      <ResearchMotif icon={icon}/>
      <div className="empty-title font-medium text-[var(--text)]">{title}</div>
      {hint && <div className="empty-hint mt-2 max-w-sm text-sm text-muted">{hint}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
