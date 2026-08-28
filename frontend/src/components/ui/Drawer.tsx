/**
 * 右侧抽屉。承载低频的批量入口（如论文导入），不占首屏。
 *
 *   <Drawer open={open} onClose={()=>setOpen(false)} title="导入论文">
 *     {children}
 *   </Drawer>
 *
 * - 右侧 fixed 面板，遮罩复用 .modal-overlay
 * - Escape / 点遮罩 = onClose
 * - 内部 flex 列：shrink-0 标题栏 + flex-1 独立滚动内容
 * - open=false 时不渲染（卸载子树）
 */
import { useEffect, type ReactNode } from "react";
import { X } from "../../icons";

export function Drawer({
  open,
  onClose,
  title,
  children,
  width = "max-w-lg",
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  /** 抽屉最大宽度，Tailwind max-w-* 类。默认 max-w-lg (32rem)。 */
  width?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="modal-overlay animate-fade-in flex justify-end" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : "侧边抽屉"}
        className={`flex h-full w-full ${width} animate-drawer-in flex-col bg-[var(--surface)]`}
        style={{ boxShadow: "var(--shadow-lg)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {title && (
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-[var(--border)] px-5 py-4">
            <h3 className="text-base font-semibold">{title}</h3>
            <button onClick={onClose} className="btn-ghost p-1.5" aria-label="关闭抽屉">
              <X size={16} />
            </button>
          </div>
        )}
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </div>
  );
}
