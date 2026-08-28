export type ThesisLinkTargetType = "project" | "chapter";

export interface ThesisLinkForm {
  target_type: ThesisLinkTargetType;
  project_id: string;
  chapter_id: string;
  role: string;
  note: string;
}

export function buildThesisLinkPayload(form: ThesisLinkForm): Record<string, unknown> | null {
  const role = form.role || "related";
  const note = form.note.trim();
  if (form.target_type === "chapter") {
    if (!form.chapter_id) return null;
    return {
      chapter_id: Number(form.chapter_id),
      role,
      ...(note ? { note } : {}),
    };
  }
  if (!form.project_id) return null;
  return {
    project_id: Number(form.project_id),
    role,
    ...(note ? { note } : {}),
  };
}
