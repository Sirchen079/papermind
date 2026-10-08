"""Literate-map pipeline: themes and assignments over a review's papers (A4a)."""
import json
import re
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


def update_themes(session, review_id, theme_list, expected_version):
    """Apply researcher-edited themes, clearing only affected downstream state.

    Kept assignments get their fingerprints recomputed against the new
    themes_fingerprint so the next run skips them (partial rerun).
    """
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    service.get(session, review_id)
    row = _map(session, review_id)
    if row is None:
        raise LookupError('文献地图尚未生成，先运行一次再编辑主题')
    if row.status == 'running':
        raise ValueError('文献地图正在生成，请先暂停')
    if row.version != expected_version:
        raise ValueError('已有更新版本，请刷新后保存')
    if not 1 <= len(theme_list) <= 15:
        raise ValueError('主题数量须在 1 到 15 之间')
    stored = json.loads(row.themes_json or '[]')

    def t_number(tid):
        match = re.fullmatch(r'T(\d+)', str(tid or ''))
        return int(match[1]) if match else 0

    next_number = max((t_number(t.get('id')) for t in list(theme_list) + stored), default=0)
    cleaned, seen = [], set()
    for theme in theme_list:
        if not isinstance(theme, dict) or not str(theme.get('name') or '').strip():
            raise ValueError('每个主题都需要非空名称')
        tid = str(theme.get('id') or '').strip()
        if not tid:
            next_number += 1
            tid = f'T{next_number}'
        if tid in seen:
            raise ValueError(f'主题 id 重复：{tid}')
        seen.add(tid)
        cleaned.append({'id': tid, 'name': str(theme['name']).strip(),
                        'definition': str(theme.get('definition') or ''),
                        'include': str(theme.get('include') or ''),
                        'exclude': str(theme.get('exclude') or '')})

    delta = themes.diff_themes(stored, cleaned)
    invalid = set(delta['changed']) | set(delta['removed'])
    assignments = json.loads(row.assignments_json or '{}')
    if delta['added']:  # every paper must be reconsidered against the new theme
        assignments = {}
    else:
        assignments = {pid: entry for pid, entry in assignments.items()
                       if not invalid.intersection(entry.get('themes') or [])}
    fingerprint = service.digest(cleaned)
    card_fps = {r.paper_id: r.fingerprint for r in session.exec(select(PaperCard))}
    for pid, entry in assignments.items():
        entry['fingerprint'] = service.digest([card_fps.get(int(pid), ''), fingerprint])
    syntheses = json.loads(row.syntheses_json or '{}')
    for tid in invalid:
        syntheses.pop(tid, None)
    row.assignments_json = service.encode(assignments)
    row.syntheses_json = service.encode(syntheses)
    if delta['added'] or not assignments:
        row.overview_json = '{}'
    row.themes_json = service.encode(cleaned)
    row.themes_fingerprint = fingerprint
    row.version += 1
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    return detail_map(session, review_id)


