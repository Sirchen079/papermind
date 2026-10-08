"""Local snapshots of web passages actually returned to the research agent."""
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlsplit
from app.agent.source_kinds import source_material_kind


def web_source(data, retrieved_by):
    url, text = data.get('url'), data.get('text')
    if not isinstance(url, str) or urlsplit(url).scheme not in {'http', 'https'}:
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    fetched = data.get('retrieved_at') or datetime.now(timezone.utc).isoformat()
    start = data.get('start_char', 0)
    end = start + len(text)
    identity = f'{url}\n{fetched}\n{start}\n{text}'
    return {'source_type': 'web', 'url': url, 'title': data.get('title') or url,
            'material_kind': source_material_kind({**data, 'source_type': 'web'}),
            'retrieved_at': fetched, 'start_char': start, 'end_char': end,
            'snapshot_id': data.get('snapshot_id') or hashlib.sha256(identity.encode()).hexdigest()[:24],
            'content_region': data.get('content_region', 'document'),
            'snippet': ' '.join(text.split())[:280], 'excerpt': text,
            'retrieved_by': retrieved_by,
            **({'carried_from_message': data['saved_message_id']} if isinstance(data.get('saved_message_id'), int) else {})}


def snapshot_result(source, message_id, source_index):
    """Read the stored excerpt only. Re-fetching is a separate, explicit tool."""
    return {key: source.get(key) for key in ('url', 'title', 'retrieved_at', 'snapshot_id', 'content_region')} | {
        'material_kind': source_material_kind(source),
        'type': 'web', 'saved_message_id': message_id, 'source_index': source_index,
        'original_start_char': source.get('start_char', 0),
        'note': '这是当时读取并保存的网页摘录，不代表网站当前内容；需要最新资料时可调用 read_webpage。'}
