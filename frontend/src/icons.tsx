/**
 * PaperMind 自绘图标集。
 *
 * 全部为手绘 SVG（viewBox 0 0 24 24，stroke 跟随 currentColor，圆角线帽），
 * 风格与 Logo 统一：细线、圆角、克制的实心点缀。不依赖任何第三方图标库。
 *
 * 统一从这里 `import { BookOpen, Logo } from "../icons"`，方便后续整体调风格。
 */
import type { ReactNode, SVGProps } from "react";

export type IconProps = Omit<SVGProps<SVGSVGElement>, "width" | "height"> & {
  size?: number | string;
  strokeWidth?: number;
};

/** 通用外壳：统一 viewBox / stroke / 线帽，默认对辅助技术隐藏。 */
function Svg({ size = 24, strokeWidth = 1.75, children, ...rest }: IconProps & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

// ─── 导航 ────────────────────────────────────────────────────────────

/** 论文库：展开的书，两页 + 书脊 + 页内文字横线。 */
export function BookOpen(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M3 5.5c3-1 6-1 9 .5v12.5c-3-1.5-6-1.5-9-.5Z" />
      <path d="M21 5.5c-3-1-6-1-9 .5v12.5c3-1.5 6-1.5 9-.5Z" />
      <path d="M6.5 9.5h2.8M6.5 12.5h2" opacity="0.55" />
      <path d="M14.7 9.5h2.8M15.5 12.5h2" opacity="0.55" />
    </Svg>
  );
}

/** 建议：灯泡，圆顶 + 螺纹底座，内部一道高光。 */
export function Lightbulb(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3a6 6 0 0 0-3.8 10.6c.7.6 1.3 1.5 1.5 2.4h4.6c.2-.9.8-1.8 1.5-2.4A6 6 0 0 0 12 3Z" />
      <path d="M8.5 17.5h7" />
      <path d="M9.5 20.5h5" />
      <path d="M12 6.4a3 3 0 0 0-2.6 1.5" opacity="0.55" />
    </Svg>
  );
}

/** 图谱：三节点网络（实心节点 + 连线）。比通用 share 更贴合知识网络。 */
export function Share2(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M7.5 7.6l2.7 8.8M16.5 7.6l-2.7 8.8M8 6.5h8" />
      <circle cx="6" cy="6.5" r="2.3" fill="currentColor" stroke="none" />
      <circle cx="18" cy="6.5" r="2.3" fill="currentColor" stroke="none" />
      <circle cx="12" cy="17.5" r="2.3" fill="currentColor" stroke="none" />
    </Svg>
  );
}

/** 对话：圆角气泡 + 左下尾巴 + 文字行。 */
export function MessageSquare(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-7.2L6 19.6V16a2 2 0 0 1-2-2Z" />
      <path d="M8 9h8M8 12h5" opacity="0.6" />
    </Svg>
  );
}

/** 技能：四宫格模块 + 中间连接线，表达"可拼装的能力"。 */
export function Blocks(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.8" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.8" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1.8" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1.8" />
      <path d="M10.5 7h3M7 10.5v3" opacity="0.55" />
    </Svg>
  );
}

/** 设置：三条水平滑块 + 圆钮（位置各异），比齿轮更克制精致。 */
export function Settings(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 7h6.8M17.2 7H20" />
      <circle cx="15" cy="7" r="2.2" />
      <path d="M4 12h2.8M11.2 12H20" />
      <circle cx="9" cy="12" r="2.2" />
      <path d="M4 17h7.8M17.7 17H20" />
      <circle cx="15.5" cy="17" r="2.2" />
    </Svg>
  );
}

// ─── 操作 / 状态 ─────────────────────────────────────────────────────

/** 刷新 / 扫描：开口圆弧 + 右上箭头头。 */
export function RotateCw(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M20.5 12a8.5 8.5 0 1 1-2.5-6" />
      <path d="M20.5 3.5v4.2h-4.2" />
    </Svg>
  );
}

