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
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
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
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLElement | null>(null);

  const confirm = useCallback<ConfirmFn>(
    (options) =>
      new Promise<boolean>((resolve) => {
        triggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        setPending({ options, resolve });
      }),
    [],
  );

  const close = useCallback((value: boolean) => {
    const trigger = triggerRef.current;
    setPending((cur) => {
      cur?.resolve(value);
      return null;
    });
    requestAnimationFrame(() => { if (trigger?.isConnected) trigger.focus(); });
  }, []);

  // Escape = 取消
  useEffect(() => {
    if (!pending) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing) return;
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopImmediatePropagation();
        close(false);
      }
      if (e.key === "Tab") {
        const buttons = dialogRef.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)');
        if (!buttons?.length) return;
        const first = buttons[0], last = buttons[buttons.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [pending, close]);

  const isDanger = pending?.options.variant === "danger";

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && createPortal(
        <div
          className="modal-overlay z-[100] animate-fade-in flex items-center justify-center p-6"
          onClick={() => close(false)}
        >
          <div
            ref={dialogRef}
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
        </div>, document.body
      )}
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm 必须在 <ConfirmProvider> 内使用");
  return ctx;
}
