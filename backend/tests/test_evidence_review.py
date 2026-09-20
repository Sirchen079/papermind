from types import SimpleNamespace
import json
import pytest
from app.agent.evidence_review import apply_edits,review_answer

SOURCE=[{'id':'E1','text':'This abstract does not describe external evaluations.'}]
EDIT={'before':'没有做外部验证','after':'摘要未描述外部验证，是否做过未知','evidence_id':'E1','quote':'This abstract does not describe external evaluations.','reason':'否定范围扩大'}

def test_exact_edit_preserves_other_claims_and_citation():
    assert apply_edits('A 没有做外部验证。[S1] B 是 0.85。',{'edits':[EDIT]},SOURCE)=='A 摘要未描述外部验证，是否做过未知。[S1] B 是 0.85。'


def test_block_id_can_target_one_of_identical_lines_without_copying_text():
    edit={k:v for k,v in EDIT.items() if k!='before'}
    edit['block_id']='B2'
    assert apply_edits('没有做外部验证\n没有做外部验证',{'edits':[edit]},SOURCE)=='没有做外部验证\n'+EDIT['after']
    assert edit['before']=='没有做外部验证'


def test_unknown_block_id_rejected():
    with pytest.raises(ValueError,match='不存在'):
        apply_edits('text',{'edits':[{**EDIT,'block_id':'B999'}]},SOURCE)

@pytest.mark.parametrize('change',[{'before':'不存在的片段'},{'quote':'external validation was never done'},{'evidence_id':'E9'},{'after':''}])
def test_invalid_edits_do_not_change_draft(change):
    with pytest.raises(ValueError):
        apply_edits('A 没有做外部验证。',{'edits':[{**EDIT,**change}]},SOURCE)

def test_repeated_and_overlapping_anchors_rejected():
    with pytest.raises(ValueError):apply_edits('没有做外部验证，没有做外部验证',{'edits':[EDIT]},SOURCE)
    with pytest.raises(ValueError):apply_edits('没有做外部验证',{'edits':[EDIT,EDIT]},SOURCE)

def test_review_retries_format_once_and_records_changes():
    calls=[]
    def complete(*args,**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content='bad' if len(calls)==1 else json.dumps({'edits':[EDIT]},ensure_ascii=False),total_tokens=3)
    text,tokens,audit=review_answer(SimpleNamespace(complete=complete),None,'model','是否验证','没有做外部验证',[{'text':SOURCE[0]['text']}])
    assert text==EDIT['after'] and tokens==6 and len(calls)==2
    assert audit['edits']==[EDIT]
    assert audit['evidence_snapshots'][0]['text']==SOURCE[0]['text']

def test_failed_review_cannot_release_original_claim():
    with pytest.raises(ValueError,match='未发布'):
        review_answer(SimpleNamespace(complete=lambda *a,**k:SimpleNamespace(content='bad',total_tokens=1)),None,'m','q','bad claim',[{'text':'only source'}])


def test_agent_emits_only_source_checked_revision(monkeypatch):
    from app.agent.loop import run_agent
    monkeypatch.setattr('app.agent.loop.tool_schemas',lambda:[])
    client=SimpleNamespace(
        complete_with_tools=lambda *a,**k:SimpleNamespace(content='没有做外部验证',tool_calls=[],total_tokens=2),
        complete=lambda *a,**k:SimpleNamespace(content=json.dumps({'edits':[EDIT]},ensure_ascii=False),total_tokens=3))
    events=list(run_agent(client,None,'m',[{'role':'user','content':'是否验证'}],None,review_evidence=True,evidence_context=SOURCE[0]['text']))
    # Progress is observable, but only reviewed answer text may be emitted.
    assert any(kind == 'status' for kind, _ in events)
    answer_events = [(kind, body) for kind, body in events if kind != 'status']
    assert [kind for kind, _ in answer_events] == ['delta', 'done']
    assert all(body['content'] == EDIT['after'] for _, body in answer_events)
    assert events[-1][1]['tokens']==5
    assert events[-1][1]['evidence_review']['edits']==[EDIT]


def test_empty_budget_retry_uses_available_context_and_is_bounded():
    from app.agent.context import estimate_tokens
    limits=[]
    def complete(provider,model,messages,**kwargs):
        limits.append(kwargs['max_tokens'])
        assert estimate_tokens(''.join(m['content'] for m in messages))+kwargs['max_tokens']<16000
        return SimpleNamespace(content='' if len(limits)==1 else '{"edits":[]}',total_tokens=2,completion_tokens=limits[-1])
    assert review_answer(SimpleNamespace(complete=complete),None,'m','q','short draft',[{'text':'short original evidence'}])[0]=='short draft'
    assert len(limits)==2 and limits[0]<limits[1]<=12000


def test_partial_read_gets_one_completion_checkpoint_before_publication(monkeypatch):
    from app.agent.loop import run_agent
    from app.providers.client import ToolTurn
    calls=[]
    tool_call=SimpleNamespace(id='read1',name='get_paper_full_text',arguments={'paper_id':4})
    turns=iter([ToolTurn('',[tool_call],0,1,1),ToolTurn('当前片段缺少训练时间',[],0,1,1),
                ToolTurn('',[tool_call],0,1,1),ToolTurn('继续读取后训练时间为 12 小时',[],0,1,1)])
    def generate(*args,**kwargs):
        calls.append([dict(m) for m in args[2]])
        return next(turns)
    monkeypatch.setattr('app.agent.loop.tool_schemas',lambda:[{}])
    monkeypatch.setattr('app.agent.loop.get_tool',lambda name:SimpleNamespace(
        parameters={'properties':{'paper_id':{}}},run=lambda *a,**k:'{"text":"training time 12 hours","truncated":true}'))
    monkeypatch.setattr('app.agent.loop.tool_sources',lambda *a:[])
    client=SimpleNamespace(complete_with_tools=generate,complete=lambda *a,**k:SimpleNamespace(content='{"edits":[]}',total_tokens=1))
    events=list(run_agent(client,None,'m',[{'role':'user','content':'核对训练时间'}],None,review_evidence=True))
    assert events[-1][0]=='done' and '12 小时' in events[-1][1]['content']
    assert len([m for m in calls[-1] if '回答前检索完整性检查' in m.get('content','')])==1
    assert not any('当前片段缺少' in body.get('content','') for kind,body in events if kind in ('delta','done'))