/** 双向循环刷新。 */
export function RefreshCw(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M18.5 8A8 8 0 0 0 5.5 5.5L4 7" />
      <path d="M4 4v3.4h3.4" />
      <path d="M5.5 16A8 8 0 0 0 18.5 18.5L20 17" />
      <path d="M20 20v-3.4h-3.4" />
    </Svg>
  );
}

export function Check(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </Svg>
  );
}

export function X(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M6 6l12 12M18 6L6 18" />
    </Svg>
  );
}

export function Plus(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 5v14M5 12h14" />
    </Svg>
  );
}

/** 删除：垃圾桶 + 提手 + 桶身竖纹。 */
export function Trash2(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4.5 7h15" />
      <path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7" />
      <path d="M6.5 7l.8 12a1.5 1.5 0 0 0 1.5 1.4h6.4a1.5 1.5 0 0 0 1.5-1.4L17.5 7" />
      <path d="M10 11v6M14 11v6" opacity="0.6" />
    </Svg>
  );
}

/** 编辑：斜放铅笔 + 笔尖。 */
export function Pencil(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 20l1-4.2L16.5 4.3a2 2 0 0 1 2.8 0l.4.4a2 2 0 0 1 0 2.8L8.2 19l-4.2 1Z" />
      <path d="M14 6l4 4" />
    </Svg>
  );
}

/** 复制：前后两张纸。 */
export function Copy(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="8" y="8" width="11.5" height="11.5" rx="2" />
      <path d="M5.5 15.5H5A1.5 1.5 0 0 1 3.5 14V5A1.5 1.5 0 0 1 5 3.5h9A1.5 1.5 0 0 1 15.5 5v.5" />
    </Svg>
  );
}

/** 保存：软盘 + 标签窗。 */
export function Save(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M5 4.5h10.5L19.5 8.5V19a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5.5a1 1 0 0 1 1-1Z" />
      <path d="M8 4.5v4h6.5v-4" />
      <rect x="8" y="13" width="8" height="7" rx="0.6" opacity="0.8" />
    </Svg>
  );
}

/** 搜索：放大镜。 */
export function Search(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="10.5" cy="10.5" r="6" />
      <path d="M15 15l4.5 4.5" />
    </Svg>
  );
}

/** 筛选：漏斗。 */
export function Filter(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 5.5h16l-6.5 7.5v6L10.5 20.5v-7L4 5.5Z" />
    </Svg>
  );
}

/** 发送：纸飞机。 */
export function Send(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M21 4L3 11l6.5 2.2L12 20l9-16Z" />
      <path d="M9.5 13.2L20 4.5" opacity="0.6" />
    </Svg>
  );
}

/** 加载：开口圆弧，配合 className="animate-spin" 旋转。 */
export function Loader2(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3a9 9 0 1 0 9 9" />
    </Svg>
  );
}

/** 工具：扳手。表示一次工具调用。 */
export function Wrench(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M15.5 3.5a4.5 4.5 0 0 0-5.4 5.4l-6 6a2 2 0 0 0 2.8 2.8l6-6a4.5 4.5 0 0 0 5.4-5.4l-2.6 2.6-2.2-.5-.5-2.2 2.5-2.7Z" />
    </Svg>
  );
}

/** 警告：三角 + 感叹号。 */
export function AlertTriangle(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 4l8.5 15.5h-17L12 4Z" />
      <path d="M12 10v4.5" />
      <circle cx="12" cy="17.4" r="0.6" fill="currentColor" stroke="none" />
    </Svg>
  );
}

/** 收藏：五角星。 */
export function Star(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3.5l2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 17.6 6.6 20l1.2-6-4.5-4.2 6.1-.7L12 3.5Z" />
    </Svg>
  );
}

/** 提示：圆圈 + i。 */
export function Info(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5" />
      <circle cx="12" cy="7.8" r="0.6" fill="currentColor" stroke="none" />
    </Svg>
  );
}

/** 收件箱。 */
export function Inbox(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 13l3-8.5h10L20 13" />
      <path d="M4 13v5a1.5 1.5 0 0 0 1.5 1.5h13A1.5 1.5 0 0 0 20 18v-5" />
      <path d="M4 13h4l1.5 2.5h5L16 13h4" />
    </Svg>
  );
}

