"""Explicit local-server setup; the normal provider API still accepts remote services."""
import ipaddress
from urllib.parse import urlsplit, urlunsplit

import httpx


def is_loopback_url(url: str | None) -> bool:
    try:
        parts = urlsplit(url or '')
        if parts.scheme not in {'http', 'https'} or parts.username or parts.password:
            return False
        if (parts.hostname or '').lower().rstrip('.') == 'localhost':
            return True
        return ipaddress.ip_address(parts.hostname or '').is_loopback
    except ValueError:
        return False


def normalize_local_url(url: str) -> str:
    url = url.strip()
    if not is_loopback_url(url):
        raise ValueError('本机模型请使用 localhost、127.0.0.1 或 [::1] 地址。其他地址可在下方添加普通模型连接。')
    parts = urlsplit(url)
    _ = parts.port  # Reject malformed ports before making a request.
    if parts.query or parts.fragment:
        raise ValueError('请填写模型服务的基础地址，不包含查询参数或片段。')
    path = parts.path.rstrip('/')
    for suffix in ('/chat/completions', '/embeddings', '/models'):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            break
    return urlunsplit((parts.scheme, parts.netloc, path or '/v1', '', ''))


def discover(base_url: str, api_key: str | None = None) -> dict:
    base = normalize_local_url(base_url)
    headers = {'Authorization': 'Bearer '+api_key} if api_key else {}
    # A machine-local discovery must not be sent through an environment proxy.
    with httpx.Client(timeout=8, trust_env=False, follow_redirects=False) as client:
        response = client.get(base+'/models', headers=headers)
        response.raise_for_status()
        payload = response.json()
    raw = payload.get('data', payload.get('models', [])) if isinstance(payload, dict) else payload
    if not isinstance(raw, list) or (isinstance(payload, dict) and (payload.get('error') or not ({'data','models'} & payload.keys()))):
        raise ValueError('服务没有返回可识别的模型列表。')
    models = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        mid = item.get('id') or item.get('model') or item.get('name')
        if isinstance(mid, str) and mid.strip():
            models[mid] = {'id': mid, 'name': item.get('display_name') or mid}
    return {'base_url': base, 'models': list(models.values())}
