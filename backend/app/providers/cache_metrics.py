"""Provider-reported input token metrics; local result reuse is not a hit."""
from collections import defaultdict

TARGET = 0.90
# Current RAG uses embedding; embed is the historical documented name. Do not
# infer from model names or exclude unfamiliar kinds: they may be real LLMs.
NON_LLM_KINDS = frozenset({'embedding', 'embed'})


def summarize_cache(rows) -> dict:
    rows = list(rows)
    reported = [r for r in rows if r.cache_usage_reported]
    inputs = sum(r.prompt_tokens for r in reported)
    cached = sum(r.cached_input_tokens for r in reported)
    invalid = sum(r.cached_input_tokens + r.cache_write_tokens > r.prompt_tokens for r in reported)
    rate = cached / inputs if inputs and not invalid else None
    complete = bool(rows) and len(reported) == len(rows) and not invalid
    return {
        'calls': len(rows),
        'reported_calls': len(reported),
        'unknown_calls': len(rows) - len(reported),
        'invalid_usage_calls': invalid,
        'reported_input_tokens': inputs,
        'cached_input_tokens': cached,
        'cache_write_tokens': sum(r.cache_write_tokens for r in reported),
        'input_token_hit_rate': rate,
        'reporting_coverage': len(reported) / len(rows) if rows else None,
        'target': TARGET,
        # An unreported gateway cannot earn a passing score from a subset.
        'target_met': rate >= TARGET if complete and rate is not None else None,
    }


def cache_diagnostics(rows) -> dict:
    rows = list(rows)
    llm_rows = [r for r in rows if r.request_kind not in NON_LLM_KINDS]
    excluded = [r for r in rows if r.request_kind in NON_LLM_KINDS]
    groups = defaultdict(list)
    excluded_groups = defaultdict(list)
    for row in llm_rows:
        groups[(row.provider_id, row.model, row.request_kind)].append(row)
    for row in excluded:
        excluded_groups[(row.provider_id, row.model, row.request_kind)].append(row)
    return {
        **summarize_cache(llm_rows),
        'scope': 'llm_provider_input_tokens_including_cold_calls',
        'all_recorded_calls': len(rows),
        'excluded_non_llm_calls': len(excluded),
        'excluded_non_llm_input_tokens': sum(r.prompt_tokens for r in excluded),
        'excluded_request_kinds': sorted(NON_LLM_KINDS),
        'excluded_by_provider_model_kind': [
            {'provider_id': provider, 'model': model, 'request_kind': kind,
             'calls': len(group), 'input_tokens': sum(r.prompt_tokens for r in group)}
            for (provider, model, kind), group in sorted(excluded_groups.items(), key=lambda item: str(item[0]))
        ],
        'by_provider_model_kind': [
            {'provider_id': provider, 'model': model, 'request_kind': kind, **summarize_cache(group)}
            for (provider, model, kind), group in sorted(groups.items(), key=lambda item: str(item[0]))
        ],
    }
