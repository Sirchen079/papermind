"""Self-contained HTML export of a literature map (A7a).

Rendering is a pure function over a plain payload dict so later exporters
(card 16) can reuse the same assembly.
"""
import html
import json
from collections import Counter
from datetime import datetime

from sqlmodel import Session, select
from app.models import Paper
from app.models.card import PaperCard
from app.models.paper import parse_authors_json
from app.reviews import service
from app.reviews.map import detail_map

LABELS = (
    ('quote_verified', '已核对原文'),
    ('number_mismatch', '数字与原文不符'),
    ('quote_not_found', '未在原文找到引文'),
    ('no_quote', '模型归纳'),
    ('unverifiable', '仅元数据，无法核对'),
)


def map_payload(session: Session, review_id) -> dict:
    """Assemble the full map detail plus per-paper cards for exporters."""
    detail = detail_map(session, review_id)
    entries = service.papers(session, review_id)
    all_ids = [e.paper_id for e in entries]
    card_rows = {r.paper_id: r for r in session.exec(
        select(PaperCard).where(PaperCard.paper_id.in_(all_ids)))}
    paper_rows = {p.id: p for p in session.exec(
        select(Paper).where(Paper.id.in_(all_ids)))}
    papers = []
    for entry in detail['papers']:
        row = paper_rows.get(entry['paper_id'])
        card_row = card_rows.get(entry['paper_id'])
        papers.append({**entry,
                       'authors': parse_authors_json(row.authors_json) if row else [],
                       'card': ({'status': card_row.status, 'model': card_row.model,
                                 'warning': card_row.warning,
                                 'card': json.loads(card_row.card_json)}
                                if card_row is not None else None)})
    models = Counter(info['card']['model'] for info in papers
                     if info['card'] and info['card'].get('model'))
    return {
        'question': service.get(session, review_id).question,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'model': models.most_common(1)[0][0] if models else '',
        'status': detail['status'], 'themes': detail['themes'],
        'assignments': detail['assignments'], 'syntheses': detail['syntheses'],
        'overview': detail['overview'], 'counts': detail['counts'], 'papers': papers,
    }


def _e(value) -> str:
    return html.escape(str(value if value is not None else ''), quote=True)


def _field_label(field: dict) -> str:
    status = field.get('status')
    if status == 'quote_verified':
        similarity = field.get('similarity')
        label = '近似核对原文' if similarity is not None and similarity < 1 else '已核对原文'
        pages = field.get('pages') or []
        if pages:
            label += '，第 ' + '、'.join(str(p) for p in pages) + ' 页'
        if field.get('found_in') == 'abstract':
            label += '（摘要）'
        return label
    if status == 'number_mismatch':
        missing = '、'.join(str(n) for n in field.get('missing_numbers') or [])
        return f'数字与原文不符：缺少 {missing}' if missing else '数字与原文不符'
    for key, label in LABELS:
        if status == key:
            return label
    return status or ''


def _paper_link(papers_by_id, pid) -> str:
    title = papers_by_id.get(pid, {}).get('title') or f'P{pid}'
    return f'<a href="#p{pid}">[P{pid}]</a> {_e(title)}'


def _bar_row(name, value, total) -> str:
    percent = round(100 * value / total) if total else 0
    return (f'<div class="bar-row"><span class="bar-name">{_e(name)}</span>'
            f'<span class="bar-track"><span class="bar-fill" style="width:{percent}%"></span></span>'
            f'<span class="bar-value">{value}</span></div>')


