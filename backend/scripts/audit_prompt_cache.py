"""Offline prefix experiment or read-only audit of provider-reported usage.

No API calls, key access, paid prewarming, or response-cache hits in metrics.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.providers.cache_metrics import cache_diagnostics
from app.providers.prompt_cache import prepare_messages


def simulate_workload(requests, tokenizer):
    """Explicit-boundary, 20-block lookback simulator; never a provider probe."""
    written = set()
    records = []
    for label, kind, messages in requests:
        prepared = prepare_messages(messages, 'anthropic', kind, marker_budget=4)
        prefix = ''
        prefixes, checkpoints = [], []
        for message in prepared:
            prefix += '\n' + message['role'] + '\n'
            body = message['content']
            blocks = body if isinstance(body, list) else [{'text': body}]
            for block in blocks:
                prefix += block['text']
                prefixes.append(prefix)
                if 'cache_control' in block:
                    checkpoints.append(len(prefixes)-1)
        # Real Claude checks up to 20 block prefixes per explicit breakpoint.
        candidates = {prefixes[j] for index in checkpoints for j in range(max(0, index-19), index+1)}
        hit = max((len(tokenizer.encode(p)) for p in candidates if p in written), default=0)
        # 1024 is a simulator setting, not a promise for every Claude model.
        written.update(prefixes[i] for i in checkpoints if len(tokenizer.encode(prefixes[i])) >= 1024)
        records.append({'label': label, 'request_kind': kind,
                        'estimated_input_tokens': len(tokenizer.encode(prefix)),
                        'estimated_cached_tokens': hit})
    total_input = sum(r['estimated_input_tokens'] for r in records)
    hits = sum(r['estimated_cached_tokens'] for r in records)
    later_input = sum(r['estimated_input_tokens'] for r in records[1:])
    return {'calls': len(records), 'estimated_input_tokens': total_input,
            'estimated_cached_tokens': hits,
            'cold_inclusive_simulated_rate': hits/total_input if total_input else None,
            'after_first_call_simulated_rate': sum(r['estimated_cached_tokens'] for r in records[1:])/later_input if later_input else None,
            'requests': records}


def simulation(calls=20):
    """Synthetic microbenchmarks plus a bounded mixed graduate workflow.

    No paid calls; no artificial material is added to the product. The mixed
    workload includes one-off/short work, two-call imports, different papers,
    and growing history. Its proportions are explicit, not measured user usage.
    """
    import tiktoken
    from app.ai_ops.paper_prompt import paper_messages
    from app.ai_ops.summarize import _SUMMARY_PROMPT
    from app.ai_ops.concepts import _EXTRACT_PROMPT
    from app.research.service import SYSTEM_PROMPT
    tokenizer = tiktoken.get_encoding('cl100k_base')
    source = '\n'.join(
        f'Synthetic section {i}: We compare retrieval baselines under a fixed evaluation split. '
        'This fixture contains no real experiment results. The method encodes documents and reranks candidates.'
        for i in range(140)
    )
    paper = {'paper_id': 7, 'title': 'Synthetic cache fixture', 'evidence': [{'ref': 'E7.1', 'quote': source}]}
    def research(payload):
        return [{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': json.dumps(payload)}]
    workloads = {}
    for scenario in ('research_extraction_synthesis', 'same_context_distinct_questions', 'changing_source_control'):
        requests = []
        for i in range(calls):
            if scenario == 'research_extraction_synthesis':
                payload = {'question': f'Question {i}: explain condition {i}', 'material' if i % 2 == 0 else 'materials': paper if i % 2 == 0 else [paper]}
                messages, kind = research(payload), 'research'
            else:
                context = source if scenario != 'changing_source_control' else f'Revised source {i}\n' + source
                messages = [{'role': 'system', 'content': 'Read supplied evidence; never invent results.'}, {'role': 'user', 'content': context + f'\n\n[本轮用户问题]\nExplain condition {i}.'}]
                kind = 'chat'
            requests.append((f'question_{i+1}', kind, messages))
        workloads[scenario] = requests
    workloads['short_one_off_requests'] = [
        (f'short_{i+1}', 'chat', [{'role': 'system', 'content': 'Answer briefly.'}, {'role': 'user', 'content': f'Explain research term {i}.'}]) for i in range(6)
    ]
    # Four newly imported papers, exactly one summary + concepts request each.
    # Product helper applies its normal 8000-character cap, not padded prompts.
    imports = []
    papers = []
    for i in range(4):
        body = f'Document {i}: distinct source.\n' + source[:7500]
        for task_name, task in [('summary', _SUMMARY_PROMPT), ('concepts', _EXTRACT_PROMPT)]:
            imports.append((f'paper_{i+1}_{task_name}', 'ingest', paper_messages(f'Paper {i+1}', 'Synthetic abstract.', body, task)))
        papers.append({'paper_id': i+1, 'title': f'Paper {i+1}', 'evidence': [
            {'ref': f'E{i+1}.{j//1800+1}', 'quote': body[j:j+1800]} for j in range(0, len(body), 1800)
        ]})
    workloads['four_paper_two_step_import'] = imports
    # All four per-paper extractions followed by one synthesis, a fresh task.
    multi = [(f'extract_paper_{i+1}', 'research', research({'material': p, 'question': 'Compare evaluation conditions.', 'task': 'Extract grounded evidence.'})) for i, p in enumerate(papers)]
    multi.append(('synthesize_four_papers', 'research', research({'materials': papers, 'question': 'Compare evaluation conditions.', 'paper_findings': {str(i+1): 'Synthetic condition summary.' for i in range(4)}})))
    workloads['four_paper_research'] = multi
    # Six rounds in one conversation, appending new user context and answers.
    history = [{'role': 'system', 'content': 'Read supplied evidence; never invent results.'}]
    growing = []
    from copy import deepcopy
    for i in range(6):
        context = source[:6500] if i == 0 else f'New retrieved source for turn {i}: ' + source[i*150:i*150+900]
        history.append({'role': 'user', 'content': context + f'\n\n[本轮用户问题]\nExplain condition {i}.'})
        growing.append((f'conversation_turn_{i+1}', 'chat', deepcopy(history)))
        history.append({'role': 'assistant', 'content': f'Answer {i}: ' + ('Synthetic explanation with limitations. ' * 35)})
    workloads['six_turn_growing_history'] = growing
    # Same cache lifecycle across all 25 calls. No per-scenario warming; report
    # token-weighted combined outcome, not the average of scenario percentages.
    mixed = (workloads['short_one_off_requests'] + imports + multi + growing)
    results = [{'scenario': name, **simulate_workload(requests, tokenizer)} for name, requests in workloads.items()]
    return {
        'evidence': 'OFFLINE_SIMULATION_NOT_PROVIDER_HIT_RATE',
        'tokenizer': 'cl100k_base estimate, not Claude billing tokens',
        'assumptions': {'minimum_estimated_tokens': 1024, 'lookback_blocks': 20,
                        'ttl_eviction_modeled': False, 'provider_routing_modeled': False,
                        'workload_distribution': 'synthetic explicit composition, not measured user frequency'},
        'scenarios': results,
        'mixed_graduate_workload': simulate_workload(mixed, tokenizer),
    }


def audit_database(path, days):
    path = Path(path).resolve(strict=True)
    since = (datetime.now(timezone.utc).date() - timedelta(days=days-1)).isoformat()
    # No migration, app startup, credential access, or write connection.
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT provider_id, model, request_kind, prompt_tokens, cached_input_tokens, cache_write_tokens, cache_usage_reported FROM tokenusage WHERE day >= ?', (since,)).fetchall()
    return {'evidence': 'RECORDED_USAGE_ONLY_VERIFY_DATABASE_IS_NOT_A_TEST_FIXTURE', 'since': since,
            **cache_diagnostics([SimpleNamespace(**dict(row)) for row in rows])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--simulate', action='store_true')
    source.add_argument('--database', type=Path)
    parser.add_argument('--days', type=int, default=30, choices=range(1, 366), metavar='1..365')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = simulation() if args.simulate else audit_database(args.database, args.days)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + '\n', encoding='utf-8')
    else:
        print(rendered)


if __name__ == '__main__':
    main()
