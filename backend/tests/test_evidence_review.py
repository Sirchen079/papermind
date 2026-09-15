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
    events=list(run_agent(client,None,'m',[{'role':'user','content':'是否验证'}],None,evidence_context=SOURCE[0]['text']))
    assert [kind for kind,_ in events]==['delta','done']
    assert all(body['content']==EDIT['after'] for _,body in events)
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
    events=list(run_agent(client,None,'m',[{'role':'user','content':'核对训练时间'}],None))
    assert events[-1][0]=='done' and '12 小时' in events[-1][1]['content']
    assert len([m for m in calls[-1] if '回答前检索完整性检查' in m.get('content','')])==1
    assert not any('当前片段缺少' in body.get('content','') for kind,body in events if kind in ('delta','done'))