@pytest.mark.parametrize('raw', ['{"edits":[]}', '```json\n{"edits":[]}\n```', '复核结果如下：\n{"edits":[]}\n以上为核对结果。'])
def test_review_accepts_json_wrappers(raw):
    from app.agent.evidence_review import parse_review_response
    assert parse_review_response(raw) == {'edits': []}


@pytest.mark.parametrize('raw', ['', 'not JSON', '{"edits":[', '{"edits":[]} {"edits":[{}]}'])
def test_review_does_not_guess_invalid_or_conflicting_json(raw):
    from app.agent.evidence_review import parse_review_response
    with pytest.raises(ValueError):
        parse_review_response(raw)


@pytest.mark.parametrize('failure', ['blank', 'format', 'timeout', 'invalid_edit', 'capacity'])
def test_chat_review_failure_preserves_answer_with_explicit_notice(monkeypatch, failure):
    from app.agent.loop import run_agent
    monkeypatch.setattr('app.agent.loop.tool_schemas', lambda: [])
    calls = []
    draft = '基于提供材料的回答。[S1]'
    def review(*args, **kwargs):
        calls.append(1)
        if failure == 'timeout':
            raise TimeoutError('private provider detail')
        raw = '' if failure == 'blank' else json.dumps({'edits': [{**EDIT, 'block_id': 'B999'}]}) if failure == 'invalid_edit' else 'bad JSON'
        return SimpleNamespace(content=raw, total_tokens=2)
    client = SimpleNamespace(complete_with_tools=lambda *a, **k: SimpleNamespace(content=draft, tool_calls=[], total_tokens=3), complete=review)
    events = list(run_agent(client, None, 'm', [{'role': 'user', 'content': 'q'}], None,
                            review_evidence=True, evidence_context=SOURCE[0]['text'], context_window=1000 if failure == 'capacity' else None))
    assert events[-1][0] == 'done'
    assert not any(kind == 'error' for kind, _ in events)
    result = events[-1][1]
    assert result['content'].endswith(draft)
    assert result['content'].startswith('> 自动证据复核未完成')
    assert 'private provider detail' not in result['content']
    assert result['evidence_review']['status'] == 'unavailable'
    assert result['evidence_review']['edits'] == []
    assert len(calls) <= 2


def test_stop_during_failed_review_still_stops_answer(monkeypatch):
    from threading import Event
    from app.agent.loop import run_agent
    stop = Event()
    def review(*a, **k):
        stop.set()
        raise TimeoutError('stopped')
    monkeypatch.setattr('app.agent.loop.review_answer', review)
    client = SimpleNamespace(complete_with_tools=lambda *a, **k: SimpleNamespace(content='draft', tool_calls=[], total_tokens=1))
    events = list(run_agent(client, None, 'm', [{'role': 'user', 'content': 'q'}], None, cancelled=stop, review_evidence=True, evidence_context='source'))
    assert events[-1][0] == 'error'
    assert not any(kind in {'delta', 'done'} for kind, _ in events)


def test_normal_chat_with_evidence_does_not_call_extra_reviewer(monkeypatch):
    from app.agent.loop import run_agent
    def forbidden(*a, **k):
        raise AssertionError('Normal chat must not enter independent review')
    monkeypatch.setattr('app.agent.loop.review_answer', forbidden)
    client = SimpleNamespace(complete_with_tools=lambda *a, **k: SimpleNamespace(content='可以先做这个假设，再设计实验验证。', tool_calls=[], total_tokens=1))
    events = list(run_agent(client, None, 'm', [{'role':'user','content':'讨论 idea'}], None, evidence_context='已有文献材料'))
    assert events[-1][0] == 'done'
    assert events[-1][1]['evidence_review'] is None
    assert events[-1][1]['content'] == '可以先做这个假设，再设计实验验证。'
    assert not any(kind == 'status' and body.get('phase') == 'review' for kind, body in events)


def test_normal_partial_read_does_not_force_another_model_round(monkeypatch):
    from app.agent.loop import run_agent
    from app.providers.client import ToolTurn
    call = SimpleNamespace(id='read', name='get_paper_full_text', arguments={})
    turns = iter([ToolTurn('', [call], 0, 1, 1), ToolTurn('基于这段材料可以尝试以下思路。', [], 0, 1, 1)])
    monkeypatch.setattr('app.agent.loop.get_tool', lambda name: SimpleNamespace(parameters={}, run=lambda *a, **k:'{"text":"excerpt","truncated":true}'))
    monkeypatch.setattr('app.agent.loop.tool_sources', lambda *a: [])
    client = SimpleNamespace(complete_with_tools=lambda *a, **k: next(turns))
    events = list(run_agent(client, None, 'm', [{'role':'user','content':'从这段启发几个 idea'}], None))
    assert events[-1][0] == 'done'
    assert events[-1][1]['content'] == '基于这段材料可以尝试以下思路。'
