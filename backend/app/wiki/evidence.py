"""Stable evidence identities and local dependency checks; no model calls."""
import hashlib
import json
from sqlmodel import select
from app.models import Paper, PaperNote, PaperExcerpt, ResearchArtifact, ResearchTask, WikiPage, WikiRevision
from app.research.materials import collect_materials


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def paper_hash(session, paper):
    return digest({
        'paper': paper.model_dump(exclude={'created_at', 'updated_at', 'pdf_path'}),
        'notes': [n.model_dump() for n in session.exec(select(PaperNote).where(PaperNote.paper_id == paper.id).order_by(PaperNote.id))],
        'excerpts': [e.model_dump() for e in session.exec(select(PaperExcerpt).where(PaperExcerpt.paper_id == paper.id).order_by(PaperExcerpt.id))],
    })


def snapshot_papers(session, ids, question):
    rows = []
    for material in collect_materials(session, list(dict.fromkeys(ids)), question):
        paper = session.get(Paper, material['paper_id'])
        version = paper_hash(session, paper)
        evidence = material['evidence'] + [dict(quote=note.content[:1800], scope='researcher_note', locator=f'研究者笔记 #{note.id}')
            for note in session.exec(select(PaperNote).where(PaperNote.paper_id == paper.id).order_by(PaperNote.id)).all()[:6]]
        for entry in evidence:
            identity = digest([paper.id, version, entry['scope'], entry['locator'], entry['quote']])[:24]
            rows.append({**entry, 'ref': 'W' + identity, 'title': material['title'],
                         'paper_id': paper.id, 'dependency': {'kind': 'paper', 'id': paper.id, 'hash': version}})
    return rows


def snapshot_artifacts(session, ids):
    rows = []
    for aid in dict.fromkeys(ids):
        artifact = session.get(ResearchArtifact, aid)
        if artifact is None:
            raise LookupError(f'研究成果 {aid} 不存在')
        task = session.get(ResearchTask, artifact.task_id)
        dependency = {'kind': 'artifact', 'id': artifact.id, 'task_id': artifact.task_id,
                      'version': artifact.version, 'hash': digest(artifact.model_dump())}
        rows.append({'ref': 'A' + digest(dependency)[:24], 'title': task.question,
                     'quote': artifact.content, 'scope': 'researcher_judgment',
                     'locator': f'研究成果 v{artifact.version}', 'dependency': dependency,
                     'support_status': artifact.support_status, 'review_note': artifact.review_note,
                     'underlying_evidence': json.loads(artifact.evidence_snapshot_json)})
    return rows


def snapshot_pages(session, pairs, current_id):
    rows = []
    for pair in pairs:
        if pair['page_id'] == current_id:
            raise ValueError('专题不能引用自身作为证据')
        page = session.get(WikiPage, pair['page_id'])
        revision = session.exec(select(WikiRevision).where(WikiRevision.page_id == pair['page_id'], WikiRevision.number == pair['number'])).first()
        if page is None or revision is None or page.archived:
            raise LookupError('引用的专题版本不存在或已归档')
        rows.append({'ref': 'P' + digest(pair)[:24], 'title': page.title, 'quote': revision.content,
                     'scope': 'wiki_revision', 'locator': f'专题 v{revision.number}',
                     'dependency': {'kind': 'page', 'id': page.id, 'version': revision.number},
                     'support_status': revision.support_status,
                     'underlying_evidence': flatten([e for e in json.loads(revision.evidence_json) if e['ref'] in json.loads(revision.references_json)])})
    return rows


def flatten(evidence):
    """Retain every unique snapshot without duplicating a nested citation tree."""
    result = {}; pending = list(evidence)
    while pending:
        item = pending.pop(0)
        children = item.get('underlying_evidence', [])
        value = {k: v for k, v in item.items() if k != 'underlying_evidence'}
        if not value.get('dependency') and value.get('paper_id') and value.get('source_hash'):
            value['dependency'] = {'kind': 'research_paper', 'id': value['paper_id'], 'hash': value['source_hash']}
        key = digest(value)
        if key in result:
            continue
        if children:
            value['underlying_refs'] = [c.get('ref') for c in children if c.get('ref')]
        result[key] = value
        pending.extend(children)
    return list(result.values())


def merge(*groups):
    # Prior evidence stays immutable; a source revision receives a new ref.
    return list({item['ref']: item for group in groups for item in group}.values())


def changes(session, evidence):
    found = {}
    fingerprints = {}
    pending = list(evidence)
    while pending:
        item = pending.pop()
        pending.extend(child for child in item.get('underlying_evidence', []) if child.get('dependency'))
        dep = item.get('dependency')
        if not dep:
            continue
        key = encode(dep)
        if key in found:
            continue
        kind = dep['kind']; issue = None
        if kind == 'paper':
            paper = session.get(Paper, dep['id'])
            if paper is None or paper.is_deleted:
                issue = '原论文已移除，保留当时的证据快照'
            else:
                if paper.id not in fingerprints:
                    fingerprints[paper.id] = paper_hash(session, paper)
                if fingerprints[paper.id] != dep['hash']:
                    issue = '论文资料、笔记或摘录已变化'
        elif kind == 'research_paper':
            paper = session.get(Paper, dep['id'])
            if paper is None or paper.is_deleted:
                issue = '研究成果引用的原论文已移除'
            elif collect_materials(session, [paper.id], '')[0]['source_hash'] != dep['hash']:
                issue = '研究成果引用的原论文材料已变化'
        elif kind == 'artifact':
            artifact = session.get(ResearchArtifact, dep['id'])
            latest = session.exec(select(ResearchArtifact).where(ResearchArtifact.task_id == dep['task_id']).order_by(ResearchArtifact.version.desc())).first()
            if artifact is None:
                issue = '原研究成果已移除'
            elif digest(artifact.model_dump()) != dep['hash'] or (latest and latest.version > dep['version']):
                issue = '研究成果已有更新，请核对引用版本'
            # Raw evidence uses the research-task hash definition. Check it too.
            for raw in item.get('underlying_evidence', []):
                paper = session.get(Paper, raw.get('paper_id'))
                if paper is None or paper.is_deleted:
                    issue = '研究成果引用的原论文已移除'
                elif collect_materials(session, [paper.id], '')[0]['source_hash'] != raw.get('source_hash'):
                    issue = '研究成果引用的原论文材料已变化'
        elif kind == 'page':
            page = session.get(WikiPage, dep['id'])
            if page is None or page.archived:
                issue = '引用专题已归档或移除'
            elif page.adopted_revision != dep['version']:
                issue = '引用专题的采用版本已变化'
        if issue:
            found[key] = {'dependency': dep, 'title': item.get('title', ''), 'reason': issue}
        else:
            found[key] = None
    return [row for row in found.values() if row]
