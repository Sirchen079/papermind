"""Keep provenance from actual local tool results, before display truncation."""
import json
from urllib.parse import quote

from app.models import Paper
from app.agent.source_passages import paper_source
from app.agent.source_kinds import describe_source


SOURCE_TOOLS = {
    'search_library': 'metadata',
    'get_paper': 'summary',
    'get_paper_full_text': 'full_text',
    'get_paper_links': 'full_text',
    'search_paper_text': 'full_text',
    'read_chat_sources': 'saved_excerpt',
    'read_saved_document': 'saved_excerpt',
    'read_research_task': 'saved_excerpt',
    'find_related': 'metadata',
    'search_research_notes': 'research_note',
    'read_paper_notes': 'research_note',
    'read_webpage': 'web',
    'search_openalex': 'web',
    'find_related_openalex': 'web',
}


def tool_sources(session, name: str, result: str) -> list[dict]:
    if name not in SOURCE_TOOLS and name != 'search_topic_wiki':
        return []
    try:
        data = json.loads(result)
    except (TypeError, ValueError):
        return []
    rows = data if isinstance(data, list) else [data]
    if name == 'get_paper_links' and isinstance(data, dict):
        # Only the nearby original PDF text was read. A URI alone is not the
        # destination's content and must never become a web snapshot.
        rows = [dict(id=data.get('id'), text=link.get('context'), page=link.get('page'),
                     locator=link.get('locator')) for link in data.get('links', [])
                if isinstance(link, dict)]
    if name == 'get_paper_full_text' and isinstance(data, dict) and isinstance(data.get('other_matches'), list):
        # Keep the pages of each preview separate from the main excerpt.
        rows = [data, *[dict(item, id=data.get('id')) for item in data.get('other_matches', [])
                        if isinstance(item, dict)]]
    if name == 'search_topic_wiki':
        return topic_sources(rows, name)
    sources = []
    for row in rows:
        if not isinstance(row, dict) or row.get('error') or row.get('ok') is False:
            continue
        if name == 'read_webpage' or row.get('type') == 'web':
            from app.agent.web_sources import web_source
            # Snapshot tools paginate within a stored excerpt; original offsets
            # remain relative to the page text that was read at fetch time.
            web = web_source({**row, 'start_char': row.get('original_start_char', 0) + row.get('start_char', 0)}, name)
            if web:
                sources.append(web)
            continue
        # A failed phrase lookup or an exhausted page returned no paper text.
        # It is a search observation, not a supporting excerpt to cite.
        if name in {'get_paper_full_text', 'get_paper_links', 'read_chat_sources', 'read_saved_document', 'read_research_task', 'read_paper_notes'} and not (isinstance(row.get('text'), str) and row['text'].strip()):
            continue
        pid = row.get('paper_id', row.get('id'))
        if not isinstance(pid, int) or isinstance(pid, bool):
            continue
        paper = session.get(Paper, pid)
        if paper is None or paper.is_deleted:
            continue
        if name == 'get_paper':
            # The tool supplies both the author's abstract and an AI analysis.
            # Preserve them separately instead of calling the abstract a summary
            # and silently dropping the actual analysis from the saved record.
            abstract = row.get('abstract')
            sources.append(describe_source(paper_source(pid, paper.title,
                abstract if isinstance(abstract, str) else '', 'metadata', name)))
            analysis = row.get('summary')
            if isinstance(analysis, dict) and analysis:
                sources.append(describe_source(paper_source(pid, paper.title,
                    json.dumps(analysis, ensure_ascii=False, indent=2), 'generated_analysis', name)))
            continue
        snippet = row.get('snippet') or row.get('text') or row.get('abstract') or ''
        if not isinstance(snippet, str):
            snippet = ''
        pages = row.get('pages') if isinstance(row.get('pages'), list) else []
        if row.get('page') is not None:
            pages = [*pages, row['page']]
        source = paper_source(pid, paper.title, snippet, row.get('type', SOURCE_TOOLS[name]),
                              name, pages, row.get('locator'))
        if row.get('material_kind'):
            source['material_kind'] = row['material_kind']
        if name == 'read_paper_notes':
            source['research_note'] = {'note_id': row['note_id'], 'updated_at': row['updated_at'],
                                       'version': row.get('version'),
                                       'start_char': row['start_char'], 'end_char': row['end_char']}
        if name in {'read_chat_sources', 'read_saved_document'} and isinstance(row.get('saved_message_id'), int):
            source['carried_from_message'] = row['saved_message_id']
        if name == 'read_research_task':
            source['research_task'] = {'task_id': row['task_id'], 'version': row['version'], 'source_index': row['source_index']}
        sources.append(describe_source(source))
    return sources


def topic_sources(rows: list[dict], retrieved_by: str = 'turn_context') -> list[dict]:
    """Record pages actually supplied by local retrieval, independently of model prose."""
    from app.workspaces.context import current_workspace
    scope = current_workspace.get()
    workspace_id = scope.id if scope else 'legacy'
    result = []
    for row in rows:
        if not isinstance(row, dict) or row.get('error'):
            continue
        page_id, revision = row.get('page_id'), row.get('revision')
        if (not isinstance(page_id, str) or not page_id or
                not isinstance(revision, int) or isinstance(revision, bool) or revision < 1):
            continue
        result.append({
            'source_type': 'topic_wiki', 'workspace_id': workspace_id,
            'workspace_name': scope.name if scope else '默认项目',
            'page_id': page_id, 'revision': revision,
            'title': row.get('title') or '未命名专题',
            'url': f'?workspace={quote(workspace_id, safe="")}#wiki?page={quote(page_id, safe="")}&revision={revision}',
            'snippet': ' '.join(str(row.get('content', '')).split())[:280],
            'support_status': row.get('support_status', 'pending'),
            'review_note': row.get('review_note', ''),
            'source_changes': [item['reason'] for item in row.get('changes', [])
                               if isinstance(item, dict) and isinstance(item.get('reason'), str)],
            'evidence': [{key: item.get(key, '') for key in ('ref', 'title', 'quote', 'locator')}
                         for item in row.get('evidence', [])[:4] if isinstance(item, dict)],
            'retrieved_by': retrieved_by,
        })
    return result


def public_sources(rows: list[dict]) -> dict:
    # Keep the paper-only API stable: paper capture must never receive a Wiki id.
    return {
        'sources': [describe_source(row) for row in rows if isinstance(row, dict)
                    and isinstance(row.get('paper_id'), int) and not isinstance(row['paper_id'], bool)
                    and row.get('source_type') != 'topic_wiki'],
        'topic_sources': [row for row in rows if isinstance(row, dict)
                          and row.get('source_type') == 'topic_wiki'],
        'web_sources': [describe_source(row) for row in rows if isinstance(row, dict) and row.get('source_type') == 'web'],
    }


def merge_sources(existing: list[dict], new: list[dict]) -> None:
    # A paper's original-text and personal-note evidence are distinct records.
    def key(row):
        if row.get('source_type') == 'web':
            return ('web', row.get('snapshot_id'), row.get('start_char'), row.get('end_char'), row.get('excerpt'))
        if row.get('source_type') == 'topic_wiki':
            return ('topic_wiki', row.get('workspace_id'), row.get('page_id'), row.get('revision'))
        return (row.get('paper_id'), row.get('source_type'), row.get('excerpt', row.get('snippet')),
                tuple(row.get('pages') or []), row.get('locator'))
    seen = {key(row) for row in existing}
    for row in new:
        if key(row) not in seen:
            existing.append(row)
            seen.add(key(row))
