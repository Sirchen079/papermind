"""Pack Markdown blocks; split long tables by rows with repeated headers."""
import re
from app.rag.chunker import chunk_text


def chunk_markdown(text, target=1000):
    lines = text.splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        first = lines[i].strip()
        start = i
        if first.startswith('|'):
            while i < len(lines) and lines[i].lstrip().startswith('|'):
                i += 1
        elif first.startswith(('```', '~~~')) or first == '$$' or first == r'\[':
            end = first[:3] if first.startswith(('```', '~~~')) else '$$' if first == '$$' else r'\]'
            i += 1
            while i < len(lines):
                last = lines[i].strip()
                i += 1
                if last.startswith(end):
                    break
        else:
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith(('|', '#', '```', '~~~', '$$')):
                i += 1
        blocks.append('\n'.join(lines[start:i]))
    pieces = []
    for n, block in enumerate(blocks):
        rows = block.splitlines()
        if len(rows) > 2 and rows[0].lstrip().startswith('|') and re.fullmatch(r'[\s|:\-]+', rows[1]):
            header = '\n'.join(rows[:2])
            caption = blocks[n - 1] if n and re.match(r'(?i)^(table\s+\d|表\s*\d)', blocks[n - 1]) else ''
            prefix = '\n\n'.join(x for x in (caption, header) if x)
            part = prefix
            for row in rows[2:]:
                if len(part) + len(row) + 1 > target and part != prefix:
                    pieces.append(part)
                    part = prefix
                part += '\n' + row
            pieces.append(part)
        elif len(block) > target and not block.lstrip().startswith(('|', '```', '~~~', '$$', r'\[')):
            pieces.extend(chunk_text(block, target=target))
        else:
            pieces.append(block)
    out = []
    buf = ''
    for block in pieces:
        if buf and len(buf) + len(block) + 2 > target:
            out.append(buf)
            buf = ''
        buf = '\n\n'.join(x for x in (buf, block) if x)
    if buf:
        out.append(buf)
    return out