def render_html(payload: dict) -> str:
    """Pure string concatenation; every text node goes through html.escape."""
    themes = payload.get('themes') or []
    syntheses = payload.get('syntheses') or {}
    overview = payload.get('overview') or {}
    papers = payload.get('papers') or []
    papers_by_id = {p['paper_id']: p for p in papers}
    counts = payload.get('counts') or {}
    evidence = Counter(p.get('evidence_level') or '' for p in papers)

    parts = []
    parts.append('<!DOCTYPE html>\n<html lang="zh">\n<head>\n<meta charset="utf-8">\n'
                 f'<title>{_e(payload.get("question"))} · 文献地图</title>\n<style>\n'
                 'body{font-family:"Microsoft YaHei",system-ui,sans-serif;max-width:960px;'
                 'margin:0 auto;padding:24px;color:#222;background:#fafafa;line-height:1.6}\n'
                 'h1{font-size:22px}h2{font-size:18px;border-bottom:2px solid #ddd;padding-bottom:4px;margin-top:36px}\n'
                 '.meta{color:#666;font-size:13px}.theme{background:#fff;border:1px solid #e0e0e0;'
                 'border-radius:8px;padding:16px;margin:12px 0}\n'
                 '.tag{display:inline-block;font-size:12px;padding:1px 8px;border-radius:10px;'
                 'background:#eef; color:#335;margin:0 6px 6px 0}\n'
                 '.tag.warn{background:#fee;color:#a20}.tag.miss{background:#ffd;color:#860}\n'
                 '.bar-row{display:flex;align-items:center;gap:8px;font-size:13px;margin:2px 0}\n'
                 '.bar-name{width:6em}.bar-track{flex:1;height:10px;background:#eee;border-radius:5px;overflow:hidden}\n'
                 '.bar-fill{display:block;height:10px;background:#7aa}\n.bar-value{width:3em;text-align:right}\n'
                 'details{background:#fff;border:1px solid #e0e0e0;border-radius:8px;margin:8px 0;padding:8px 12px}\n'
                 'summary{cursor:pointer}.quote{color:#555;border-left:3px solid #ccc;padding-left:8px;margin:4px 0;font-size:13px}\n'
                 'table{border-collapse:collapse;width:100%;background:#fff;font-size:14px}\n'
                 'th,td{border:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top}\n'
                 'th{background:#f0f0f0}.controls{display:flex;gap:12px;margin:10px 0}\n'
                 '.muted{color:#777;font-size:13px}footer{color:#999;font-size:12px;margin-top:40px}\n'
                 '</style>\n</head>\n<body>\n')

    # 1. 标题区
    parts.append(f'<h1>{_e(payload.get("question"))}</h1>\n'
                 f'<p class="meta">生成日期：{_e(payload.get("generated_at"))} · '
                 f'论文 {counts.get("papers", len(papers))} 篇 · '
                 f'生成模型：{_e(payload.get("model") or "—")}</p>\n')

    # 2. 方法与边界
    parts.append('<h2>方法与边界</h2>\n<p>'
                 f'本地图基于研究者选定的 {counts.get("papers", len(papers))} 篇论文，不代表穷尽检索。</p>\n'
                 f'<p>证据级别：全文 {evidence.get("full_text", 0)} 篇 / 摘要 {evidence.get("abstract", 0)} 篇 / '
                 f'仅元数据 {evidence.get("metadata", 0)} 篇。</p>\n'
                 '<p class="muted">核对标签含义：'
                 + '；'.join(label for _, label in LABELS)
                 + '（有页码时标注页码，来自摘要时注明“（摘要）”）。</p>\n')

    # 3. 总览
    parts.append('<h2>总览</h2>\n')
    if overview.get('error'):
        parts.append(f'<p class="tag warn">{_e(overview["error"])}</p>\n')
    if overview.get('summary'):
        parts.append(f'<p>{_e(overview["summary"])}</p>\n')
    route = overview.get('reading_route') or []
    if route:
        parts.append('<h3>建议阅读路线</h3>\n<ol>\n')
        for step in route:
            papers_html = '、'.join(_paper_link(papers_by_id, pid) for pid in step.get('papers') or [])
            if not papers_html:
                papers_html = '<span class="muted">无</span>'
            missing = ' <span class="tag miss">来源待补</span>' if step.get('source_missing') else ''
            parts.append(f'<li><strong>{_e(step.get("goal"))}</strong>{missing}：'
                         f'{papers_html}'
                         f'<span class="muted">（{_e(step.get("why"))}）</span></li>\n')
        parts.append('</ol>\n')
    steps = overview.get('research_steps') or []
    if steps:
        parts.append('<h3>开展新研究的步骤</h3>\n<ol>\n')
        for step in steps:
            parts.append(f'<li>{_e(step)}</li>\n')
        parts.append('</ol>\n')

    # 4. 主题卡
    parts.append('<h2>主题</h2>\n')
    for theme in themes:
        tid = theme.get('id')
        entry = syntheses.get(tid) or {}
        parts.append(f'<div class="theme" id="theme-{_e(tid)}">\n'
                     f'<h3>{_e(theme.get("name"))}</h3>\n'
                     f'<p class="muted">{_e(theme.get("definition"))}</p>\n')
        stats = entry.get('stats') or {}
        if stats:
            total = stats.get('count') or 0
            parts.append('<div class="muted">年份分布：'
                         + '；'.join(f'{_e(year)} 年 {n} 篇' for year, n in (stats.get('years') or {}).items())
                         + '。</div>\n')
            setting = stats.get('setting') or {}
            parts.append('<div class="muted">数据条件：'
                         + '；'.join(f'{_e(key)} {value} 篇' for key, value in setting.items())
                         + '。</div>\n')
            for name, value in (('实测', setting.get('field', 0)), ('合成', setting.get('synthetic', 0))):
                parts.append(_bar_row(name, value, total))
        if entry.get('error'):
            parts.append(f'<p class="tag warn">{_e(entry["error"])}</p>\n')
        if entry.get('trend'):
            parts.append(f'<p><strong>趋势：</strong>{_e(entry["trend"])}</p>\n')
        questions = entry.get('open_questions') or []
        if questions:
            parts.append('<p><strong>值得研究的问题：</strong></p>\n<ul>\n')
            for item in questions:
                missing = ' <span class="tag miss">来源待补</span>' if item.get('source_missing') else ''
                cards = '、'.join(f'<a href="#p{pid}">[P{pid}]</a>' for pid in item.get('cards') or [])
                parts.append(f'<li>{_e(item.get("question"))}{missing}'
                             f'<div class="muted">为什么还没回答：{_e(item.get("why"))}</div>'
                             f'<div class="muted">据现有证据不能宣称：{_e(item.get("cannot_claim"))}</div>'
                             f'<div class="muted">依据：{cards or "—"}</div></li>\n')
            parts.append('</ul>\n')
        combos = entry.get('combination_opportunities') or []
        if combos:
            parts.append('<p><strong>方法组合与迁移机会：</strong></p>\n<ul>\n')
            for item in combos:
                missing = ' <span class="tag miss">来源待补</span>' if item.get('source_missing') else ''
                cards = '、'.join(f'<a href="#p{pid}">[P{pid}]</a>' for pid in item.get('cards') or [])
                parts.append(f'<li>{_e(item.get("idea"))}{missing}'
                             f'<div class="muted">预期解决：{_e(item.get("expected"))}；主要风险：{_e(item.get("risk"))}</div>'
                             f'<div class="muted">依据：{cards or "—"}</div></li>\n')
            parts.append('</ul>\n')
        reps = entry.get('representative') or []
        if reps:
            parts.append('<p><strong>代表论文：</strong>'
                         + '；'.join(f'{_paper_link(papers_by_id, r.get("paper_id"))}'
                                     f'（{_e(r.get("why"))}）' for r in reps)
                         + '</p>\n')
        parts.append('</div>\n')

    # 5. 精读卡片
    parts.append('<h2>精读卡片</h2>\n')
    for paper in papers:
        pid = paper.get('paper_id')
        info = paper.get('card') or {}
        card = info.get('card') or {}
        venue = paper.get('venue') or ''
        head = f"[P{pid}] {paper.get('year') or ''} {paper.get('title') or ''}"
        if venue:
            head += f' · {venue}'
        parts.append(f'<details id="p{pid}">\n<summary>{_e(head)}</summary>\n')
        parts.append('<p class="muted">'
                     + '；'.join(filter(None, [
                         '作者：' + (_e(', '.join(paper.get('authors') or [])) if paper.get('authors') else ''),
                         f'证据级别：{_e(paper.get("evidence_level") or "—")}',
                         f'卡片状态：{_e(info.get("status") or paper.get("card_status") or "pending")}']))
                     + '</p>\n')
        if paper.get('doi'):
            parts.append(f'<p>DOI：<a href="https://doi.org/{_e(paper["doi"])}">{_e(paper["doi"])}</a></p>\n')
        if paper.get('themes'):
            names = {t.get('id'): t.get('name') for t in themes}
            parts.append('<p>所属主题：'
                         + ''.join(f'<span class="tag">{_e(names.get(tid, tid))}</span>' for tid in paper['themes'])
                         + '</p>\n')
        if card:
            fields = (('问题', 'problem'), ('机制', 'mechanism'), ('数据条件', 'data_setting'),
                      ('判断边界', 'boundary'))
            for label, key in fields:
                field = card.get(key) or {}
                parts.append(_render_field(label, field))
            for index, item in enumerate(card.get('contributions') or [], start=1):
                parts.append(_render_field(f'主要贡献 {index}', item))
        else:
            parts.append('<p class="muted">这篇论文还没有精读卡片。</p>\n')
        parts.append('</details>\n')

    # 6. 主表 + 原生 JS 过滤
    parts.append('<h2>论文总表</h2>\n'
                 '<div class="controls">\n'
                 '<input id="map-search" type="text" placeholder="搜索题名、期刊、DOI" style="flex:1;padding:6px 10px">\n'
                 '<select id="theme-filter" style="padding:6px 10px">\n'
                 '<option value="">全部主题</option>\n')
    for theme in themes:
        parts.append(f'<option value="{_e(theme.get("id"))}">{_e(theme.get("name"))}</option>\n')
    parts.append('</select>\n</div>\n'
                 '<table id="main-table">\n<thead><tr><th>编号</th><th>年份</th><th>题名</th>'
                 '<th>期刊</th><th>主题</th><th>证据级别</th><th>DOI</th></tr></thead>\n<tbody>\n')
    names = {t.get('id'): t.get('name') for t in themes}
    for paper in papers:
        pid = paper.get('paper_id')
        search = ' '.join(str(paper.get(key) or '') for key in ('title', 'venue', 'doi')).lower()
        theme_ids = ','.join(paper.get('themes') or [])
        doi = paper.get('doi')
        doi_html = (f'<a href="https://doi.org/{_e(doi)}">{_e(doi)}</a>' if doi else '')
        parts.append(f'<tr data-search="{_e(search)}" data-themes="{_e(theme_ids)}">'
                     f'<td>[P{pid}]</td><td>{_e(paper.get("year") or "")}</td>'
                     f'<td><a href="#p{pid}">{_e(paper.get("title") or "")}</a></td>'
                     f'<td>{_e(paper.get("venue") or "")}</td>'
                     f'<td>{_e("、".join(names.get(tid, tid) for tid in paper.get("themes") or []))}</td>'
                     f'<td>{_e(paper.get("evidence_level") or "")}</td><td>{doi_html}</td></tr>\n')
    parts.append('</tbody>\n</table>\n')
    parts.append('<script>\n(function(){\n'
                 'var input=document.getElementById("map-search"),select=document.getElementById("theme-filter");\n'
                 'function apply(){var q=(input.value||"").toLowerCase(),t=select.value;\n'
                 'document.querySelectorAll("#main-table tbody tr").forEach(function(row){\n'
                 'var hit=!q||row.getAttribute("data-search").indexOf(q)>=0;\n'
                 'var ok=!t||(","+row.getAttribute("data-themes")+",").indexOf(","+t+",")>=0;\n'
                 'row.style.display=(hit&&ok)?"":"none";});}\n'
                 'input.addEventListener("input",apply);select.addEventListener("change",apply);})();\n'
                 '</script>\n')
    parts.append(f'<footer>由 PaperMind 生成 · 生成模型 {_e(payload.get("model") or "—")} · '
                 f'{_e(payload.get("generated_at"))}</footer>\n</body>\n</html>\n')
    return ''.join(parts)