def detail_map(session, review_id):
    service.get(session, review_id)
    entries = service.papers(session, review_id)
    all_ids = [e.paper_id for e in entries]
    ids = [e.paper_id for e in entries if e.status != 'missing']
    paper_rows = {p.id: p for p in session.exec(
        select(service.Paper).where(service.Paper.id.in_(all_ids)))}
    cards = {r.paper_id: r for r in session.exec(
        select(PaperCard).where(PaperCard.paper_id.in_(all_ids)))}
    row = _map(session, review_id)
    assignments = json.loads(row.assignments_json or '{}') if row is not None else {}
    papers_payload = []
    for entry in entries:
        paper = paper_rows.get(entry.paper_id)
        card_row = cards.get(entry.paper_id)
        card = json.loads(card_row.card_json) if card_row is not None else {}
        papers_payload.append({
            'paper_id': entry.paper_id,
            'title': (paper.title if paper else None) or entry.title,
            'year': paper.year if paper else None,
            'venue': paper.venue if paper else '',
            'doi': paper.doi if paper else '',
            'themes': (assignments.get(str(entry.paper_id)) or {}).get('themes') or [],
            'evidence_level': card.get('evidence_level') or '',
            'card_status': card_row.status if card_row is not None else 'pending',
        })
    if row is None:
        return {'status': 'draft', 'stage': '', 'error': '', 'version': 0, 'themes': [],
                'assignments': {}, 'syntheses': {}, 'overview': {}, 'papers': papers_payload,
                'counts': {'papers': len(ids), 'cards_done': 0, 'assigned': 0, 'unassigned': len(ids)}}
    assigned = sum(1 for pid in ids if assignments.get(str(pid), {}).get('themes'))
    return {
        'status': row.status, 'stage': row.stage, 'error': row.error, 'version': row.version,
        'themes': json.loads(row.themes_json or '[]'), 'assignments': assignments,
        'syntheses': json.loads(row.syntheses_json or '{}'),
        'overview': json.loads(row.overview_json or '{}'),
        'papers': papers_payload,
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

        # 4. 主题综合（每主题一次调用；指纹命中即跳过）
        with Session(engine) as s:
            row = _map(s, review_id)
            theme_list = json.loads(row.themes_json or '[]')
            assignments = json.loads(row.assignments_json or '{}')
            syntheses = json.loads(row.syntheses_json or '{}')
            card_rows = {r.paper_id: r for r in s.exec(
                select(PaperCard).where(PaperCard.paper_id.in_(ids)))}
            paper_rows = {p.id: p for p in s.exec(
                select(service.Paper).where(service.Paper.id.in_(ids)))}
        members_of = {t['id']: [] for t in theme_list}
        for pid_str, entry in assignments.items():
            try:
                pid = int(pid_str)
            except ValueError:
                continue
            for tid in entry.get('themes') or []:
                if tid in members_of:
                    members_of[tid].append(pid)

        def verified_count(card):
            fields = [card.get(name) or {} for name in ('problem', 'mechanism', 'data_setting', 'boundary')]
            fields += card.get('contributions') or []
            return sum(1 for field in fields if field.get('status') == 'quote_verified')

        total = len(theme_list)
        for index, theme in enumerate(theme_list):
            if not active():
                return
            stage(f'主题综合 {index}/{total}')
            tid = theme['id']
            member_ids = members_of.get(tid, [])
            cards_by_pid = {}
            member_stats = []
            for pid in member_ids:
                card_row = card_rows.get(pid)
                card = json.loads(card_row.card_json) if card_row is not None else {}
                cards_by_pid[pid] = card
                paper = paper_rows.get(pid)
                member_stats.append({
                    'paper_id': pid,
                    'year': (card.get('metadata') or {}).get('year') or (paper.year if paper else None),
                    'evidence_level': card.get('evidence_level') or '',
                    'data_setting_value': (card.get('data_setting') or {}).get('value') or '',
                })
            stats = themes.theme_stats(member_stats)
            fingerprint = service.digest([
                theme,
                sorted((card_rows[pid].fingerprint if pid in card_rows else '') for pid in member_ids),
                themes.SYNTHESIZE_THEME,
            ])
            existing = syntheses.get(tid)
            if isinstance(existing, dict) and existing.get('fingerprint') == fingerprint:
                continue

            def brief(pid):
                card, paper = cards_by_pid.get(pid) or {}, paper_rows.get(pid)
                meta = card.get('metadata') or {}
                return {'paper_id': pid, 'year': meta.get('year') or (paper.year if paper else None),
                        'title': meta.get('title') or (paper.title if paper else '')}

            def full(pid):
                card = cards_by_pid.get(pid) or {}

                def field(name):
                    item = card.get(name) or {}
                    return {'value': item.get('value') or '', 'status': item.get('status') or ''}
                payload = brief(pid)
                payload.update({
                    'problem': field('problem'), 'mechanism': field('mechanism'),
                    'data_setting': field('data_setting'), 'boundary': field('boundary'),
                    'contributions': [{'value': c.get('value') or '', 'status': c.get('status') or ''}
                                      for c in card.get('contributions') or []],
                })
                return payload

            ranked = sorted(member_ids, key=lambda pid: -verified_count(cards_by_pid.get(pid) or {}))
            cards_payload = ([full(pid) for pid in ranked[:themes.SYNTH_FULL_CARDS]]
                            + [brief(pid) for pid in ranked[themes.SYNTH_FULL_CARDS:]])
            user = service.encode({'theme': theme, 'stats': stats, 'cards': cards_payload})
            validated = themes.validate_synthesis(
                themes.parse_payload(ask(themes.SYNTHESIZE_THEME, user, 3000)),
                member_ids, ids)
            if validated is None:  # 解析失败重试一次
                validated = themes.validate_synthesis(
                    themes.parse_payload(ask(themes.SYNTHESIZE_THEME, user, 3000)),
                    member_ids, ids)
            if validated is None:
                syntheses[tid] = {'error': '本主题综合未完成，可重新运行', 'stats': stats}
            else:
                syntheses[tid] = {**validated, 'stats': stats, 'fingerprint': fingerprint}
            with Session(engine) as s:
                row = _map(s, review_id)
                if row.run_token != token:
                    return
                row.syntheses_json = service.encode(syntheses)
                s.add(row)
                s.commit()

        # 5. 总览与阅读路线（任一主题综合指纹变化即重新生成）
        stage('总览与阅读路线')
        overview_fp = service.digest([
            [syntheses.get(t['id'], {}).get('fingerprint', '') for t in theme_list],
            themes.OVERVIEW,
        ])
        with Session(engine) as s:
            row = _map(s, review_id)
            current = json.loads(row.overview_json or '{}')
        if current.get('fingerprint') != overview_fp:
            def member_stat(pid):
                card = json.loads(card_rows[pid].card_json) if pid in card_rows else {}
                paper = paper_rows.get(pid)
                return {'paper_id': pid,
                        'year': (card.get('metadata') or {}).get('year') or (paper.year if paper else None),
                        'evidence_level': card.get('evidence_level') or '',
                        'data_setting_value': (card.get('data_setting') or {}).get('value') or ''}

            all_members = sorted({pid for pids in members_of.values() for pid in pids})
            theme_inputs = []
            for theme in theme_list:
                entry = syntheses.get(theme['id'], {})
                theme_inputs.append({
                    'id': theme['id'], 'name': theme['name'], 'definition': theme['definition'],
                    'trend': entry.get('trend', ''),
                    'open_questions': [q.get('question', '') for q in entry.get('open_questions', [])],
                    'representative': [
                        {'paper_id': rep.get('paper_id'),
                         'title': (paper_rows.get(rep.get('paper_id')).title
                                   if rep.get('paper_id') in paper_rows else '')}
                        for rep in entry.get('representative', [])],
                })
            user = service.encode({'themes': theme_inputs, 'stats': themes.theme_stats([member_stat(pid) for pid in all_members]),
                                   'unassigned': len(ids) - len(all_members)})
            validated = themes.validate_overview(
                themes.parse_payload(ask(themes.OVERVIEW, user, 3000)), ids)
            if validated is None:  # 解析失败重试一次
                validated = themes.validate_overview(
                    themes.parse_payload(ask(themes.OVERVIEW, user, 3000)), ids)
            overview_entry = ({**validated, 'fingerprint': overview_fp} if validated is not None
                              else {'error': '总览未完成，可重新运行'})
            with Session(engine) as s:
                row = _map(s, review_id)
                if row.run_token != token:
                    return
                row.overview_json = service.encode(overview_entry)
                s.add(row)
                s.commit()

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
