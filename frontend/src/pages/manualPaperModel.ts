export interface ManualPaperForm {
  citation_key: string;
  title: string;
  authors: string;
  year: string;
  venue: string;
  doi: string;
  arxiv_id: string;
  abstract: string;
}

function optionalText(value: string): string | null {
  const text = value.trim();
  return text || null;
}

function optionalYear(value: string): number | null | undefined {
  const text = value.trim();
  if (!text) return null;
  const year = Number(text);
  if (!Number.isInteger(year) || year < 0) return undefined;
  return year;
}

export function emptyManualPaperForm(): ManualPaperForm {
  return {
    citation_key: "",
    title: "",
    authors: "",
    year: "",
    venue: "",
    doi: "",
    arxiv_id: "",
    abstract: "",
  };
}

export function buildManualPaperPayload(form: ManualPaperForm): Record<string, unknown> | null {
  const title = form.title.trim();
  if (!title) return null;
  const year = optionalYear(form.year);
  if (year === undefined) return null;
  return {
    citation_key: optionalText(form.citation_key),
    title,
    authors: form.authors
      .split(/\r?\n/)
      .map((author) => author.trim())
      .filter(Boolean),
    year,
    venue: optionalText(form.venue),
    doi: optionalText(form.doi),
    arxiv_id: optionalText(form.arxiv_id),
    abstract: optionalText(form.abstract),
  };
}
