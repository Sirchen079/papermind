/**
 * 加载占位骨架。用 P0 的 .skeleton 类（pulse 动画，reduced-motion 下自动停）。
 *
 *   <Skeleton variant="card" />
 *   <SkeletonGroup variant="row" count={5} />
 */
import { type CSSProperties } from "react";

type SkeletonVariant = "card" | "row" | "text";

const SIZES: Record<SkeletonVariant, string> = {
  card: "h-24 w-full rounded-xl",
  row: "h-12 w-full rounded-lg",
  text: "h-4 w-full rounded",
};

export function Skeleton({
  variant = "text",
  className = "",
  style,
}: {
  variant?: SkeletonVariant;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div
      className={`skeleton ${SIZES[variant]} ${className}`.trim()}
      style={style}
      aria-hidden="true"
    />
  );
}

export function SkeletonGroup({
  variant = "row",
  count = 3,
  className = "",
}: {
  variant?: SkeletonVariant;
  count?: number;
  className?: string;
}) {
  return (
    <div className="space-y-2" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} variant={variant} className={className} />
      ))}
    </div>
  );
}
