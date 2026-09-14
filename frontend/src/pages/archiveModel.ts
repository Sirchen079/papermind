export type ArchiveTone = "success" | "danger";

export function restoreGuideStatusLabel(canRestore: boolean): string {
  return canRestore ? "可按指南恢复" : "不建议恢复";
}

export function restoreGuideTone(canRestore: boolean): ArchiveTone {
  return canRestore ? "success" : "danger";
}
