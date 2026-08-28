/**
 * 空状态 / 零数据占位。图示 + 标题 + 说明 + 可选行动按钮，居中布局。
 *
 *   <EmptyState icon={<BookOpen/>} title="论文库还是空的"
 *      hint="导入你的第一篇论文开始管理"
 *      action={<button onClick={...}>导入论文</button>} />
 */
import { type ReactNode } from "react";

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
      className={`flex flex-col items-center justify-center px-6 py-12 text-center ${className}`.trim()}
    >
      {icon && (
        <div
          className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl"
          style={{ backgroundColor: "var(--surface-2)", color: "var(--faint)" }}
          aria-hidden="true"
        >
          {icon}
        </div>
      )}
      <div className="text-sm font-medium text-[var(--text)]">{title}</div>
      {hint && <div className="mt-1 max-w-sm text-sm text-faint">{hint}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
