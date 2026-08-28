/**
 * 受控确认对话框。用 Promise 阻塞式询问，替代 window.confirm。
 *
 *   const confirm = useConfirm();
 *   const ok = await confirm({
 *     title: "删除论文？",
 *     message: "该操作不可撤销。",
 *     variant: "danger",
 *     confirmText: "删除",
 *   });
 *   if (ok) doDelete();
 *
 * 挂载：根（App 最外层）包 <ConfirmProvider>。
 * - Escape / 点遮罩 = 取消（resolve false）
 * - autoFocus 落在「取消」上，避免回车误触危险操作
 * - variant=danger 时左侧警示图标 + 确认键用 danger 色
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { AlertTriangle } from "../../icons";

interface ConfirmOptions {
  title?: string;
  message: ReactNode;
  confirmText?: string;
  cancelText?: string;
  variant?: "danger" | "default";
}

type ConfirmFn = (opts: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

interface PendingState {
  options: ConfirmOptions;
  resolve: (v: boolean) => void;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingState | null>(null);

  const confirm = useCallback<ConfirmFn>(
    (options) =>
      new Promise<boolean>((resolve) => {
        setPending({ options, resolve });
      }),
    [],
  );

  const close = useCallback((value: boolean) => {
    setPending((cur) => {
      cur?.resolve(value);
      return null;
    });
  }, []);

  // Escape = 取消
  useEffect(() => {
    if (!pending) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pending, close]);

  const isDanger = pending?.options.variant === "danger";

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && (
        <div
          className="modal-overlay animate-fade-in flex items-center justify-center p-6"
          onClick={() => close(false)}
        >
          <div
            role="alertdialog"
            aria-modal="true"
            aria-label={pending.options.title ?? "确认操作"}
            className="w-full max-w-sm animate-slide-up rounded-xl p-5"
            style={{ backgroundColor: "var(--surface)", boxShadow: "var(--shadow-lg)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              {isDanger && (
                <span
                  className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
                  style={{ backgroundColor: "var(--danger-soft)", color: "var(--danger)" }}
                >
                  <AlertTriangle size={16} />
                </span>
              )}
              <div className="flex-1">
                {pending.options.title && (
                  <h3 className="mb-1 text-base font-semibold">{pending.options.title}</h3>
                )}
                <div className="text-sm leading-relaxed text-muted">
                  {pending.options.message}
                </div>
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button className="btn-ghost" onClick={() => close(false)} autoFocus>
                {pending.options.cancelText ?? "取消"}
              </button>
              <button
                className="btn-primary"
                style={isDanger ? { backgroundColor: "var(--danger)" } : undefined}
                onClick={() => close(true)}
              >
                {pending.options.confirmText ?? "确认"}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm 必须在 <ConfirmProvider> 内使用");
  return ctx;
}