/** 文档：文件 + 文字行。 */
export function FileText(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M6 3.5h7L18 8.5V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z" />
      <path d="M13 3.5v5h5" />
      <path d="M8.5 13h7M8.5 16h7M8.5 19h4" opacity="0.7" />
    </Svg>
  );
}

/** 标签。 */
export function Tag(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12.8 3.5H5A1.5 1.5 0 0 0 3.5 5v7.8c0 .4.2.8.4 1.1l7.2 7.2a1.5 1.5 0 0 0 2.1 0l6.4-6.4a1.5 1.5 0 0 0 0-2.1l-7.2-7.2a1.5 1.5 0 0 0-1.1-.4Z" />
      <circle cx="8" cy="8" r="1.3" fill="currentColor" stroke="none" />
    </Svg>
  );
}

// ─── 主题 ────────────────────────────────────────────────────────────

/** 浅色模式：太阳，圆 + 八射线。 */
export function Sun(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="3.8" />
      <path d="M12 3.5v1.8M12 18.7v1.8M3.5 12h1.8M18.7 12h1.8" />
      <path d="M6 6l1.3 1.3M16.7 16.7L18 18M18 6l-1.3 1.3M7.3 16.7L6 18" />
    </Svg>
  );
}

/** 深色模式：弯月 + 一颗装饰星点。 */
export function Moon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5Z" />
      <path d="M18 4l.45 1.35L19.8 5.8l-1.35.45L18 7.6l-.45-1.35L16.2 5.8l1.35-.45L18 4Z" fill="currentColor" stroke="none" opacity="0.7" />
    </Svg>
  );
}

// ─── 布局 ────────────────────────────────────────────────────────────

/** 菜单：三横线。 */
export function Menu(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </Svg>
  );
}

export function ChevronRight(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M9.5 5l7 7-7 7" />
    </Svg>
  );
}

export function ChevronDown(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M5 9.5l7 7 7-7" />
    </Svg>
  );
}

/** 显示密码 / 可见：眼睛。 */
export function Eye(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M2.5 12S6 6.5 12 6.5s9.5 5.5 9.5 5.5-3.5 5.5-9.5 5.5S2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="2.8" />
    </Svg>
  );
}

/** 隐藏：眼睛 + 斜杠。 */
export function EyeOff(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 4l16 16" />
      <path d="M9.6 9.7a3 3 0 0 0 4.2 4.2" />
      <path d="M6.8 6.9C4.3 8.4 2.5 12 2.5 12s3.5 5.5 9.5 5.5c1.4 0 2.7-.3 3.8-.8" />
      <path d="M17.6 9.6C19.7 11 21.5 12 21.5 12s-1.5 2.3-3.9 3.8" opacity="0.7" />
    </Svg>
  );
}

// ─── 别名（避免与内置 / 其它名冲突） ──────────────────────────────────

/** 关联链接：两段链环。 */
export function LinkIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M9.5 14.5l5-5" opacity="0.6" />
      <path d="M11 6.6l1-1a4 4 0 0 1 5.6 5.6l-2 2a4 4 0 0 1-3.4 1.1" />
      <path d="M13 17.4l-1 1a4 4 0 0 1-5.6-5.6l2-2a4 4 0 0 1 3.4-1.1" />
    </Svg>
  );
}

/** 停止：实心圆角方块（停止生成按钮用）。 */
export function SquareIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="7" y="7" width="10" height="10" rx="1.8" fill="currentColor" stroke="none" />
    </Svg>
  );
}

// ─── 品牌 ────────────────────────────────────────────────────────────

/**
 * PaperMind 品牌标识——一本翻开的书 + 一个相连的节点（论文 + AI）。
 * 跟随 currentColor，所以在 accent 背景上自动反白。
 */
export function Logo({ size = 24, ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <path d="M5 4h11a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2V4Z" />
      <path d="M5 4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2" />
      <path d="M9 9h6" />
      <path d="M9 13h4" />
      <circle cx="18.5" cy="6.5" r="1.6" fill="currentColor" stroke="none" />
      <path d="M16.6 9.4l1.3-1.4" />
    </svg>
  );
}
