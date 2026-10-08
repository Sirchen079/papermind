"""Continue a small-paper research task from a specific saved artifact version."""
import json

from sqlmodel import select

from app.models import Paper, ResearchArtifact, ResearchTask
from app.agent.source_kinds import research_scope_kind


def artifact_for_version(session, task_id, version):
    task = session.get(ResearchTask, task_id)
    if task is None:
        raise LookupError('当前项目中没有这项研究')
    artifact = session.exec(select(ResearchArtifact).where(
        ResearchArtifact.task_id == task_id, ResearchArtifact.version == version)).first()
    if artifact is None:
        raise LookupError('这份研究成果版本不存在，请先保存研究判断')
    return task, artifact


def read_research_task(session, task_id, version, part='document', source_index=0,
                       start_char=0, max_chars=12000):
    try:
        task, artifact = artifact_for_version(session, task_id, version)
    except LookupError as exc:
        return json.dumps({'error': str(exc)}, ensure_ascii=False)
    sources = json.loads(artifact.evidence_snapshot_json)
    result = {'task_id': task.id, 'version': artifact.version, 'question': task.question}
    if part == 'source':
        if source_index < 0 or source_index >= len(sources):
            return json.dumps({'error': '该版本没有这条来源'}, ensure_ascii=False)
        source = sources[source_index]
        paper = session.get(Paper, source['paper_id'])
        result.update(paper_id=source['paper_id'], title=source.get('title'),
                      material_kind=research_scope_kind(source.get('scope')),
                      type='saved_excerpt', source_index=source_index,
                      pages=[source['page']] if source.get('page') else [],
                      locator=source.get('locator', ''), evidence_ref=source.get('ref'),
                      source_hash=source.get('source_hash'), coverage=source.get('scope'),
                      original_available=bool(paper and not paper.is_deleted))
        text = source.get('quote', '')
    else:
        latest = session.exec(select(ResearchArtifact.version).where(
            ResearchArtifact.task_id == task_id).order_by(ResearchArtifact.version.desc())).first()
        result.update(material_kind=artifact.claim_kind, support_status=artifact.support_status,
                      review_note=artifact.review_note, adopted=artifact.adopted,
                      paper_ids=json.loads(task.paper_ids_json), latest_version=latest,
                      note='这是指定版本的研究成果；source_catalog 是它保存时的来源，可用 part=source 回读。后续版本不会自动替换当前版本。',
                      source_catalog=[{'source_index': i, **{key: source.get(key) for key in
                          ('paper_id', 'title', 'ref', 'locator', 'page', 'scope')}}
                          for i, source in enumerate(sources)])
        text = artifact.content
    start = max(0, min(start_char, len(text)))
    end = min(len(text), start + max(500, min(max_chars, 20000)))
    return json.dumps({**result, 'text': text[start:end], 'start_char': start,
                       'total_chars': len(text), 'next_start_char': end if end < len(text) else None}, ensure_ascii=False)