def _render_field(label: str, field: dict) -> str:
    value = field.get('value') or ''
    quote = field.get('quote') or ''
    label_html = f'<span class="tag">{_e(_field_label(field))}</span>'
    if field.get('status') == 'number_mismatch':
        label_html = f'<span class="tag warn">{_e(_field_label(field))}</span>'
    quote_html = f'<div class="quote">原文：“{_e(quote)}”</div>' if quote else ''
    return (f'<p><strong>{_e(label)}：</strong>{label_html}<br>{_e(value)}\n{quote_html}</p>\n')


TABLE_HEADERS = ('编号', '年份', '题名', '作者', '期刊', 'DOI', '主题', '证据级别', '卡片状态')


def _table_rows(payload: dict):
    names = {t.get('id'): t.get('name') for t in payload.get('themes') or []}
    for paper in payload.get('papers') or []:
        yield [
            f"P{paper.get('paper_id')}", paper.get('year') or '',
            paper.get('title') or '', ', '.join(paper.get('authors') or []),
            paper.get('venue') or '', paper.get('doi') or '',
            '、'.join(names.get(tid, tid) for tid in paper.get('themes') or []),
            paper.get('evidence_level') or '', paper.get('card_status') or '',
        ]


def render_xlsx(payload: dict) -> bytes:
    from io import BytesIO

    import openpyxl

    wb = openpyxl.Workbook()
    main = wb.active
    main.title = '主表'
    main.append(list(TABLE_HEADERS))
    for row in _table_rows(payload):
        main.append(row)
    main.freeze_panes = 'A2'
    main.auto_filter.ref = main.dimensions

    cards = wb.create_sheet('精读卡片')
    cards.append(['编号', '题名', '问题', '机制', '数据条件', '主要贡献', '判断边界',
                  '问题核对', '机制核对', '数据条件核对', '贡献核对', '边界核对'])
    for paper in payload.get('papers') or []:
        info = paper.get('card') or {}
        card = info.get('card') or {}
        contributions = card.get('contributions') or []

        def labels(items):
            return '；'.join(_field_label(item) for item in items)

        cards.append([
            f"P{paper.get('paper_id')}", paper.get('title') or '',
            (card.get('problem') or {}).get('value') or '',
            (card.get('mechanism') or {}).get('value') or '',
            (card.get('data_setting') or {}).get('value') or '',
            '\n'.join((item.get('value') or '') for item in contributions),
            (card.get('boundary') or {}).get('value') or '',
            labels([card.get('problem') or {}]), labels([card.get('mechanism') or {}]),
            labels([card.get('data_setting') or {}]), labels(contributions),
            labels([card.get('boundary') or {}]),
        ])

    themes_sheet = wb.create_sheet('主题与问题')
    themes_sheet.append(['主题', '定义', '趋势', '值得研究的问题', '方法组合机会', '代表论文编号'])
    syntheses = payload.get('syntheses') or {}
    for theme in payload.get('themes') or []:
        entry = syntheses.get(theme.get('id')) or {}
        themes_sheet.append([
            theme.get('name') or '', theme.get('definition') or '', entry.get('trend') or '',
            '\n'.join(item.get('question') or '' for item in entry.get('open_questions') or []),
            '\n'.join(item.get('idea') or '' for item in entry.get('combination_opportunities') or []),
            ' '.join(f"[P{rep.get('paper_id')}]" for rep in entry.get('representative') or []),
        ])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def render_docx(payload: dict) -> bytes:
    from io import BytesIO

    from docx import Document

    papers = payload.get('papers') or []
    papers_by_id = {p['paper_id']: p for p in papers}
    counts = payload.get('counts') or {}
    evidence = Counter(p.get('evidence_level') or '' for p in papers)
    doc = Document()
    doc.add_heading(payload.get('question') or '文献地图', 0)
    doc.add_paragraph(f"生成日期：{payload.get('generated_at') or ''} · "
                      f"论文 {counts.get('papers', len(papers))} 篇 · "
                      f"生成模型：{payload.get('model') or '—'}")
    doc.add_heading('方法与边界', level=1)
    doc.add_paragraph(f"本地图基于研究者选定的 {counts.get('papers', len(papers))} 篇论文，不代表穷尽检索。"
                      f"证据级别：全文 {evidence.get('full_text', 0)} 篇 / 摘要 {evidence.get('abstract', 0)} 篇 / "
                      f"仅元数据 {evidence.get('metadata', 0)} 篇。")
    overview = payload.get('overview') or {}
    doc.add_heading('总览', level=1)
    if overview.get('error'):
        doc.add_paragraph(overview['error'])
    if overview.get('summary'):
        doc.add_paragraph(overview['summary'])
    route = overview.get('reading_route') or []
    if route:
        doc.add_heading('建议阅读路线', level=2)
        for step in route:
            titles = '、'.join(f"[P{pid}] {papers_by_id.get(pid, {}).get('title', '')}"
                               for pid in step.get('papers') or [])
            doc.add_paragraph(f"第 {step.get('step')} 步：{step.get('goal')} —— {titles}"
                              f"（{step.get('why')}）")
    for index, step in enumerate(overview.get('research_steps') or [], start=1):
        if index == 1:
            doc.add_heading('开展新研究的步骤', level=2)
        doc.add_paragraph(f"{index}. {step}")
    doc.add_heading('主题', level=1)
    syntheses = payload.get('syntheses') or {}
    for theme in payload.get('themes') or []:
        entry = syntheses.get(theme.get('id')) or {}
        doc.add_heading(f"{theme.get('name')}（{theme.get('id')}）", level=2)
        doc.add_paragraph(theme.get('definition') or '')
        if entry.get('error'):
            doc.add_paragraph(entry['error'])
        if entry.get('trend'):
            doc.add_paragraph(f"趋势：{entry['trend']}")
        for item in entry.get('open_questions') or []:
            doc.add_paragraph(f"值得研究的问题：{item.get('question')}"
                              f"（据现有证据不能宣称：{item.get('cannot_claim')}）", style='List Bullet')
        for item in entry.get('combination_opportunities') or []:
            doc.add_paragraph(f"方法组合机会：{item.get('idea')}；预期：{item.get('expected')}；"
                              f"风险：{item.get('risk')}", style='List Bullet')
        for rep in entry.get('representative') or []:
            doc.add_paragraph(f"代表论文：[P{rep.get('paper_id')}] "
                              f"{papers_by_id.get(rep.get('paper_id'), {}).get('title', '')}"
                              f"（{rep.get('why')}）", style='List Bullet')
    doc.add_heading('附录：精读卡片', level=1)
    for paper in papers:
        doc.add_heading(f"[P{paper.get('paper_id')}] {paper.get('title') or ''}"
                        f"（{paper.get('year') or ''}）", level=3)
        info = paper.get('card') or {}
        card = info.get('card') or {}
        if not card:
            doc.add_paragraph('这篇论文还没有精读卡片。')
            continue
        for label, key in (('问题', 'problem'), ('机制', 'mechanism'), ('数据条件', 'data_setting'),
                           ('判断边界', 'boundary')):
            field = card.get(key) or {}
            doc.add_paragraph(f"{label}：{field.get('value') or ''}（{_field_label(field)}）")
        for item in card.get('contributions') or []:
            doc.add_paragraph(f"主要贡献：{item.get('value') or ''}（{_field_label(item)}）")
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def render_csv(payload: dict) -> str:
    import csv
    import io

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(TABLE_HEADERS)
    for row in _table_rows(payload):
        writer.writerow(row)
    return '\ufeff' + buf.getvalue()  # BOM so Excel opens it cleanly


