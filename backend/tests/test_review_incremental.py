import json
from types import SimpleNamespace
from sqlmodel import Session,select
from app.db.engine import get_engine
from app.models import Paper
from app.models.review import ReviewSection
from app.reviews import continuation,incremental
from app.reviews.editing import replace_blocks,blocks
from test_library_reviews import setup


def targets(text):
    return json.loads(text.split('目标段落：\n',1)[1].split('\n',1)[0])


def add_paper(client,prefix):
    with Session(get_engine()) as s:
        p=Paper(source='manual',title='New delta only',abstract='A new result with explicit experimental conditions.')
        s.add(p);s.commit();pid=p.id
    assert client.post(prefix+'/papers',json={'paper_ids':[pid]}).status_code==200
    return pid


def test_added_paper_updates_only_target_paragraph_and_reuses_the_rest(client,monkeypatch):
    prefix,fake,ids=setup(client,monkeypatch,count=2);client.post(prefix+'/run')
    current=client.get(prefix).json()
    original='# 研究者自定标题\n\n## 保留章节\n\n同一段😀 [P1]。\n\n同一段😀 [P1]。\n\n结尾已核对：未报告不等于未执行 [P2]。'
    client.post(prefix+'/content',json={'content':original,'expected_version':current['version']})
    pid=add_paper(client,prefix);prior=fake.complete;seen=[]
    replacement=f'只有第二处更新，补充有条件的新结果 [P{pid}]。'
    def complete(provider,model,messages,**kwargs):
        text=messages[-1]['content']
        if '仅返回需要修改的段落' in text:
            seen.append(text);chosen=[b for b in targets(text) if b['text']=='同一段😀 [P1]。'][1]
            assert f'[P{pid}]' in text and 'New delta only' in text
            return SimpleNamespace(content=json.dumps({'edits':[{'block_id':chosen['id'],'replacement':replacement,'reason':'新证据补充第二处。'}]},ensure_ascii=False))
        assert '只写当前章节' not in text and '只输出标题列表' not in text
        return prior(provider,model,messages,**kwargs)
    monkeypatch.setattr(fake,'complete',complete)
    client.post(prefix+'/run');result=client.get(prefix).json()
    start=original.rindex('同一段😀 [P1]。')
    expected=original[:start]+replacement+original[start+len('同一段😀 [P1]。'):]
    assert result['content'].startswith(expected+'\n\n## 引用文献')
    assert len(seen)==1 and result['counts']['reused']==2 and not result['error']
    assert '本次更新 1 处' in result['writing_notes']
    count=len(seen);client.post(prefix+'/run');assert len(seen)==count


def test_partial_patch_keeps_valid_edit_and_pending_delta_survives_retry(client,monkeypatch):
    prefix,fake,ids=setup(client,monkeypatch,count=1);client.post(prefix+'/run');pid=add_paper(client,prefix)
    prior=fake.complete;requests=[]
    def complete(provider,model,messages,**kwargs):
        text=messages[-1]['content']
        if '仅返回需要修改的段落' in text:
            requests.append(text)
            delta=text.split('新增或改变的论文分析：\n',1)[1].split('\n\n原文依据：',1)[0]
            assert 'New delta only' in delta and f'[P{pid}]' in delta and 'Paper 0' not in delta
            if len(requests)>1:return SimpleNamespace(content='{"edits":[]}')
            chosen=next(b for b in targets(text) if not b['text'].startswith('#'))
            return SimpleNamespace(content=json.dumps({'edits':[{'block_id':chosen['id'],'replacement':f'已应用的有效修改 [P{pid}]。'},{'block_id':'missing','replacement':'不能覆盖任何段落。'}]},ensure_ascii=False))
        return prior(provider,model,messages,**kwargs)
    monkeypatch.setattr(fake,'complete',complete)
    client.post(prefix+'/run');first=client.get(prefix).json()
    assert '已应用的有效修改' in first['content'] and '不能覆盖任何段落' not in first['content']
    assert first['error'] and first['status']=='ready'
    client.post(prefix+'/run');second=client.get(prefix).json()
    assert len(requests)==2 and not second['error'] and second['content']==first['content']


