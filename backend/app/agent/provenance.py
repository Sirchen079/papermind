"""Keep provenance from actual local tool results, before display truncation."""
import json
from urllib.parse import quote

from app.models import Paper


SOURCE_TOOLS = {
    'search_library': 'metadata',
    'get_paper': 'summary',
    'get_paper_full_text': 'full_text',
    'find_related': 'metadata',
    'search_research_notes': 'research_note',
}


def tool_sources(session, name: str, result: str) -> list[dict]:
    if name not in SOURCE_TOOLS and name != 'search_topic_wiki':
        return []
    try:
        data = json.loads(result)
    except (TypeError, ValueError):
        return []
    rows = data if isinstance(data, list) else [data]
    if name == 'search_topic_wiki':
        return topic_sources(rows, name)
    sources = []
    for row in rows:
        if not isinstance(row, dict) or row.get('error') or row.get('ok') is False:
            continue
        # A failed phrase lookup or an exhausted page returned no paper text.
        # It is a search observation, not a supporting excerpt to cite.
        if name == 'get_paper_full_text' and not (isinstance(row.get('text'), str) and row['text'].strip()):
            continue
        pid = row.get('paper_id', row.get('id'))
        if not isinstance(pid, int) or isinstance(pid, bool):
            continue
        paper = session.get(Paper, pid)
        if paper is None or paper.is_deleted:
            continue
        snippet = row.get('snippet') or row.get('text') or row.get('abstract') or ''
        if not isinstance(snippet, str):
            snippet = ''
        snippet = ' '.join(snippet.split())[:280]
        source = {'paper_id': pid, 'title': paper.title or f'#{pid}',
                  'snippet': snippet, 'source_type': row.get('type', SOURCE_TOOLS[name]),
                  'retrieved_by': name}
        if row.get('locator'):
            source['locator'] = row['locator']
        sources.append(source)
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
        'sources': [row for row in rows if isinstance(row, dict)
                    and isinstance(row.get('paper_id'), int) and not isinstance(row['paper_id'], bool)
                    and row.get('source_type') != 'topic_wiki'],
        'topic_sources': [row for row in rows if isinstance(row, dict)
                          and row.get('source_type') == 'topic_wiki'],
    }


def merge_sources(existing: list[dict], new: list[dict]) -> None:
    # A paper's original-text and personal-note evidence are distinct records.
    def key(row):
        if row.get('source_type') == 'topic_wiki':
            return ('topic_wiki', row.get('workspace_id'), row.get('page_id'), row.get('revision'))
        return (row.get('paper_id'), row.get('source_type'), row.get('snippet'))
    seen = {key(row) for row in existing}
    for row in new:
        if key(row) not in seen:
            existing.append(row)
            seen.add(key(row))
