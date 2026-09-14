/**
 * 单个统计数字卡。用 .stat-card 类。
 *
 *   <Stat label="论文总数" value={42} />
 *   <Stat label="待读" value={8} accent="var(--accent)" />
 */
import { type ReactNode } from "react";

export function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: ReactNode;
  /** CSS 颜色值，作为左色条（如 "var(--accent)"）。不传则无色条。 */
  accent?: string;
}) {
  return (
    <div className="stat-card relative overflow-hidden">
      {accent && (
        <span
          className="absolute inset-y-0 left-0 w-1"
          style={{ backgroundColor: accent }}
          aria-hidden="true"
        />
      )}
      <div className={`text-2xl font-bold leading-tight tracking-tight ${accent ? "pl-2.5" : ""}`}>
        {value}
      </div>
      <div className={`mt-0.5 text-xs text-faint ${accent ? "pl-2.5" : ""}`}>{label}</div>
    </div>
  );
}

export interface StatItem {
  label: string;
  value: ReactNode;
  accent?: string;
}
