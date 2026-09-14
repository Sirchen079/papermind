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

// 批量导入后默认打开的第一篇成功论文。
export function firstDonePdfItem<TFile extends PdfImportFileLike>(
  queue: PdfImportItem<TFile>[],
): PdfImportItem<TFile> | null {
  return queue.find((item) => item.status === "done" && item.paperId != null) ?? null;
}

export interface PdfImportSummary {
  done: number;
  failed: number;
  remaining: number;
}

// 结果概览：完成 / 失败 / 仍在队列或进行中。
export function summarizePdfImport<TFile extends PdfImportFileLike>(
  queue: PdfImportItem<TFile>[],
): PdfImportSummary {
  let done = 0;
  let failed = 0;
  let remaining = 0;
  for (const item of queue) {
    if (item.status === "done") done += 1;
    else if (item.status === "failed") failed += 1;
    else remaining += 1;
  }
  return { done, failed, remaining };
}
