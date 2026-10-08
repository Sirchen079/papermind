"""Coalesce identical automatic material without summarizing research history."""
import hashlib
import re


_SELECTED_TEXT = re.compile(
    r'<!-- selected-paper:(\d+) sha256:([0-9a-f]{64}) -->\n(.*?)\n'
    r'<!-- /selected-paper:\1 sha256:\2 -->', re.DOTALL)


def _parts(body):
    """Keep an admitted whole paper atomic, including short result paragraphs."""
    parts, start = [], 0
    for match in _SELECTED_TEXT.finditer(body):
        if hashlib.sha256(match[3].encode()).hexdigest() != match[2]:
            continue
        parts.extend(body[start:match.start()].split('\n\n'))
        parts.append(match[0])
        start = match.end()
    parts.extend(body[start:].split('\n\n'))
    return parts


def coalesce_snapshots(snapshots: list[tuple[int, str]]) -> dict[int, str]:
    """Keep long, byte-identical paragraphs in the newest supplied snapshot.

    Callers exclude user-authored documents and attachments. Changed paragraphs
    remain verbatim, even when almost identical: numbers and conditions matter.
    Stored snapshots are never modified. Short headings stay beside their text.
    """
    owners: dict[str, int] = {}
    result = {}
    referenced = set()
    for message_id, body in reversed(snapshots):
        parts = []
        previous_owner = None
        for paragraph in _parts(body):
            owner = owners.get(paragraph) if len(paragraph) >= 160 else None
            if owner is not None and owner != message_id:
                referenced.add(owner)
                if owner != previous_owner:
                    parts.append(f'[完全相同的材料已合并至消息 #{owner} 的材料快照，见下文。]')
                previous_owner = owner
            else:
                parts.append(paragraph)
                previous_owner = None
                if len(paragraph) >= 160:
                    owners.setdefault(paragraph, message_id)
        result[message_id] = '\n\n'.join(parts)
    for message_id in referenced:
        result[message_id] = f'[消息 #{message_id} 的材料快照]\n' + result[message_id]
    return result
