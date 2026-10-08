"""Download one identified public PDF to disk, independent of chat attachments."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile
from urllib.parse import urljoin

import httpx
from app.security.url_guard import ensure_http_url


def check_cancelled(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise InterruptedError('已停止下载，未导入论文。')


@contextmanager
def download_pdf(url: str, data_dir: Path, cancelled=None):
    """Yield a closed temporary file and a compact receipt; clean up on all exits.

    Uses HTTPX streaming and the existing per-hop URL validation. No whole-file
    response buffer or chat attachment size limit. Parsing/format verification
    happens before the shared ingestion service modifies the library.
    """
    requested_url = ensure_http_url(url)
    cache = (data_dir / 'downloads').resolve()
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='paper-', dir=cache) as folder:
        Path(folder).resolve().relative_to(cache)
        path = Path(folder) / 'article.pdf'
        with httpx.Client(timeout=httpx.Timeout(60, connect=20), follow_redirects=False,
                          headers={'User-Agent': 'PaperMind research reader', 'Accept': 'application/pdf'}) as client:
            for _ in range(6):
                check_cancelled(cancelled)
                ensure_http_url(url)
                with client.stream('GET', url) as response:
                    if response.is_redirect:
                        location = response.headers.get('location')
                        if not location:
                            raise ValueError('PDF 跳转缺少目标网址。')
                        url = urljoin(url, location)
                        continue
                    response.raise_for_status()
                    digest = hashlib.sha256()
                    size = 0
                    head = bytearray()
                    with path.open('xb') as output:
                        for chunk in response.iter_bytes(chunk_size=64 * 1024):
                            check_cancelled(cancelled)
                            if not chunk:
                                continue
                            if len(head) < 1024:
                                head.extend(chunk[:1024-len(head)])
                                if len(head) >= 1024 and b'%PDF-' not in head:
                                    raise ValueError('链接未返回 PDF，可能是文章页面或登录页。请读取页面寻找正文 PDF 链接。')
                            output.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                    if b'%PDF-' not in head:
                        raise ValueError('链接未返回有效 PDF。')
                    check_cancelled(cancelled)
                    receipt = {'requested_url': requested_url, 'url': str(response.url),
                               'retrieved_at': datetime.now(timezone.utc).isoformat(),
                               'bytes': size, 'sha256': digest.hexdigest(),
                               'content_type': response.headers.get('content-type', '')}
                    break
            else:
                raise ValueError('PDF 跳转次数过多。')
        yield path, receipt
