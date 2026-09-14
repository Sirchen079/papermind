import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlmodel import Session, select
from app.db.engine import get_engine
from app.models import AIResultCache, Paper, Provider, TokenUsage
from app.providers.prompt_cache import cache_usage, prepare_messages
from app.providers.client import ProviderClient
from app.research import cache, service


def test_provider_cache_accounting_formats_and_unknown():
    assert cache_usage({'prompt_tokens_details': {'cached_tokens': 700}, 'cache_creation_input_tokens': 120}) == (700, 120, True)
    assert cache_usage(SimpleNamespace(input_tokens_details=SimpleNamespace(cached_tokens=500))) == (500, 0, True)
    assert cache_usage({'cache_read_input_tokens': 250}) == (250, 0, True)
    assert cache_usage({'prompt_cache_hit_tokens': 340}) == (340, 0, True)
    assert cache_usage({'prompt_tokens_details': {'cached_tokens': 0}}) == (0, 0, True)
    assert cache_usage({'prompt_tokens': 2000}) == (0, 0, False)


def test_stable_material_prefix_across_questions_and_no_gateway_parameters():
    payload = {'material': {'evidence': [{'quote': 'shared source ' * 1000}]}, 'question': 'Question A'}
    original = [{'role': 'system', 'content': 'System'}, {'role': 'user', 'content': json.dumps(payload)}]
    before = deepcopy(original)
    a = prepare_messages(original, 'anthropic', 'research')
    payload['question'] = 'Question B'
    b = prepare_messages([original[0], {'role': 'user', 'content': json.dumps(payload)}], 'anthropic', 'research')
    assert a[1]['content'][0] == b[1]['content'][0]
    assert a[1]['content'][0]['cache_control'] == {'type': 'ephemeral'}
    assert a[1]['content'][1] != b[1]['content'][1]
    assert original == before  # no history mutations or cached question leaking
    compatible = prepare_messages(original, 'openai_compat', 'research')
    assert isinstance(compatible[1]['content'], str)
    assert 'cache_control' not in compatible[1]['content']
    assert compatible[1]['content'].index('shared source') < compatible[1]['content'].index('Question A')


def test_tool_sequence_preserved_and_cache_breakpoints_bounded():
    messages = [{'role':'system','content':'system ' * 1000}, {'role':'user','content':'paper ' * 2000}, {'role':'assistant','content':'', 'tool_calls':[{'id':'call1'}]}, {'role':'tool','tool_call_id':'call1','content':'result ' * 2000}, {'role':'user','content':'continue'}]
    result = prepare_messages(messages, 'anthropic', 'chat')
    assert result[2] == messages[2]
    assert result[3]['tool_call_id'] == 'call1'
    assert result[-1]['content'][0]['text'] == 'continue'
    assert 'cache_control' in result[-1]['content'][0]
    assert sum('cache_control' in b for m in result for b in (m['content'] if isinstance(m['content'],list) else [])) <= 3


def test_first_request_user_anchor_survives_tool_roundtrips():
    from app.providers.prompt_cache import prepare_tools, cache_options
    history = [{'role':'system','content':'rules'}, {'role':'user','content':'source ' * 2000}]
    first = prepare_messages(history, 'anthropic', 'chat')
    next_round = prepare_messages(history + [{'role':'assistant','content':'','tool_calls':[{'id':'c'}]}, {'role':'tool','tool_call_id':'c','content':'result'}], 'anthropic', 'chat')
    assert first == next_round[:2]
    assert first[-1]['content'][-1]['cache_control'] == {'type':'ephemeral'}
    tools = [{'type':'function','function':{'name':'lookup','parameters':{'type':'object'}}}]
    assert prepare_tools(tools, first, 'anthropic')[-1]['cache_control'] == {'type':'ephemeral'}
    assert 'cache_control' not in tools[-1]
    assert prepare_tools(tools, first, 'openai_compat') == tools
    key = cache_options('openai_chat', None, 'chat', history)
    assert key and key == cache_options('openai_chat', 'https://api.openai.com/v1', 'chat', history + [{'role':'user','content':'next'}])
    assert cache_options('openai_responses', 'https://open.bigmodel.cn/api/paas/v4/', 'chat', history) == {}
    assert cache_usage({'input_tokens_details':{'cache_write_tokens':50}}) == (0,50,True)