def render_bibtex(payload: dict, session) -> str:
    from app.archive.bibtex import citekey, format_paper

    ids = [p['paper_id'] for p in payload.get('papers') or []]
    rows = session.exec(select(Paper).where(Paper.id.in_(ids))).all() if ids else []
    by_id = {p.id: p for p in rows}
    seen: dict[str, int] = {}
    entries = []
    for pid in ids:
        paper = by_id.get(pid)
        if paper is None:
            continue
        base = citekey(paper)
        count = seen.get(base, 0)
        seen[base] = count + 1
        key = base if count == 0 else f'{base}{count + 1}'
        entries.append(format_paper(paper, key))
    return '\n\n'.join(entries) + ('\n' if entries else '')


EXPORT_FORMATS = {
    'html': ('text/html; charset=utf-8', '文献地图.html', 'map.html'),
    'xlsx': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '文献地图.xlsx', 'map.xlsx'),
    'docx': ('application/vnd.openxmlformats-officedocument.wordprocessingml.document', '文献地图.docx', 'map.docx'),
    'csv': ('text/csv; charset=utf-8', '文献地图.csv', 'map.csv'),
    'bib': ('application/x-bibtex', '文献地图.bib', 'map.bib'),
}


def export_file(session, review_id, fmt: str):
    """Render one export format; returns (body, media_type, filename headers)."""
    from urllib.parse import quote as urlquote

    payload = map_payload(session, review_id)
    media_type, cn_name, ascii_name = EXPORT_FORMATS[fmt]
    if fmt == 'html':
        body = render_html(payload).encode('utf-8')
    elif fmt == 'xlsx':
        body = render_xlsx(payload)
    elif fmt == 'docx':
        body = render_docx(payload)
    elif fmt == 'csv':
        body = render_csv(payload).encode('utf-8')  # BOM included by render_csv
    else:
        body = render_bibtex(payload, session).encode('utf-8')
    return body, media_type, {
        'Content-Disposition': f'attachment; filename="{ascii_name}"; '
                               f"filename*=UTF-8''{urlquote(cn_name)}"}
