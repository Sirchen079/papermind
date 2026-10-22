"""Browser-context PDF transfer for authenticated PDF viewers.

The browser fetch pattern follows nature-downloader's browser transfer workflow;
this bounded adapter does not export cookies or create a second login context.
"""
SOURCE = r'''
import base64
from urllib.parse import urlsplit

def fetch_in_browser(page, url):
    if page is None or urlsplit(url).scheme != 'https':
        return None, url
    # Fetch only the PDF origin the visible page has already reached.
    if urlsplit(url).netloc != urlsplit(page.url).netloc:
        return None, url
    try:
        # APIRequestContext shares this browser's cookie jar; the PDF plugin
        # itself can have no usable JavaScript execution context.
        response = page.context.request.get(url, timeout=90000)
        if response.ok and int(response.headers.get('content-length', '0')) <= 104857600:
            content = response.body()
            if content.startswith(b'%PDF-') and len(content) <= 104857600:
                return content, url
    except Exception:
        pass
    if urlsplit(page.url).path.lower().endswith('.pdf'):
        return None, url
    try:
        meta = page.evaluate(r''' + '"""' + r'''
            async (url) => {
                const response = await fetch(url, {credentials:'include', signal:AbortSignal.timeout(90000)});
                if (!response.ok || !response.body) return {ok:false};
                const reader = response.body.getReader(), chunks = [];
                let size = 0;
                for (;;) {
                    const {done, value} = await reader.read();
                    if (done) break;
                    size += value.length;
                    if (size > 104857600) { await reader.cancel(); return {ok:false}; }
                    chunks.push(value);
                }
                const bytes = new Uint8Array(size);
                let offset = 0;
                for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
                if (String.fromCharCode(...bytes.slice(0,5)) !== '%PDF-') return {ok:false};
                window.__paperMindPdf = bytes;
                return {ok:true, size};
            }
        ''' + '"""' + r''', url)
        if not meta.get('ok') or not 0 < meta.get('size', 0) <= 104857600:
            return None, url
        content = bytearray()
        for offset in range(0, meta['size'], 262144):
            encoded = page.evaluate(r''' + '"""' + r'''
                offset => {
                    const bytes = window.__paperMindPdf.slice(offset, offset+262144);
                    let text = '';
                    for (let i=0; i<bytes.length; i+=8192) text += String.fromCharCode(...bytes.slice(i,i+8192));
                    return btoa(text);
                }
            ''' + '"""' + r''', offset)
            content.extend(base64.b64decode(encoded, validate=True))
        if len(content) == meta['size'] and content.startswith(b'%PDF-'):
            return bytes(content), url
    except Exception:
        return None, url
    finally:
        try:
            page.evaluate('() => { delete window.__paperMindPdf; }')
        except Exception:
            pass
    return None, url
'''