def test_chat_prefix_survives_library_and_retrieval_changes(client):
    from app.api.chat_api import _build_messages
    from app.models import Conversation, Message, PaperChunk
    with Session(get_engine()) as session:
        conv = Conversation(); paper = Paper(source='manual',title='Original')
        session.add(conv); session.add(paper); session.commit()
        first = Message(conversation_id=conv.id,role='user',content='first question')
        session.add(first);session.commit()
        chunk = PaperChunk(paper_id=paper.id,text='first retrieval')
        a = _build_messages(session,conv,first.content,[(chunk,1.,paper)],current_message_id=first.id)
        session.add(Message(conversation_id=conv.id,role='assistant',content='answer'))
        second = Message(conversation_id=conv.id,role='user',content='second question')
        session.add(second); paper.title='Changed title';session.add(paper);session.commit()
        chunk.text='different retrieval'
        b = _build_messages(session,conv,second.content,[(chunk,1.,paper)],current_message_id=second.id)
        assert b[:len(a)] == a
        assert 'different retrieval' in b[-1]['content']
        assert 'first retrieval' in b[1]['content']
        cid = conv.id
    visible = client.get(f'/api/chat/conversations/{cid}').json()['messages']
    assert visible[0]['content'] == 'first question'
    assert 'model_context' not in visible[0]


def setup_research(client, monkeypatch):
    with Session(get_engine()) as session:
        provider = Provider(name='Synthetic', type='openai_chat')
        paper = Paper(source='manual',title='Synthetic caching fixture',full_text='Method A uses split S1. No experiment was executed.')
        session.add(provider);session.add(paper);session.commit();session.refresh(provider);session.refresh(paper)
        paper_id = paper.id
    calls = []
    def complete(p, model, messages, **kwargs):
        calls.append(messages)
        payload = json.loads(messages[1]['content'])
        evidence = payload.get('material',{}).get('evidence') or payload['materials'][0]['evidence']
        return SimpleNamespace(content=json.dumps({'answer':'Candidate answer', 'evidence_refs':[evidence[0]['ref']], 'unknowns':[], 'route':'continue','next_step':'Check source'}), cached_input_tokens=123, cache_usage_reported=True)
    monkeypatch.setattr(service, 'pick_llm', lambda *args:(SimpleNamespace(complete=complete),provider,'synthetic-model'))
    def run(question='Compare method conditions'):
        created = client.post('/api/research/tasks', json={'request_id':str(uuid4()),'question':question,'paper_ids':[paper_id],'depth':'evidence'})
        assert created.status_code == 201, created.text
        task_id = created.json()['id']
        assert client.post('/api/research/tasks/'+task_id+'/run').status_code == 202
        return client.get('/api/research/tasks/'+task_id).json()
    return run, calls, paper_id


def test_completed_steps_reused_across_tasks_and_source_changes_invalidate(client, monkeypatch):
    run, calls, paper_id = setup_research(client, monkeypatch)
    first = run(); assert first['status'] == 'ready', first
    assert len(calls) == 2
    second = run(); assert second['cache_summary']['local_reused_steps'] == 2
    assert second['cache_summary']['api_calls'] == 0
    assert second['cache_summary']['cached_input_tokens'] == 0
    assert len(calls) == 2
    run('A different research question'); assert len(calls) == 4
    with Session(get_engine()) as session:
        paper = session.get(Paper,paper_id);paper.full_text += ' Updated source.';session.add(paper);session.commit()
    run(); assert len(calls) == 6


