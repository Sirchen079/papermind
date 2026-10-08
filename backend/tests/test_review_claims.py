import json
import re
from pathlib import Path
from types import SimpleNamespace
import pymupdf
from sqlmodel import Session
from app.config import get_settings
from app.db.engine import get_engine
from app.models import Paper
from app.reviews.claims import cited_claims, gather, numbers, text_matches, pdf_matches
from app.reviews.evidence import source_text
from app.agent.context import estimate_tokens


def make_table(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with pymupdf.open() as doc:
        page=doc.new_page()
        for y,label,left,right in [(80,'Model','Accuracy','Latency'),(110,'Base','14.7','1.0'),
                                   (140,'DifferentBase-Retrieval','51.8','2.0')]:
            for x,text in [(40,label),(260,left),(360,right)]:page.insert_text((x,y),text)
        page.insert_text((40,175),'Table 1: Different base model conditions.')
        doc.save(path)


def test_numeric_claim_anchors_are_exact_and_not_citation_or_model_ids():
    assert numbers('[P999] LLaMA2-13B 14.7%, 51.8, 50,000 samples, 20%')=={'14.7','51.8','50000','20'}
    full=('Unrelated background about a different method.\n'*400+
          '\n5 Results\nThe treatment changed survival from 14.7% to 51.8% under condition B.\n'*8)
    result=text_matches(full,['生存率从14.7%升至51.8% [P9]'])
    assert result and 'condition B' in result[0]['quote']
    for e in result:assert full[e['start']:e['end']]==e['quote']
    assert text_matches(full,['不存在的内容 [P9]'])==[]


def test_cited_claims_separate_sources_and_keep_shared_context():
    claims=cited_claims('背景条件。准确率为29.3% [P1]；延迟为2.0秒 [P2]。定性观察 [P3]。')
    assert numbers(''.join(claims[1]))=={'29.3'}
    assert claims[1][0].startswith('背景条件。')
    assert numbers(''.join(claims[2]))=={'2.0'}
    assert numbers(''.join(claims[3]))==set()
    shared=cited_claims('两项研究共同观察到14.7%的结果 [P1][P2]。这些条件仍需验证。')
    assert shared[1]==shared[2]
    assert '这些条件仍需验证' in shared[1][0]


def test_cited_claims_handle_punctuation_prefixes_and_decimals():
    after=cited_claims('准确率为29.3%。[P1] 延迟为2.0秒。[P2]')
    prefix=cited_claims('[P1] 准确率为29.3%；[P2] 延迟为2.0秒。')
    english=cited_claims('Accuracy was 29.3%.[P1] Latency was 2.0 seconds [P2].')
    for claims in (after,prefix,english):
        assert numbers(''.join(claims[1]))=={'29.3'}
        assert numbers(''.join(claims[2]))=={'2.0'}
    single='完整背景。准确率29.3% [P1]；解释和局限。'
    assert cited_claims(single)=={1:[single]}
    assert cited_claims('没有引用。')=={}
    # Within one sentence, ambiguous shared attribution keeps the context.
    shared=cited_claims('Accuracy 29.3% [P1], latency 2.0 seconds [P2].')
    assert shared[1]==shared[2]


def test_gather_does_not_select_pdf_using_another_sources_numbers(client):
    path=get_settings().data_dir/'pdfs'/'numeric.pdf';make_table(path)
    with Session(get_engine()) as session:
        numeric=Paper(source='manual',title='Numbers',pdf_path='numeric.pdf',full_text='Accuracy 14.7 and 51.8.')
        qualitative=Paper(source='manual',title='Qualitative',pdf_path='numeric.pdf',full_text='Qualitative mechanism interpretation.')
        session.add_all([numeric,qualitative]);session.commit()
        entries=[SimpleNamespace(paper_id=p.id) for p in (numeric,qualitative)]
        result=gather(session,entries,f'Accuracy rose from 14.7 to 51.8 [P{numeric.id}]。Qualitative mechanism interpretation [P{qualitative.id}]。')
        assert any(e['paper_id']==numeric.id and e['scope']=='pdf_page_layout' for e in result)
        assert not any(e['paper_id']==qualitative.id and e['scope']=='pdf_page_layout' for e in result)
        assert any(e['paper_id']==qualitative.id and e['scope']=='full_text_span' for e in result)


def test_layout_keeps_model_and_value_on_the_same_line(tmp_path):
    path=tmp_path/'table.pdf';make_table(path)
    result=pdf_matches(path,['结果从14.7%升至51.8% [P1]'])
    assert len(result)==1 and result[0]['page']==1
    assert re.search(r'Base\s+14\.7',result[0]['quote'])
    assert re.search(r'DifferentBase-Retrieval\s+51\.8',result[0]['quote'])
    assert 'Accuracy' in result[0]['quote'] and len(result[0]['source_hash'])==64
    assert pdf_matches(path,['没有数值的比较 [P1]'])==[]


def test_numeric_anchor_keeps_cross_page_conditions_and_deduplicates_neighbors(tmp_path):
    path=tmp_path/'cross-page.pdf'
    pages=['The experiment uses the same retriever, comparing generators.',
           'A decrease of 0.7 points on Dataset A and 2.0',
           'points on Dataset B. Both comparisons keep retrieval fixed.',
           'A second independent result is 61.3 percent.',
           'This comparison only uses the small model.']
    with pymupdf.open() as doc:
        for text in pages:doc.new_page().insert_text((40,80),text)
        doc.save(path)
    result=pdf_matches(path,['下降0.7和2.0点 [P1]','另一结果61.3% [P1]'])
    assert [e['page'] for e in result[:2]]==[2,4]
    assert len(result)==5 and len({e['page'] for e in result})==5
    assert all(not e['adjacent_context'] for e in result[:2])
    assert all(e['adjacent_context'] for e in result[2:])
    assert any(e['page']==3 and 'Dataset B' in e['quote'] for e in result)
    assert any(e['page']==1 and 'same retriever' in e['quote'] for e in result)
    assert any(e['page']==5 and 'small model' in e['quote'] for e in result)
    with pymupdf.open(path) as doc:
        assert all(e['quote']==doc[e['page']-1].get_text('text',sort=True) for e in result)
    # First/last pages have only valid neighbors; anchor priority is unchanged.
    last=pdf_matches(path,['另一结果61.3% [P1]'],limit=1)
    assert last[0]['page']==4 and {e['page'] for e in last}=={3,4,5}


def test_gather_only_cited_library_papers_and_preserves_missing_pdf_fallback(client):
    with Session(get_engine()) as session:
        p=Paper(source='manual',title='Comparison',full_text='<!-- page:8 -->\nResults\nMeasured accuracy 14.7 with condition A. '*8,pdf_path='missing.pdf')
        other=Paper(source='manual',title='Uncited',full_text='OTHER_PAPER 51.8')
        session.add_all([p,other]);session.commit()
        entries=[SimpleNamespace(paper_id=i.id) for i in (p,other)]
        result=gather(session,entries,f'准确率14.7% [P{p.id}]；不属于当前库 [P99999]')
        assert result and {e['paper_id'] for e in result}=={p.id}
        assert all(e['claim_source'] and e['page']==8 for e in result)
        assert 'OTHER_PAPER' not in str(result)
        p.is_deleted=True;session.add(p);session.commit()
        assert gather(session,entries,f'准确率14.7% [P{p.id}]')==[]


def test_gather_attached_pdf_and_budget_keep_numeric_context(client):
    path=get_settings().data_dir/'pdfs'/'table.pdf';make_table(path)
    with Session(get_engine()) as session:
        p=Paper(source='manual',title='Table',pdf_path='table.pdf',full_text='Base\n14.7\nDifferentBase-Retrieval\n51.8')
        session.add(p);session.commit()
        result=gather(session,[SimpleNamespace(paper_id=p.id)],f'从14.7升至51.8 [P{p.id}]')
        assert result[0]['scope']=='pdf_page_layout'
        assert all(e['paper_title']=='Table' for e in result)
        result.extend(dict(paper_id=p.id,quote='Background information. '*500) for _ in range(6))
        text=source_text(result,500)
        assert re.search(r'Base\s+14\.7',text) and re.search(r'DifferentBase-Retrieval\s+51\.8',text)
        assert estimate_tokens(text)<=500


def test_revision_evidence_keeps_paper_identity_with_the_quote():
    from app.reviews.evidence import revision_sources
    papers=[SimpleNamespace(paper_id=58,title='ATM: Adversarial Tuning',evidence_json=json.dumps([
        {'quote':'Subspan EM for the ATM comparison.','purpose':'实验结果'}])),
        SimpleNamespace(paper_id=38,title='BERGEN: A Benchmarking Library',evidence_json=json.dumps([
        {'quote':'Oracle retrieval for ELI5 and WoW.','purpose':'实验结果'}]))]
    evidence=revision_sources(papers,'ATM 指标 [P58]。BERGEN 的 oracle 实验 [P38]。')
    text=source_text(evidence,400)
    units=text.split('\n\n')
    assert any('[P58] ATM: Adversarial Tuning' in unit and 'Subspan EM' in unit and 'BERGEN' not in unit for unit in units)
    assert any('[P38] BERGEN: A Benchmarking Library' in unit and 'Oracle retrieval' in unit and 'ATM' not in unit for unit in units)
    assert estimate_tokens(text)<=400
    # Snapshots produced by earlier versions remain usable without a title.
    legacy=source_text([{'paper_id':7,'quote':'LEGACY_SOURCE'}],100)
    assert '[P7]' in legacy and 'LEGACY_SOURCE' in legacy


def test_source_panel_includes_final_revision_evidence(client,monkeypatch):
    from test_library_reviews import setup
    from app.models.review import ReviewSection
    prefix,_,ids=setup(client,monkeypatch)
    rid=prefix.rsplit('/',1)[1]
    with Session(get_engine()) as session:
        session.add(ReviewSection(review_id=rid,ordinal=-99996,title='Whole revision',
            evidence_json=json.dumps([dict(paper_id=ids[0],quote='FINAL_TABLE_CONTEXT',page=7,locator='PDF page 7')])))
        session.commit()
    evidence=client.get(prefix+f'/papers/{ids[0]}').json()['evidence']
    assert any(e['quote']=='FINAL_TABLE_CONTEXT' and e['page']==7 for e in evidence)
