import json
from copy import deepcopy
from types import SimpleNamespace as NS

from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Provider, TokenUsage
from app.providers.cache_metrics import cache_diagnostics
from app.providers.client import ProviderClient
from app.providers.prompt_cache import cache_usage, marker_count, prepare_messages, prepare_tools, token_usage


def test_ingest_summary_and_concepts_share_bounded_source_and_preserve_schemas():
    from app.ai_ops.summarize import summarize_paper
    from app.ai_ops.concepts import extract_concepts
    calls = []
    def complete(provider, model, messages, **kwargs):
        calls.append(messages)
        return NS(content='{"problem":"p","method":"m","dataset":"d","results":"r","limitations":"l"}' if len(calls) == 1 else '[{"name":"n","type":"method","evidence":"e"}]')
    client = NS(complete=complete)
    full = 'source ' * 2000
    assert summarize_paper(client, None, 'm', 'Title', 'Abstract', full)['method'] == 'm'
    assert extract_concepts(client, None, 'm', 'Title', 'Abstract', full)[0]['type'] == 'method'
    assert calls[0][:2] == calls[1][:2]
    assert calls[0][-1] != calls[1][-1]
    assert calls[0][1]['content'].endswith(full[:8000])
    assert len(calls[0][1]['content']) < 8100
    a, b = [prepare_messages(messages, 'anthropic', 'ingest', marker_budget=4) for messages in calls]
    assert a[1] == b[1]
    assert a[1]['content'][-1]['cache_control'] == {'type': 'ephemeral'}


def test_single_paper_extraction_and_synthesis_share_exact_prefix():
    paper = {'paper_id': 7, 'evidence': [{'ref': 'E7.1', 'quote': '真实材料' * 900}]}
    for provider in ('anthropic', 'openai_chat', 'openai_compat', 'openai_responses'):
        a = prepare_messages([{'role': 'user', 'content': json.dumps({'material': paper, 'question': '抽取方法'})}], provider, 'research')
        b = prepare_messages([{'role': 'user', 'content': json.dumps({'materials': [paper], 'question': '评测限制', 'paper_findings': {'7': '已抽取的方法'}})}], provider, 'research')
        if provider == 'anthropic':
            assert a[0]['content'][0] == b[0]['content'][0]
            assert 'cache_control' in a[0]['content'][0]
            assert a[0]['content'][1] != b[0]['content'][1]
        else:
            assert a[0]['content'].split('\n本次任务：')[0] == b[0]['content'].split('\n本次任务：')[0]


def test_chinese_context_boundary_does_not_depend_on_8192_char_heuristic():
    # CJK can exceed a provider's token minimum with far fewer than 8192 chars.
    context = '论文中评测数据与方法的完整摘录。' * 100
    first = [{'role': 'user', 'content': context + '\n\n[本轮用户问题]\n问题一'}]
    second = [{'role': 'user', 'content': context + '\n\n[本轮用户问题]\n问题二'}]
    before = deepcopy(first)
    a, b = [prepare_messages(m, 'anthropic', 'chat') for m in (first, second)]
    assert a[0]['content'][0] == b[0]['content'][0]
    assert a[0]['content'][0]['cache_control'] == {'type': 'ephemeral'}
    assert ''.join(block['text'] for block in a[0]['content']) == first[0]['content']
    assert first == before


def test_previous_user_checkpoint_survives_more_than_twenty_blocks():
    first = [{'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'source ' * 1500}]
    a = prepare_messages(first, 'anthropic', 'chat')
    # A long response or externally supplied content blocks can exceed lookback.
    long_answer = {'role': 'assistant', 'content': [{'type': 'text', 'text': f'part {i}'} for i in range(25)]}
    b = prepare_messages(first + [long_answer, {'role': 'user', 'content': 'next'}], 'anthropic', 'chat')
    assert a[1] == b[1]  # Explicit previous write survives outside lookback.
    assert b[2] == long_answer
    assert marker_count(b) <= 3


def test_tool_checkpoint_and_manual_budget_do_not_mutate_history():
    tools = [{'type': 'function', 'function': {'name': 'read'}, 'cache_control': {'type': 'ephemeral'}}]
    history = [{'role': 'user', 'content': 'paper ' * 1500}, {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'a'}]}, {'role': 'tool', 'tool_call_id': 'a', 'content': 'result ' * 1500}]
    prepared = prepare_messages(history, 'anthropic', 'chat', marker_budget=3)
    assert prepared[-1]['content'][-1]['cache_control'] == {'type': 'ephemeral'}
    assert prepared[-1]['tool_call_id'] == 'a'
    assert marker_count(prepared) + marker_count(prepare_tools(tools, prepared, 'anthropic')) <= 4
    assert isinstance(history[-1]['content'], str)


