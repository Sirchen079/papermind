import json
from types import SimpleNamespace
from sqlmodel import Session,select
from app.db.engine import get_engine
from app.models.review import ReviewPaper,ReviewSection
from test_library_reviews import setup
from test_review_incremental import add_paper,targets
from test_review_editing import seed


def test_published_changes_keep_reasons_sources_and_edit_current_paragraph(client,monkeypatch):
    prefix,fake,ids=setup(client,monkeypatch,1);client.post(prefix+'/run');pid=add_paper(client,prefix)
    prior=fake.complete
    def complete(provider,model,messages,**kwargs):
        text=messages[-1]['content']
        if '仅返回需要修改的段落' in text:
            block=next(b for b in targets(text) if not b['text'].startswith('#'))
            return SimpleNamespace(content=json.dumps({'edits':[{'block_id':block['id'],'replacement':f'新增证据的有限结论 [P{pid}]。','reason':'补充新论文的比较条件。'}]}))
        return prior(provider,model,messages,**kwargs)
    monkeypatch.setattr(fake,'complete',complete);client.post(prefix+'/run');review=client.get(prefix).json();version=review['version']
    count=len(fake.calls)
    detail=client.get(prefix+f'/revisions/{version}/changes').json()
    assert detail['snapshot'] and detail['base_version']==version-1 and len(detail['changes'])==1
    change=detail['changes'][0];assert change['reason']=='补充新论文的比较条件。' and change['current_block_id']
    assert any(e['paper_id']==pid and e['quote'] for e in detail['evidence'])
    # Later analysis/checkpoint changes cannot rewrite this version's evidence.
    with Session(get_engine()) as s:
        for row in s.exec(select(ReviewPaper).where(ReviewPaper.review_id==review['id'])):
            row.evidence_json='[]';s.add(row)
        for row in s.exec(select(ReviewSection).where(ReviewSection.review_id==review['id'],ReviewSection.ordinal>-400000)):
            row.evidence_json='[]';s.add(row)
        s.commit()
    assert client.get(prefix+f'/revisions/{version}/changes').json()['evidence']==detail['evidence']
    response=client.post(prefix+'/paragraphs/apply',json={'expected_version':version,'block_id':change['current_block_id'],'replacement':'研究者核对后的结果。'})
    assert response.status_code==200
    old=client.get(prefix+f'/revisions/{version}/changes').json()
    assert old['changes'][0]['after']==change['after'] and old['changes'][0]['current_block_id'] is None
    assert len(fake.calls)==count


def test_old_versions_compare_duplicates_unicode_and_allow_existing_editor(client):
    prefix,original=seed(client);blocks=client.get(prefix+'/paragraphs').json()['blocks'];target=blocks[3]
    assert '相同段落' in target['text']
    client.post(prefix+'/paragraphs/apply',json={'expected_version':1,'block_id':target['id'],'replacement':'第二处修订😀 [P7]。'})
    response=client.get(prefix+'/revisions/2/changes');assert response.status_code==200
    report=response.json();assert not report['snapshot'] and report['base_version']==1
    assert len(report['changes'])==1 and report['changes'][0]['before']==target['text']
    assert report['changes'][0]['current_block_id']
    # An edit elsewhere changes the version, but the same span is still usable.
    current=client.get(prefix).json();client.post(prefix+'/content',json={'expected_version':2,'content':'开头追加说明。\n\n'+current['content']})
    moved=client.get(prefix+'/revisions/2/changes').json();assert moved['current_version']==3 and moved['changes'][0]['current_block_id']
    assert client.post(prefix+'/paragraphs/apply',json={'expected_version':3,'block_id':moved['changes'][0]['current_block_id'],'replacement':'第二处再次核对。'}).status_code==200
    assert '相同段落😀 [P7]。' in client.get(prefix).json()['content']
    assert client.get(prefix+'/revisions/999/changes').status_code==404


def test_comparison_preserves_fences_and_insert_delete_spans():
    from app.reviews.changes import comparison
    a='同一段😀\r\n\r\n```py\r\na=1\r\n\r\nb=2\r\n```\r\n\r\n末段'
    b=a.replace('b=2','b=3')+'\r\n\r\n新增'
    changes=comparison(a,b)
    assert len(changes)==2 and 'a=1\r\n\r\nb=2' in changes[0]['before']
    assert changes[1]['before']=='' and changes[1]['after']=='新增'
    assert comparison('只删除','')[0]['after']==''