def test_cache_expiration_protocol_model_and_corrupt_values(client, monkeypatch):
    run, calls, _ = setup_research(client, monkeypatch)
    run()
    with Session(get_engine()) as session:
        for row in session.exec(select(AIResultCache)).all():
            row.created_at = datetime.now(timezone.utc)-timedelta(days=8);session.add(row)
        session.commit()
    run(); assert len(calls) == 4
    with Session(get_engine()) as session:
        for row in session.exec(select(AIResultCache)).all():
            row.result_json = '{"answer":"bad","evidence_refs":["NONEXISTENT"]}';session.add(row)
        session.commit()
    run(); assert len(calls) == 6
    p = Provider(id=1,type='openai_chat',name='a')
    base = cache.cache_key(p,'model','prompt','system')
    assert base != cache.cache_key(p,'other','prompt','system')
    p.base_url = 'https://example.com/v1'
    assert base != cache.cache_key(p,'model','prompt','system')


def test_usage_endpoint_distinguishes_zero_unknown_and_writes(client):
    with Session(get_engine()) as session:
        provider = Provider(name='cache-test',type='anthropic');session.add(provider);session.commit();session.refresh(provider)
    pc = ProviderClient(lambda:Session(get_engine()),None)
    pc._record_usage(provider,'synthetic','research',None,2000,100,2100,usage={'prompt_tokens_details':{'cached_tokens':1500},'cache_creation_input_tokens':200})
    pc._record_usage(provider,'synthetic','chat',None,200,20,220,usage=None)
    result = client.get('/api/usage').json()
    assert result['cached_input_tokens'] == 1500
    assert result['cache_write_tokens'] == 200
    assert result['cache_reported_calls'] == 1
    assert result['cache_reported_input_tokens'] == 2000
    assert result['call_count'] == 2
    assert result['total_tokens'] == 2320  # hits are billed input, not zero tokens


def test_concurrent_identical_research_does_not_double_call(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    run, calls, _ = setup_research(client, monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert all(r['status'] == 'ready' for r in results), results
    assert len(calls) == 2
    assert sum(r['cache_summary']['local_reused_steps'] for r in results) == 2


def test_embedding_cache_deduplicates_and_invalidates_model(client, monkeypatch):
    with Session(get_engine()) as session:
        provider = Provider(name='vectors',type='openai_chat');session.add(provider);session.commit();session.refresh(provider)
    sent = []
    def embed(**kwargs):
        sent.append(kwargs['input'])
        return SimpleNamespace(data=[{'embedding':[len(text),1.0]} for text in kwargs['input']],usage=SimpleNamespace(prompt_tokens=20,total_tokens=20))
    monkeypatch.setattr('app.providers.client.litellm.embedding', embed)
    pc = ProviderClient(lambda:Session(get_engine()),None)
    assert pc.embed(provider,'vector-v1',['paper A','paper A','paper B']) == [[7,1],[7,1],[7,1]]
    assert sent == [['paper A','paper B']]
    pc.embed(provider,'vector-v1',['paper B','paper A'])
    assert len(sent) == 1
    pc.embed(provider,'vector-v2',['paper A'])
    assert len(sent) == 2
    pc.embed(provider,'vector-v1',['updated paper'])
    assert len(sent) == 3
    with Session(get_engine()) as session:
        assert len(session.exec(select(TokenUsage)).all()) == 3


def test_no_partial_embedding_cache_after_invalid_response(client, monkeypatch):
    import pytest
    with Session(get_engine()) as session:
        provider=Provider(name='vectors',type='openai_chat');session.add(provider);session.commit();session.refresh(provider)
    monkeypatch.setattr('app.providers.client.litellm.embedding',lambda **kwargs:SimpleNamespace(data=[{'embedding':[1.,2.]}],usage=None))
    pc=ProviderClient(lambda:Session(get_engine()),None)
    with pytest.raises(ValueError):
        pc.embed(provider,'vector-v1',['one','two'])
    with Session(get_engine()) as session:
        assert session.exec(select(AIResultCache)).first() is None
