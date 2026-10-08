import json
from types import SimpleNamespace
from sqlmodel import Session
from app.db.engine import get_engine
from app.models import Paper
from app.models.reading import PaperNote
from app.reviews import service
from app.reviews.evidence import revision_sources, chapter_sources, source_text
from app.reviews.notes import from_entries, context
from test_library_reviews import setup


def test_note_correction_invalidates_only_affected_paper_and_reaches_patch(client,monkeypatch):
    prefix,fake,ids=setup(client,monkeypatch,count=3)
    client.post(prefix+'/run')
    before=client.get(prefix).json();calls=len(fake.calls)
    correction='核对记录：训练只在数据集甲进行；数据集乙仅作测试，不支持跨域普遍有效。'
    with Session(get_engine()) as s:
        note=PaperNote(paper_id=ids[1],content=correction)
        s.add(note);s.commit();nid=note.id
    client.post(prefix+'/run')
    changed=fake.calls[calls:]
    analyses=[x for x in changed if '逐篇分析。' in x]
    patches=[x for x in changed if '仅返回需要修改的段落' in x]
    assert len(analyses)==1 and correction in analyses[0]
    assert patches and all(correction in x and '不是论文原文' in x for x in patches)
    result=client.get(prefix).json()
    assert result['counts']['reused']==2
    saved=client.get(prefix+f'/papers/{ids[1]}').json()['evidence']
    n=next(e for e in saved if e.get('scope')=='researcher_note')
    assert n['note_id']==nid and n['version']==1 and n['quote']==correction
    # The fake returns no edits; adding a note does not itself replace prose.
    assert result['content']==before['content']
    calls=len(fake.calls);client.post(prefix+'/run')
    assert len(fake.calls)==calls
    with Session(get_engine()) as s:
        note=s.get(PaperNote,nid);note.content='改为待测试设想，尚未采用。';note.version=2;s.add(note);s.commit()
    client.post(prefix+'/run')
    new=fake.calls[calls:]
    assert sum('逐篇分析。' in x for x in new)==1
    assert all(correction not in x for x in new)
    assert any('v2' in x and '尚未采用' in x for x in new)
    calls=len(fake.calls)
    with Session(get_engine()) as s:s.delete(s.get(PaperNote,nid));s.commit()
    client.post(prefix+'/run')
    assert client.get(prefix).json()['counts']['reused']==2
    assert sum('逐篇分析。' in x for x in fake.calls[calls:])==1
    assert not any('尚未采用' in x for x in fake.calls[calls:])
    with Session(get_engine()) as s:
        entry=next(p for p in service.papers(s,prefix.rsplit('/',1)[1]) if p.paper_id==ids[1])
        assert not from_entries([entry])
    # Historical update snapshots stay available for interpreting old changes.


def test_saved_notes_do_not_become_original_text_or_crowd_it_out():
    evidence=[dict(paper_id=1,scope='full_text_span',quote='Exact paper method and result.',purpose='方法机制',locator='PDF 2'),
              dict(paper_id=1,scope='researcher_note',note_id=7,version=4,quote='Speculation from saved note.',locator='研究笔记 #7 · v4')]
    entry=SimpleNamespace(paper_id=1,title='Paper',evidence_json=json.dumps(evidence))
    assert all(e['scope']!='researcher_note' for e in revision_sources([entry],'[P1]'))
    assert all(e['scope']!='researcher_note' for e in chapter_sources([entry],[],'方法',2))
    assert 'Speculation' not in source_text(evidence,2000)
    assert 'Exact paper' in source_text(evidence,2000)
    text=context(from_entries([entry]))
    assert 'v4' in text and '不是论文原文' in text and 'Speculation' in text


def test_notes_only_paper_yields_labeled_material_instead_of_stopping(client,monkeypatch):
    prefix,fake,ids=setup(client,monkeypatch,count=1)
    with Session(get_engine()) as s:
        paper=s.get(Paper,ids[0]);paper.full_text=None;s.add(paper)
        s.add(PaperNote(paper_id=ids[0],content='待测试设想：对比两个噪声条件。'))
        s.commit()
    client.post(prefix+'/run')
    result=client.get(prefix).json()
    assert result['status']=='ready' and result['counts']['missing']==0
    assert result['papers'][0]['coverage']=='research_notes_only'
    analysis=next(x for x in fake.calls if '逐篇分析。' in x)
    assert '没有可读论文正文或摘要' in analysis and '待测试设想' in analysis
    assert any('不是论文原文' in x for x in fake.calls if '当前章节' in x)


def test_small_window_keeps_note_and_original_channels(client,monkeypatch):
    from app.models import Provider,Model
    from app.agent.context import total_tokens
    prefix,fake,ids=setup(client,monkeypatch,count=1)
    with Session(get_engine()) as s:
        s.add(Provider(id=123,name='fixture',type='openai_chat',base_url='https://test.invalid'));s.commit()
        s.add(Model(provider_id=123,model_id='fake',context_window=8192))
        s.add(PaperNote(paper_id=ids[0],content='\n\n'.join(f'笔记段落{i}：'+'未确定的研究条件。'*150 for i in range(20))))
        s.commit()
    original=fake.complete
    def complete(provider,model,messages,**kwargs):
        assert total_tokens(messages)+kwargs['max_tokens']<=8192
        return original(provider,model,messages,**kwargs)
    monkeypatch.setattr(fake,'complete',complete)
    client.post(prefix+'/run')
    assert client.get(prefix).json()['status']=='ready'
    analysis=next(x for x in fake.calls if '逐篇分析。' in x)
    assert 'Method 0 uses retrieval' in analysis and '研究笔记' in analysis
    assert '笔记段落19' in analysis


def test_paragraph_proposal_uses_current_note_without_requiring_batch_run(client,monkeypatch):
    prefix,fake,ids=setup(client,monkeypatch,count=1)
    monkeypatch.setattr('app.reviews.editing.pick_llm',lambda *_:(fake,SimpleNamespace(id=123,base_url='https://test.invalid'),'fake'))
    client.post(prefix+'/run')
    with Session(get_engine()) as s:
        s.add(PaperNote(paper_id=ids[0],content='刚刚核对的新条件：目前只是设想。',version=2));s.commit()
    data=client.get(prefix+'/paragraphs').json()
    block=next(b for b in data['blocks'] if f'[P{ids[0]}]' in b['text'])
    before=len(fake.calls)
    response=client.post(prefix+'/paragraphs/propose',json={'expected_version':data['version'],'block_id':block['id'],'instruction':'结合已有记录核对措辞。'})
    assert response.status_code==200,response.text
    assert any('刚刚核对的新条件' in x and 'v2' in x and '不是论文原文' in x for x in fake.calls[before:])
