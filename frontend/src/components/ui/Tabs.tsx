/**
 * 受控 Tabs。Phase 5 拆 Library 详情 modal 时用。
 *
 *   <Tabs tabs={[{key:"overview",label:"概览"},...]} value={tab} onChange={setTab} />
 *
 * 无障碍：role=tablist/tab + aria-selected + 焦点环（tabindex roving）。
 * 当前项底部一条 accent 下划线；超出宽度横向滚动。
 */
import { type ReactNode } from "react";

export interface TabItem {
  key: string;
  label: ReactNode;
  /** 可选角标计数（>0 才显示），例如某 Tab 下的条目数。 */
  count?: number;
}

export function Tabs({
  tabs,
  value,
  onChange,
  className = "",
}: {
  tabs: TabItem[];
  value: string;
  onChange: (key: string) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      className={`flex items-center gap-1 overflow-x-auto border-b border-[var(--border)] ${className}`.trim()}
    >
      {tabs.map((t) => {
        const active = t.key === value;
        return (
          <button
            key={t.key}
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(t.key)}
            className="relative shrink-0 px-3.5 py-2.5 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2"
            style={{ color: active ? "var(--text)" : "var(--muted)", "--tw-ring-color": "var(--accent)" } as React.CSSProperties}
          >
            <span className="inline-flex items-center gap-1.5">
              {t.label}
              {t.count != null && t.count > 0 && (
                <span
                  className="rounded-full px-1.5 text-[11px] font-normal"
                  style={{ backgroundColor: "var(--surface-2)", color: "var(--faint)" }}
                >
                  {t.count}
                </span>
              )}
            </span>
            {active && (
              <span className="absolute inset-x-0 -bottom-px h-0.5 bg-[var(--accent)]" />
            )}
          </button>
        );
      })}
    </div>
  );
}
