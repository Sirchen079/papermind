export type BulkOrganizationTargetType = "tag" | "collection";

export interface BulkOrganizationPayload {
  paperIds: number[];
  targetId: number;
}

export function replaceBulkPaperSelection(paperIds: number[]): number[] {
  const seen = new Set<number>();
  const next: number[] = [];
  for (const id of paperIds) {
    if (!Number.isInteger(id) || id <= 0 || seen.has(id)) continue;
    seen.add(id);
    next.push(id);
  }
  return next;
}

export function toggleBulkPaperSelection(selectedPaperIds: number[], paperId: number): number[] {
  if (!Number.isInteger(paperId) || paperId <= 0) return selectedPaperIds;
  if (selectedPaperIds.includes(paperId)) {
    return selectedPaperIds.filter((id) => id !== paperId);
  }
  return [...selectedPaperIds, paperId];
}

export function buildBulkOrganizationPayload(
  selectedPaperIds: number[],
  rawTargetId: string,
): BulkOrganizationPayload | null {
  const paperIds = replaceBulkPaperSelection(selectedPaperIds);
  const targetId = Number(rawTargetId);
  if (paperIds.length === 0 || !Number.isInteger(targetId) || targetId <= 0) return null;
  return { paperIds, targetId };
}
