export type PdfImportStatus = "queued" | "importing" | "done" | "failed";

export interface PdfImportFileLike {
  name: string;
  type?: string;
}

export interface PdfImportItem<TFile extends PdfImportFileLike = PdfImportFileLike> {
  id: string;
  name: string;
  file: TFile;
  status: PdfImportStatus;
  paperId: number | null;
  error: string | null;
}

export interface PdfImportPatch {
  status: PdfImportStatus;
  paperId?: number | null;
  error?: string | null;
}

function isPdf(file: PdfImportFileLike) {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

export function buildPdfImportQueue<TFile extends PdfImportFileLike>(
  files: Iterable<TFile>,
): PdfImportItem<TFile>[] {
  return Array.from(files).map((file, index) => {
    const valid = isPdf(file);
    return {
      id: `${index}-${file.name}`,
      name: file.name,
      file,
      status: valid ? "queued" : "failed",
      paperId: null,
      error: valid ? null : "只支持 PDF 文件",
    };
  });
}

export function nextQueuedPdf<TFile extends PdfImportFileLike>(
  queue: PdfImportItem<TFile>[],
): PdfImportItem<TFile> | null {
  return queue.find((item) => item.status === "queued") ?? null;
}

export function markPdfImportItem<TFile extends PdfImportFileLike>(
  queue: PdfImportItem<TFile>[],
  id: string,
  patch: PdfImportPatch,
): PdfImportItem<TFile>[] {
  return queue.map((item) =>
    item.id === id
      ? {
          ...item,
          status: patch.status,
          paperId: patch.paperId ?? item.paperId,
          error: patch.error ?? null,
        }
      : item,
  );
}