def test_legacy_checkpoint_learns_material_baseline_without_model_regeneration(client,monkeypatch):
    prefix,fake,ids=setup(client,monkeypatch,count=2);client.post(prefix+'/run')
    with Session(get_engine()) as s:
        row=s.exec(select(ReviewSection).where(ReviewSection.review_id==prefix.rsplit('/',1)[1],ReviewSection.ordinal==continuation.ORDINAL)).one()
        data=json.loads(row.content);data.pop('papers');row.content=json.dumps(data);s.add(row);s.commit()
    count=len(fake.calls);before=client.get(prefix).json()
    client.post(prefix+'/run');assert len(fake.calls)==count
    with Session(get_engine()) as s:
        row=s.exec(select(ReviewSection).where(ReviewSection.review_id==prefix.rsplit('/',1)[1],ReviewSection.ordinal==continuation.ORDINAL)).one()
        assert set(json.loads(row.content)['papers'])=={str(i) for i in ids}
    assert client.get(prefix).json()['content']==before['content']


def test_exact_editor_spans_handle_duplicate_unicode_and_code_fences():
    original='same😀\r\n\r\n```python\r\nx=1\r\n\r\nx+=2\r\n```\r\n\r\nsame😀\r\n\r\ntail'
    units=incremental.units(original,3,1000)
    assert len(units)==4 and 'x+=2' in units[1]['text']
    raw=json.dumps({'edits':[{'block_id':units[2]['id'],'replacement':'modified😀'},
                              {'block_id':units[3]['id'],'op':'append','replacement':'addition'}]})
    edits,warnings,reasons=incremental.edits(raw,units,{1})
    assert not warnings
    assert replace_blocks(original,edits)==original[:units[2]['start']]+'modified😀'+original[units[2]['end']:]+'\n\naddition'


def test_new_original_evidence_survives_many_existing_citations(client,monkeypatch):
    from app.reviews import evidence,claims
    prefix,fake,ids=setup(client,monkeypatch,count=1);client.post(prefix+'/run')
    pid=add_paper(client,prefix);original=fake.complete;seen=[]
    old=[dict(paper_id=ids[0],quote=f'Existing source {i}. '+('Detailed original research results. '*35),claim_source=True) for i in range(35)]
    monkeypatch.setattr(claims,'gather',lambda *args:old)
    def sources(entries,draft,*args,**kwargs):
        if len(entries)==1 and entries[0].paper_id==pid:
            return [dict(paper_id=pid,quote='New original evidence with its experimental conditions. '*25)]
        return [dict(e,claim_source=False) for e in old]
    monkeypatch.setattr(evidence,'revision_sources',sources)
    def complete(provider,model,messages,**kwargs):
        text=messages[-1]['content']
        if '仅返回需要修改的段落' in text:
            seen.append(text)
            assert f'[P{pid}]' in text.split('新增或改变论文的原文：\n',1)[1]
            assert 'New original evidence with its experimental conditions.' in text
            return SimpleNamespace(content='{"edits":[]}')
        return original(provider,model,messages,**kwargs)
    monkeypatch.setattr(fake,'complete',complete)
    client.post(prefix+'/run')
    assert seen and not client.get(prefix).json()['error']


def test_human_edit_of_partial_first_draft_switches_to_current_manuscript(client,monkeypatch):
    prefix,fake,ids=setup(client,monkeypatch,count=1);original=fake.complete
    def incomplete(provider,model,messages,**kwargs):
        if '只写当前章节' in messages[-1]['content']:raise TimeoutError('fixture chapter failure')
        return original(provider,model,messages,**kwargs)
    monkeypatch.setattr(fake,'complete',incomplete)
    client.post(prefix+'/run');first=client.get(prefix).json();assert first['error']
    corrected='# 已核对稿\n\n人工纠正与尚待补充的段落 [P1]。'
    client.post(prefix+'/content',json={'content':corrected,'expected_version':first['version']})
    seen=[]
    def update(provider,model,messages,**kwargs):
        text=messages[-1]['content'];assert '只写当前章节' not in text
        if '仅返回需要修改的段落' in text:
            seen.append(text);assert '人工纠正与尚待补充的段落' in text
            return SimpleNamespace(content='{"edits":[]}')
        return original(provider,model,messages,**kwargs)
    monkeypatch.setattr(fake,'complete',update)
    client.post(prefix+'/run');result=client.get(prefix).json()
    assert seen and result['content'].startswith(corrected+'\n\n## 引用文献') and not result['error']
