"""Provide complete selected paper texts when the existing chat budget permits."""
from __future__ import annotations

import hashlib
from collections.abc import Callable

from app.agent.source_passages import paper_source, text_pages
from app.models import Paper


def selected_ids(request: dict) -> list[int]:
    ids = request.get('paper_ids')
    if ids is None and request.get('paper_id') is not None:
        ids = [request['paper_id']]
    return list(dict.fromkeys(ids or []))


def _block(ids: list[int], texts: dict[int, tuple[str, str, str]]) -> str:
    if not texts:
        return ''
    included = '、'.join(f'P{pid}' for pid in texts)
    deferred = [pid for pid in ids if pid not in texts]
    header = ('[用户选定论文的完整入库正文]\n'
              f'本轮完整提供：{included}。正文与上面的用户笔记、AI分析分别使用，原页标记保持。')
    if deferred:
        header += ('\n本轮未自动附入全文：' + '、'.join(f'P{pid}' for pid in deferred)
                   + '；可用 get_paper_full_text 按章节、页码或字符位置继续读取。')
    bodies = [f'[P{pid}] 原文全文：{title}\n'
              f'<!-- selected-paper:{pid} sha256:{digest} -->\n{text}\n'
              f'<!-- /selected-paper:{pid} sha256:{digest} -->'
              for pid, (title, text, digest) in texts.items()]
    return header + '\n\n' + '\n\n'.join(bodies)


def collect_selected_texts(session, request: dict, fits: Callable[[str], bool], message_id: int):
    """Keep each admitted text whole; defer others to existing navigation tools.

    A highlighted passage or an attached saved work has its own narrow focus.
    The caller budgets actual projected messages, tools and response space.
    This does not retrieve, parse, OCR, rewrite or judge any paper.
    """
    ids = selected_ids(request)
    if not ids or (request.get('selected_text') or '').strip() or any(
            a.get('saved_document') or a.get('research_task') for a in request.get('attachments', [])):
        return '', {}, []
    texts: dict[int, tuple[str, str, str]] = {}
    for pid in ids:
        paper = session.get(Paper, pid)
        if paper is None or paper.is_deleted or not (paper.full_text or '').strip():
            continue
        candidate = {**texts, pid: (paper.title or f'#{pid}', paper.full_text,
                                  hashlib.sha256(paper.full_text.encode()).hexdigest())}
        if fits(_block(ids, candidate)):
            texts = candidate
    sources = []
    for pid, (title, text, digest) in texts.items():
        # Reuse bounded source excerpts without losing the remainder of the
        # supplied text. Every range stays addressable in the saved chat sources.
        for start in range(0, len(text), 12000):
            end = min(start + 12000, len(text))
            source = paper_source(pid, title, text[start:end], 'full_text',
                                  'selected_full_text', text_pages(text, start, end))
            source.update(start_char=start, end_char=end, total_chars=len(text),
                          provided_message_id=message_id, full_text_sha256=digest)
            sources.append(source)
    return _block(ids, texts), {pid: text for pid, (_, text, _) in texts.items()}, sources
