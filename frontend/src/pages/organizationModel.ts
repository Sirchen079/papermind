export interface TagForm {
  name: string;
  color: string;
}

export interface CollectionForm {
  name: string;
  description: string;
}

export type OrganizationFilter = "all" | `tag:${number}` | `collection:${number}`;

export interface OrganizationPaperLike {
  tags?: { id: number; name: string; color: string | null }[];
  collections?: { id: number; name: string }[];
}

function optionalText(value: string): string | null {
  const text = value.trim();
  return text || null;
}

export function buildTagPayload(form: TagForm): { name: string; color: string | null } | null {
  const name = form.name.trim();
  if (!name) return null;
  return { name, color: optionalText(form.color) };
}

export function buildCollectionPayload(
  form: CollectionForm,
): { name: string; description: string | null } | null {
  const name = form.name.trim();
  if (!name) return null;
  return { name, description: optionalText(form.description) };
}

export function matchesOrganizationFilter(
  paper: OrganizationPaperLike,
  filter: OrganizationFilter,
): boolean {
  if (filter === "all") return true;
  const [kind, rawId] = filter.split(":");
  const id = Number(rawId);
  if (kind === "tag") return (paper.tags ?? []).some((tag) => tag.id === id);
  if (kind === "collection") {
    return (paper.collections ?? []).some((collection) => collection.id === id);
  }
  return true;
}