def test_token_normalization_handles_raw_claude_and_normalized_litellm_without_double_count():
    raw = {'input_tokens': 100, 'output_tokens': 20, 'cache_read_input_tokens': 900, 'cache_creation_input_tokens': 100}
    assert token_usage(raw) == (1100, 20, 1120)
    assert token_usage({**raw, 'prompt_tokens': 1100, 'completion_tokens': 20, 'total_tokens': 1120}) == (1100, 20, 1120)
    assert token_usage({'input_tokens': 1100, 'output_tokens': 20, 'input_tokens_details': {'cached_tokens': 900}}) == (1100, 20, 1120)
    assert cache_usage({'prompt_cache_hit_tokens': float('nan'), 'cache_creation_input_tokens': float('inf')}) == (0, 0, False)


def test_stream_preserves_early_cache_usage_when_final_chunk_has_only_output(client, monkeypatch):
    with Session(get_engine()) as session:
        provider = Provider(name='fixture', type='anthropic')
        session.add(provider); session.commit(); session.refresh(provider)
    chunks = [
        NS(choices=[], usage={'input_tokens': 100, 'cache_read_input_tokens': 1900}),
        NS(choices=[NS(delta=NS(content='answer'))], usage=None),
        NS(choices=[], usage={'output_tokens': 20}),
    ]
    monkeypatch.setattr('app.providers.client.litellm.completion', lambda **kwargs: iter(chunks))
    pc = ProviderClient(lambda: Session(get_engine()), None)
    events = list(pc.stream_complete(provider, 'fixture', [{'role': 'user', 'content': 'q'}], 'chat'))
    assert events[-1].prompt_tokens == 2000
    assert events[-1].total_tokens == 2020
    with Session(get_engine()) as session:
        row = session.exec(select(TokenUsage)).one()
        assert row.cached_input_tokens == 1900
        assert row.cache_usage_reported


def test_diagnostics_require_full_reporting_and_use_token_weighting():
    def row(tokens, hits, known=True, model='m'):
        return NS(provider_id=1, model=model, request_kind='chat', prompt_tokens=tokens,
                  cached_input_tokens=hits, cache_write_tokens=0, cache_usage_reported=known)
    result = cache_diagnostics([row(1000, 0), row(19000, 19000)])
    assert result['input_token_hit_rate'] == .95  # Includes the cold request.
    assert result['target_met'] is True
    result = cache_diagnostics([row(1000, 950), row(5000, 0, False, 'gateway')])
    assert result['input_token_hit_rate'] == .95
    assert result['unknown_calls'] == 1
    assert result['target_met'] is None
    assert len(result['by_provider_model_kind']) == 2
    assert cache_diagnostics([])['input_token_hit_rate'] is None
    assert cache_diagnostics([row(100, 200)])['target_met'] is None


def test_llm_diagnostics_exclude_only_known_embedding_kinds_and_keep_unknown_llms():
    def row(kind, known, hits=0):
        return NS(provider_id=1, model=kind, request_kind=kind, prompt_tokens=1000,
                  cached_input_tokens=hits, cache_write_tokens=0, cache_usage_reported=known)
    base = [row('chat', True, 950), row('embedding', False), row('embed', False)]
    result = cache_diagnostics(base)
    assert result['calls'] == 1
    assert result['unknown_calls'] == 0
    assert result['target_met'] is True
    assert result['all_recorded_calls'] == 3
    assert result['excluded_non_llm_calls'] == 2
    assert result['excluded_non_llm_input_tokens'] == 2000
    assert len(result['excluded_by_provider_model_kind']) == 2
    result = cache_diagnostics(base + [row('new_custom_llm_kind', False)])
    assert result['unknown_calls'] == 1
    assert result['reporting_coverage'] == .5
    assert result['target_met'] is None
    assert len(result['by_provider_model_kind']) == 2
    assert cache_diagnostics([row('embedding', False)])['target_met'] is None


