"""Versioned researcher corrections, kept separate from generated card inputs."""
import json
import re

from sqlmodel import select
from app.models import Paper
from app.models.base import utcnow, utc_iso
from app.models.card import PaperCard
from app.models.review import ReviewPaper
from app.reviews.service import digest

LABELS = {'problem': '问题', 'mechanism': '机制', 'data_setting': '数据条件', 'boundary': '判断边界'}


def field_at(card, name):
    if name in LABELS:
        return card.get(name)
    if re.fullmatch(r'contributions\.[0-2]', name):
        entries = card.get('contributions') or []
        index = int(name[-1])
        return entries[index] if index < len(entries) else None
    return None


def set_field(card, name, item):
    if name in LABELS:
        card[name] = item
    else:
        entries = card.setdefault('contributions', [])
        index = int(name[-1])
        while len(entries) <= index:
            entries.append({})
        entries[index] = item


def content_fingerprint(row):
    if row is None:
        return ''
    edits = json.loads(row.card_json or '{}').get('manual_fields')
    return digest([row.fingerprint, edits]) if edits else row.fingerprint


def preserve_edits(generated, stored, paper):
    """Recheck quotes against current source while preserving human text/history."""
    from app.reviews.cards import _verified_field
    card = dict(generated)
    if not stored.get('manual_fields'):
        return card
    sources = {'abstract': paper.abstract or '', 'full_text': paper.full_text or '', 'snippets': ''}
    for name, edit in stored['manual_fields'].items():
        item = _verified_field({'value': edit['value'], 'quote': edit['quote']}, sources,
                               not any(sources.values()))
        set_field(card, name, {**item, 'researcher_edited': True})
    for key in ('manual_fields', 'edit_history'):
        card[key] = stored.get(key, {} if key == 'manual_fields' else [])
    return card


def edit_field(session, review_id, paper_id, name, value, quote, expected_version):
    session.connection().exec_driver_sql('BEGIN IMMEDIATE')
    member = session.exec(select(ReviewPaper).where(
        ReviewPaper.review_id == review_id, ReviewPaper.paper_id == paper_id)).first()
    paper = session.get(Paper, paper_id)
    if member is None or paper is None or paper.is_deleted:
        raise LookupError('论文不在本次综述中或已删除')
    row = session.exec(select(PaperCard).where(PaperCard.paper_id == paper_id)).first()
    if row is None:
        raise LookupError('这篇论文还没有精读卡片')
    if row.version != expected_version:
        raise ValueError('卡片已有更新版本，请载入最新卡片后核对再保存；当前输入已保留。')
    card = json.loads(row.card_json)
    before = field_at(card, name)
    if not before or not value.strip():
        raise ValueError('请选择已有字段并填写修订内容')
    edits = card.setdefault('manual_fields', {})
    stamp = utc_iso(utcnow())
    edits[name] = {'value': value.strip(), 'quote': quote.strip(), 'updated_at': stamp,
                   'original': edits.get(name, {}).get('original', before)}
    card = preserve_edits(card, card, paper)
    card.setdefault('edit_history', []).append(dict(
        field=name, before=before, after=field_at(card, name), updated_at=stamp, version=row.version + 1))
    row.card_json = json.dumps(card, ensure_ascii=False)
    row.version += 1
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    return {'paper_id': paper_id, 'title': paper.title or member.title, 'status': row.status,
            'card': card, 'version': row.version, 'warning': row.warning, 'updated_at': row.updated_at}


def correction_snapshot(session, paper_id):
    """Use the existing researcher-note evidence channel; never duplicate editable notes."""
    row = session.exec(select(PaperCard).where(PaperCard.paper_id == paper_id)).first()
    card = json.loads(row.card_json) if row else {}
    edits = card.get('manual_fields') or {}
    if not edits:
        return []
    lines = []
    for name, edit in edits.items():
        label = LABELS.get(name, f'主要贡献 {int(name[-1]) + 1}' if name.startswith('contributions.') else name)
        lines.append(f'{label}：{edit["value"]}')
        if edit.get('quote'):
            lines.append(f'附引文（匹配状态：{field_at(card, name).get("status", "")}）：{edit["quote"]}')
    text = '\n'.join(lines)
    version = len(card.get('edit_history') or [])
    return [dict(ref=f'C{paper_id}.v{version}', paper_id=paper_id, scope='researcher_note',
                 version=version, kind='card_correction', tags=['卡片修订'], quote=text,
                 source_hash=digest(text), locator=f'人工卡片修订 · v{version}（研究记录，非论文原文）',
                 purpose='研究笔记')]
