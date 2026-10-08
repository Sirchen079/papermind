"""Optional external advanced parse engine (layout OCR such as Surya/MinerU).

PaperSpark reference (design only, CC BY-NC): one main app plus optional
parse engines behind a uniform job protocol, engine-agnostic caching. Here a
minimal three-phase HTTP protocol is defined by PaperMind itself so any
conforming local or cloud service can be plugged in; nothing from PaperSpark
is copied. The engine handles whole documents (layout, tables, scanned
pages) that native text extraction handles poorly.

Protocol (documented for engine implementers):
- ``POST {url}/jobs``       multipart field ``file`` = the PDF
  -> ``200 {"job_id": "..."}``
- ``GET {url}/jobs/{id}``   -> ``{"status": "queued"|"running"|"done"|"error",
                                "error"?: str,
                                "pages": [{"page": 1, "markdown": "..."}]}``
  ``pages`` is present once ``done`` and must cover every PDF page exactly
  once, 1-based.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import httpx

from app.models import Setting

_log = logging.getLogger(__name__)

SETTING_URL = 'advanced_parser_url'
DEFAULT_TIMEOUT_SECONDS = 20 * 60
POLL_INTERVAL = 2.0
CONNECT_TIMEOUT = 10


class AdvancedParseError(RuntimeError):
    """Engine-side failure with a user-presentable message."""


def configured_url(session) -> str | None:
    row = session.get(Setting, SETTING_URL)
    url = (row.value or '').strip() if row else ''
    return url or None


def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(60, connect=CONNECT_TIMEOUT), follow_redirects=True)


def parse_document(path: Path, url: str, *, should_continue=None,
                   timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict[int, str]:
    """Submit the whole PDF and poll until done.

    Returns ``{page_number: markdown}``. ``should_continue`` is polled between
    engine polls; when it returns False the run was cancelled or obsoleted and
    ``None`` is returned instead of a result.
    """
    from app.security.url_guard import ensure_http_url

    try:
        base = str(ensure_http_url(url)).rstrip('/')
    except Exception as exc:
        raise AdvancedParseError('高级解析引擎地址无效，请在设置中检查。') from exc
    deadline = time.monotonic() + timeout
    try:
        with path.open('rb') as handle:
            with _client() as client:
                response = client.post(f'{base}/jobs', files={'file': (path.name, handle, 'application/pdf')})
        if response.status_code != 200:
            raise AdvancedParseError(f'高级解析引擎拒绝任务（HTTP {response.status_code}）。')
        job = response.json()
        job_id = job.get('job_id')
        if not isinstance(job_id, str) or not job_id:
            raise AdvancedParseError('高级解析引擎未返回任务编号。')
        while True:
            if should_continue is not None and not should_continue():
                return None
            if time.monotonic() > deadline:
                raise AdvancedParseError('高级解析引擎处理超时，请检查引擎状态或稍后重试。')
            time.sleep(POLL_INTERVAL)
            if should_continue is not None and not should_continue():
                return None
            with _client() as client:
                response = client.get(f'{base}/jobs/{job_id}')
            if response.status_code != 200:
                raise AdvancedParseError(f'查询解析进度失败（HTTP {response.status_code}）。')
            state = response.json()
            status = state.get('status')
            if status == 'error':
                raise AdvancedParseError('高级解析引擎报告失败，请检查引擎日志或改用其他转换方式。')
            if status == 'done':
                return _pages(state)
    except AdvancedParseError:
        raise
    except httpx.HTTPError as exc:
        raise AdvancedParseError('无法连接高级解析引擎，请确认引擎正在运行且地址正确。') from exc
    except ValueError as exc:
        raise AdvancedParseError('高级解析引擎返回了无法解析的结果。') from exc


def _pages(state: dict) -> dict[int, str]:
    pages = state.get('pages')
    if not isinstance(pages, list) or not pages:
        raise AdvancedParseError('高级解析引擎没有返回页面结果。')
    result: dict[int, str] = {}
    for item in pages:
        if not isinstance(item, dict):
            raise AdvancedParseError('高级解析引擎返回的页面格式不正确。')
        number = item.get('page')
        markdown = item.get('markdown')
        if not isinstance(number, int) or isinstance(number, bool) or not isinstance(markdown, str):
            raise AdvancedParseError('高级解析引擎返回的页面格式不正确。')
        if number in result:
            raise AdvancedParseError('高级解析引擎返回了重复页码。')
        # Page markers are added by PaperMind itself on publish; strip engine
        # ones and any hallucinated image links, mirroring OCR postprocessing.
        markdown = markdown.replace('<!-- page:', '&lt;!-- page:')
        markdown = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', markdown).strip()
        if not markdown:
            markdown = '[空白页]'
        result[number] = markdown
    return result
