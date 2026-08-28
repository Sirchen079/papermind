export interface NoteForm {
  kind: string;
  content: string;
  tags: string;
}

export interface ExcerptForm {
  quote: string;
  page: string;
  section: string;
  locator: string;
  note: string;
  tags: string;
}

export interface MatrixSuggestionMergeResult<T extends string> {
  draft: Record<T, string>;
  applied: number;
  skipped: number;
}

export function splitTagInput(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function optionalText(value: string): string | null {
  const text = value.trim();
  return text || null;
}

function optionalPositiveInteger(value: string): number | null | undefined {
  const text = value.trim();
  if (!text) return null;
  const page = Number(text);
  if (!Number.isInteger(page) || page <= 0) return undefined;
  return page;
}

export function buildNotePayload(form: NoteForm): Record<string, unknown> | null {
  const content = form.content.trim();
  if (!content) return null;
  return {
    kind: form.kind,
    content,
    tags: splitTagInput(form.tags),
  };
}

export function buildExcerptPayload(form: ExcerptForm): Record<string, unknown> | null {
  const quote = form.quote.trim();
  if (!quote) return null;
  const page = optionalPositiveInteger(form.page);
  if (page === undefined) return null;
  return {
    quote,
    page,
    section: optionalText(form.section),
    locator: optionalText(form.locator),
    note: optionalText(form.note),
    tags: splitTagInput(form.tags),
  };
}

export function mergeMatrixSuggestion<T extends string>(
  current: Record<T, string>,
  suggestion: Record<string, unknown>,
  fields: readonly T[],
): MatrixSuggestionMergeResult<T> {
  const draft = { ...current };
  let applied = 0;
  let skipped = 0;

  for (const field of fields) {
    const value = suggestion[field];
    const text = value == null ? "" : String(value).trim();
    if (!text) continue;
    if (draft[field].trim()) {
      skipped += 1;
      continue;
    }
    draft[field] = text;
    applied += 1;
  }

  return { draft, applied, skipped };
}
