/**
 * 全局 Toast 通知。
 *
 * 用法：
 *   const toast = useToast();
 *   toast.success("保存成功");
 *   toast.error("导入失败");
 *
 * 挂载：在根（App 最外层）包一层 <ToastProvider>，视图由 Provider 自动渲染，
 * 无需单独放 <Toaster/>（避免忘挂）。
 *
 * - 位置：右下角，窄屏自适应宽度。
 * - 自动消失：success/info 3.5s、warn 4.5s、error 6s；可在第二个参数覆盖。
 * - 手动关闭：每条右侧 X 按钮。
 * - 无障碍：region + aria-live=polite；进出场用 .animate-slide-up，
 *   prefers-reduced-motion 下由全局 CSS 自动禁用动画。
 */
import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AlertTriangle, Check, Info, X } from "../../icons";

type ToastVariant = "success" | "error" | "warn" | "info";

interface ToastItem {
  id: number;
  variant: ToastVariant;
  message: string;
}

interface ToastOptions {
  duration?: number;
}

interface ToastApi {
  success: (msg: string, opts?: ToastOptions) => void;
  error: (msg: string, opts?: ToastOptions) => void;
  warn: (msg: string, opts?: ToastOptions) => void;
  info: (msg: string, opts?: ToastOptions) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const DEFAULT_DURATION: Record<ToastVariant, number> = {
  success: 3500,
  info: 3500,
  warn: 4500,
  error: 6000,
};

const ICONS: Record<ToastVariant, (p: { size?: number }) => ReactNode> = {
  success: Check,
  error: X,
  warn: AlertTriangle,
  info: Info,
};

const ACCENT: Record<ToastVariant, string> = {
  success: "var(--success)",
  error: "var(--danger)",
  warn: "var(--warning)",
  info: "var(--info)",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);

  const dismiss = useCallback((id: number) => {
    setItems((cur) => cur.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (variant: ToastVariant, message: string, opts?: ToastOptions) => {
      const id = ++seq.current;
      setItems((cur) => [...cur, { id, variant, message }]);
      const duration = opts?.duration ?? DEFAULT_DURATION[variant];
      window.setTimeout(() => dismiss(id), duration);
    },
    [dismiss],
  );

  const api: ToastApi = {
    success: (m, o) => push("success", m, o),
    error: (m, o) => push("error", m, o),
    warn: (m, o) => push("warn", m, o),
    info: (m, o) => push("info", m, o),
  };

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastView items={items} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast 必须在 <ToastProvider> 内使用");
  return ctx;
}

function ToastView({ items, onDismiss }: { items: ToastItem[]; onDismiss: (id: number) => void }) {
  if (items.length === 0) return null;
  return (
    <div
      className="fixed bottom-4 right-4 z-50 flex w-[calc(100vw-2rem)] max-w-sm flex-col gap-2"
      role="region"
      aria-label="通知"
      aria-live="polite"
    >
      {items.map((t) => {
        const Icon = ICONS[t.variant];
        const color = ACCENT[t.variant];
        return (
          <div
            key={t.id}
            className="card-tight animate-slide-up flex items-start gap-2.5 !p-3"
            style={{ borderLeft: `3px solid ${color}`, boxShadow: "var(--shadow-lg)" }}
          >
            <span className="mt-0.5 shrink-0" style={{ color }}>
              <Icon size={16} />
            </span>
            <div className="flex-1 text-sm leading-snug">{t.message}</div>
            <button
              type="button"
              onClick={() => onDismiss(t.id)}
              className="-mr-1 shrink-0 rounded p-0.5 opacity-60 transition-opacity hover:opacity-100 text-faint"
              aria-label="关闭通知"
              
            >
              <X size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
