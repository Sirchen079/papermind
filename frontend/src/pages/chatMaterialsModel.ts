interface PageAttachment {
  kind: string; data_url: string;
  paper_page?: {paper_id: number; page: number; pdf_sha256: string; image_sha256: string}|null;
}

export function appendPageAttachment<T extends PageAttachment, S extends {attachments: T[]}>(previous: S, item: T): S {
  const page = item.paper_page;
  if (!page || item.kind !== 'image') throw new Error('没有可带入的原页图片');
  const duplicate = previous.attachments.some(a => a.kind === 'image' && a.paper_page?.paper_id === page.paper_id
    && a.paper_page.page === page.page && a.paper_page.pdf_sha256 === page.pdf_sha256
    && a.paper_page.image_sha256 === page.image_sha256 && a.data_url === item.data_url);
  if (duplicate) return previous;
  if (previous.attachments.length >= 4) throw new Error('本轮已有 4 个附件，请先移除一个再带入本页');
  return {...previous, attachments: [...previous.attachments, item]};
}
