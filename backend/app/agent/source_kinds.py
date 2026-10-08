"""Describe the material actually returned, without judging whether a claim is true."""
from urllib.parse import parse_qs, urlsplit

KINDS = {'original_text', 'abstract_metadata', 'discovery', 'generated_analysis',
         'research_record', 'webpage', 'unknown'}


def source_material_kind(source):
    kind = source.get('material_kind')
    if isinstance(kind, str) and kind in KINDS:
        return kind
    source_type = source.get('source_type')
    if source_type == 'web':
        return web_material_kind(source.get('url', ''), source.get('content_region'))
    if source_type == 'full_text':
        return 'original_text'
    if source_type == 'metadata':
        return 'discovery' if source.get('retrieved_by') in {'search_library', 'find_related'} else 'abstract_metadata'
    # Older get_paper snapshots stored the abstract under the label "summary".
    # Reclassify the view only; never rewrite those original snapshots.
    if source_type == 'summary' and source.get('retrieved_by') == 'get_paper':
        return 'abstract_metadata'
    if source_type in {'summary', 'generated_analysis'}:
        return 'generated_analysis'
    if source_type in {'research_note', 'note', 'excerpt', 'matrix'}:
        return 'research_record'
    return 'unknown'


def web_material_kind(url, region=None):
    if region == 'pdf_text':
        return 'original_text'
    # Recognized endpoint semantics, not a guessed classification of page prose.
    try:
        parsed = urlsplit(url)
        host, path = parsed.hostname, parsed.path.rstrip('/')
        if host in {'arxiv.org', 'export.arxiv.org'} and path == '/api/query':
            return 'discovery' if 'search_query' in parse_qs(parsed.query) else 'abstract_metadata'
        if host in {'api.crossref.org', 'api.openalex.org'} and (path == '/works' or path.startswith('/works/')):
            return 'discovery' if path == '/works' else 'abstract_metadata'
        if (host in {'arxiv.org', 'www.bing.com', 'www.google.com'} and path == '/search'):
            return 'discovery'
    except (TypeError, ValueError):
        pass
    return 'abstract_metadata' if region == 'scholarly_metadata' else 'webpage'


def describe_source(source):
    return {**source, 'material_kind': source_material_kind(source)}


def research_scope_kind(scope):
    return {'abstract': 'abstract_metadata', 'excerpt': 'research_record',
            'researcher_note': 'research_record', 'full_text': 'original_text',
            'full_text_span': 'original_text', 'retrieved_span': 'original_text',
            'retrieved_context': 'original_text'}.get(scope, 'unknown')
