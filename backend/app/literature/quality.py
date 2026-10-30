"""Venue admission uses external expert lists, independently of model screening.

OpenAlex list membership: https://help.openalex.org/data/sources/attributes/
JUFO criteria: https://julkaisufoorumi.fi/en/evaluations/classification-criteria
These are venue signals, not an assessment of an individual paper's methods.
"""

SOURCE_LISTS = {
    'jufo-3': 'JUFO 3', 'jufo-2': 'JUFO 2',
    'norway-2': '挪威期刊目录 2', 'ccf-a': 'CCF A',
}
SOURCE_FILTER = 'primary_location.source.listed_in:' + '|'.join(SOURCE_LISTS)


def source_quality(record: dict) -> str:
    if record.get('is_retracted') or record.get('source_type') == 'repository':
        return ''
    lists = record.get('source_lists')
    if not isinstance(lists, list):
        return ''
    return ' / '.join(label for key, label in SOURCE_LISTS.items() if key in lists)
