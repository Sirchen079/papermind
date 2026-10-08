"""Literate-map pipeline: themes and assignments over a review's papers (A4a)."""
import json
from uuid import uuid4

from sqlmodel import Session, select
from app.models.base import utcnow
from app.models.card import PaperCard
from app.models.review import ReviewMap
from app.reviews import service, themes


def _map(session, review_id):
    return session.exec(select(ReviewMap).where(ReviewMap.review_id == review_id)).first()


def start_map(session, review_id):
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    service.get(session, review_id)  # 404 when the review itself is gone
    row = _map(session, review_id)
    if row is None:
        row = ReviewMap(review_id=review_id)
        session.add(row)
        session.flush()
    if row.status == 'running':
        raise ValueError('文献地图正在生成')
    row.run_token = uuid4().hex
    row.status = 'running'
    row.error = ''
    row.stage = '准备材料'
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    return row.run_token


def stop_map(session, review_id):
    service.get(session, review_id)
    row = _map(session, review_id)
    if row is None:
        raise LookupError('文献地图尚未生成')
    row.run_token = ''
    row.status = 'paused'
    row.stage = '已暂停，继续时复用已完成步骤'
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    return detail_map(session, review_id)


def detail_map(session, review_id):
    service.get(session, review_id)
    ids = [p.paper_id for p in service.papers(session, review_id) if p.status != 'missing']
    row = _map(session, review_id)
    if row is None:
        return {'status': 'draft', 'stage': '', 'error': '', 'version': 0, 'themes': [],
                'assignments': {}, 'syntheses': {}, 'overview': {},
                'counts': {'papers': len(ids), 'cards_done': 0, 'assigned': 0, 'unassigned': len(ids)}}
    cards = {r.paper_id: r for r in session.exec(
        select(PaperCard).where(PaperCard.paper_id.in_(ids)))}
    assignments = json.loads(row.assignments_json or '{}')
    assigned = sum(1 for pid in ids if assignments.get(str(pid), {}).get('themes'))
    return {
        'status': row.status, 'stage': row.stage, 'error': row.error, 'version': row.version,
        'themes': json.loads(row.themes_json or '[]'), 'assignments': assignments,
        'syntheses': json.loads(row.syntheses_json or '{}'),
        'overview': json.loads(row.overview_json or '{}'),
        'counts': {'papers': len(ids),
                   'cards_done': sum(1 for pid in ids if cards.get(pid)
                                     and cards[pid].status in ('done', 'metadata_only')),
                   'assigned': assigned, 'unassigned': len(ids) - assigned},
    }


def run_map(engine, review_id, token):
    from app.reviews import cards as card_mod

    def active():
        with Session(engine) as s:
            row = _map(s, review_id)
            return bool(row and row.status == 'running' and row.run_token == token)

    def stage(label):
        with Session(engine) as s:
            row = _map(s, review_id)
            if row is None or row.run_token != token:
                return
            row.stage = label
            row.updated_at = utcnow()
            s.add(row)
            s.commit()

    def close(message, status):
        with Session(engine) as s:
            row = _map(s, review_id)
            if row is None or row.run_token != token:
                return
            row.status = status
            row.error = message
            row.run_token = ''
            row.updated_at = utcnow()
            s.add(row)
            s.commit()

    try:
        with Session(engine) as s:
            selected = service.pick_llm(s, 'chat')
        if selected is None:
            close('没有可用的对话模型', 'failed')
            return
        client, provider, model = selected

        def ask(system, user, max_tokens):
            result = client.complete(
                provider, model,
                [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                request_kind='library_review', ref_id=review_id, max_tokens=max_tokens,
                reasoning_effort='low')
            return result.content or ''

        stage('精读卡片')
        with Session(engine) as s:
            ids = [p.paper_id for p in service.papers(s, review_id) if p.status != 'missing']
        card_mod.ensure_cards(engine, ids, client, provider, model, review_id, active, [])
        if not active():
            return

        stage('提出主题')
        with Session(engine) as s:
            row = _map(s, review_id)
            existing = json.loads(row.themes_json or '[]')
        if not existing:  # researcher-edited themes are never overwritten
            with Session(engine) as s:
                lines = themes.card_lines(s, review_id)
            try:
                proposed = themes.renumber(themes.propose_themes(ask, lines))
            except themes.ThemeError:
                close('主题提出失败，可重新运行', 'failed')
                return
            with Session(engine) as s:
                row = _map(s, review_id)
                if row.run_token != token:
                    return
                row.themes_json = service.encode(proposed)
                row.themes_fingerprint = service.digest(proposed)
                s.add(row)
                s.commit()
        if not active():
            return

        with Session(engine) as s:
            row = _map(s, review_id)
            theme_list = json.loads(row.themes_json or '[]')
            themes_fp = row.themes_fingerprint
            card_rows = {r.paper_id: r for r in s.exec(
                select(PaperCard).where(PaperCard.paper_id.in_(ids)))}
        todo = []
        for pid in ids:
            fingerprint = service.digest([card_rows[pid].fingerprint if pid in card_rows else '',
                                          themes_fp])
            prior = json.loads(row.assignments_json or '{}').get(str(pid))
            if prior and prior.get('fingerprint') == fingerprint and prior.get('themes'):
                continue
            todo.append((pid, fingerprint))
        total = len(todo)
        done = 0
        for start in range(0, len(todo), themes.ASSIGN_BATCH):
            if not active():
                return
            stage(f'论文归类 {done}/{total}')
            batch = todo[start:start + themes.ASSIGN_BATCH]
            with Session(engine) as s:
                lines = [themes.card_line(pid, card_rows.get(pid), s.get(service.Paper, pid))
                         for pid, _ in batch]
            found = themes.assign_batch(ask, theme_list, lines)
            with Session(engine) as s:
                row = _map(s, review_id)
                if row.run_token != token:
                    return
                merged = json.loads(row.assignments_json or '{}')
                for pid, fingerprint in batch:
                    entry = found.get(pid) or {'themes': [], 'reason': '未能归类'}
                    entry['fingerprint'] = fingerprint
                    merged[str(pid)] = entry
                row.assignments_json = service.encode(merged)
                s.add(row)
                s.commit()
            done += len(batch)

        with Session(engine) as s:
            row = _map(s, review_id)
            if row.run_token != token:
                return
            row.status = 'ready'
            row.stage = '文献地图已生成'
            row.version += 1
            row.error = ''
            row.run_token = ''
            row.updated_at = utcnow()
            s.add(row)
            s.commit()
    except Exception as exc:
        close(type(exc).__name__, 'failed')