def test_multi_paper_material_blocks_preserve_first_paper_cache_prefix():
    paper = {'paper_id': 1, 'evidence': [{'quote': 'source ' * 1500}]}
    other = {'paper_id': 2, 'evidence': [{'quote': 'other source ' * 1500}]}
    first = prepare_messages([{'role': 'user', 'content': json.dumps({'material': paper, 'question': 'Extract'})}], 'anthropic', 'research')
    combined = prepare_messages([{'role': 'user', 'content': json.dumps({'materials': [paper, other], 'question': 'Compare'})}], 'anthropic', 'research')
    assert first[0]['content'][0]['text'] == combined[0]['content'][0]['text']
    assert combined[0]['content'][1]['cache_control'] == {'type': 'ephemeral'}
    assert combined[0]['content'][1]['text'].endswith(json.dumps(other, ensure_ascii=False, sort_keys=True))
    assert marker_count(combined) <= 4


def test_offline_mixed_workload_keeps_cold_calls_and_reports_low_reuse_controls():
    from scripts.audit_prompt_cache import simulation
    result = simulation(calls=2)
    scenarios = {s['scenario']: s for s in result['scenarios']}
    assert scenarios['short_one_off_requests']['cold_inclusive_simulated_rate'] == 0
    assert 0 < scenarios['four_paper_two_step_import']['cold_inclusive_simulated_rate'] < .5
    assert scenarios['four_paper_research']['calls'] == 5
    mixed = result['mixed_graduate_workload']
    assert mixed['calls'] == 25
    assert mixed['requests'][0]['estimated_cached_tokens'] == 0
    assert mixed['estimated_input_tokens'] == sum(r['estimated_input_tokens'] for r in mixed['requests'])
    assert mixed['cold_inclusive_simulated_rate'] < .90


def test_audit_reads_only_usage_and_does_not_modify_database(tmp_path):
    import hashlib
    import sqlite3
    from datetime import date
    from scripts.audit_prompt_cache import audit_database
    path = tmp_path / 'usage.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE tokenusage (provider_id, model, request_kind, prompt_tokens, cached_input_tokens, cache_write_tokens, cache_usage_reported, day)')
        db.execute('INSERT INTO tokenusage VALUES (1, "fixture", "chat", 1000, 950, 0, 1, ?)', (date.today().isoformat(),))
    before = hashlib.sha256(path.read_bytes()).digest()
    result = audit_database(path, 30)
    assert result['input_token_hit_rate'] == .95
    assert 'TEST_FIXTURE' in result['evidence']
    assert before == hashlib.sha256(path.read_bytes()).digest()


def test_litellm_anthropic_wire_retains_material_boundary_and_normalized_totals(client, monkeypatch):
    """Exercise real SDK transformation against an intercepted HTTP response."""
    import respx
    from app.ai_ops.paper_prompt import paper_messages
    with Session(get_engine()) as session:
        provider = Provider(name='wire fixture', type='anthropic')
        session.add(provider); session.commit(); session.refresh(provider)
    pc = ProviderClient(lambda: Session(get_engine()), None)
    monkeypatch.setattr(pc, '_api_key', lambda p: 'test-key-not-a-real-credential')
    messages = paper_messages('Fixture', 'Abstract', 'evidence ' * 1000, 'Return JSON.')
    with respx.mock(assert_all_called=True) as http:
        route = http.post('https://api.anthropic.com/v1/messages').respond(200, json={
            'id': 'msg_fixture', 'type': 'message', 'role': 'assistant',
            'content': [{'type': 'text', 'text': '{}'}],
            'model': 'claude-sonnet-4-20250514', 'stop_reason': 'end_turn', 'stop_sequence': None,
            'usage': {'input_tokens': 100, 'output_tokens': 10, 'cache_read_input_tokens': 1900, 'cache_creation_input_tokens': 0},
        })
        result = pc.complete(provider, 'claude-sonnet-4-20250514', messages, 'ingest')
        wire = json.loads(route.calls.last.request.content)
    blocks = [b for m in wire['messages'] for b in m['content']]
    assert any(b.get('text') == messages[1]['content'] and b.get('cache_control') == {'type': 'ephemeral'} for b in blocks)
    assert marker_count(wire) <= 4
    assert result.prompt_tokens == 2000
    assert result.cached_input_tokens == 1900
    assert result.total_tokens == 2010
