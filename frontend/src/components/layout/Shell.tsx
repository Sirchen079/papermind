/**
 * 内容壳：统一页面最大宽度与横向 padding，并 mx-auto 居中。
 * 这是解决「内容靠左」问题的根——所有页面用 Shell 包裹，宽度档统一。
 *
 *   <Shell max="wide">    max-w-[1400px]，工作台（Library / Graph）
 *   <Shell max="narrow">  max-w-[1100px]，单列阅读（Suggestions / Skills / Settings）
 *   <Shell max="fluid">   不限宽，仅统一 padding（Chat / App main）
 */
import { type ReactNode } from "react";

const MAXW = {
  wide: "max-w-[1400px]",
  narrow: "max-w-[1100px]",
  fluid: "max-w-none",
} as const;

export function Shell({
  max = "wide",
  className = "",
  children,
}: {
  max?: keyof typeof MAXW;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={`mx-auto w-full px-4 sm:px-6 lg:px-10 ${MAXW[max]} ${className}`.trim()}>
      {children}
    </div>
  );
}
