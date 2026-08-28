export interface ProjectDeleteLike {
  id: number;
  children: unknown[];
  chapters: unknown[];
}

export interface ChapterDeleteLike {
  id: number;
  children: unknown[];
}

export interface LinkedPaperLike {
  links: {
    project_id: number | null;
    chapter_id: number | null;
  }[];
}

export type ThesisMarkdownExportScope = "project" | "chapter";
export type ThesisMarkdownExportTarget = { project_id: number } | { chapter_id: number };

function positiveId(id: number | null): number | null {
  return Number.isInteger(id) && id != null && id > 0 ? id : null;
}

export function collectLinkedThesisTargetIds(papers: LinkedPaperLike[]) {
  const projectIds = new Set<number>();
  const chapterIds = new Set<number>();
  for (const paper of papers) {
    for (const link of paper.links) {
      if (link.project_id != null) projectIds.add(link.project_id);
      if (link.chapter_id != null) chapterIds.add(link.chapter_id);
    }
  }
  return { projectIds, chapterIds };
}

export function projectDeleteBlockReason(
  project: ProjectDeleteLike,
  linkedProjectIds: Set<number>,
): string | null {
  if (project.children.length > 0) return "项目下还有子项目";
  if (project.chapters.length > 0) return "项目下还有章节";
  if (linkedProjectIds.has(project.id)) return "项目下还有论文链接";
  return null;
}

export function chapterDeleteBlockReason(
  chapter: ChapterDeleteLike,
  linkedChapterIds: Set<number>,
): string | null {
  if (chapter.children.length > 0) return "章节下还有子章节";
  if (linkedChapterIds.has(chapter.id)) return "章节下还有论文链接";
  return null;
}

export function buildThesisMarkdownExportTarget(
  scope: ThesisMarkdownExportScope,
  selectedProjectId: number | null,
  selectedChapterId: number | null,
): ThesisMarkdownExportTarget | null {
  if (scope === "project") {
    const id = positiveId(selectedProjectId);
    return id == null ? null : { project_id: id };
  }
  const id = positiveId(selectedChapterId);
  return id == null ? null : { chapter_id: id };
}
