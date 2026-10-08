import json
from types import SimpleNamespace
from sqlmodel import Session
from app.db.engine import get_engine
from app.models import Paper
from app.reviews.evidence import candidates, select_spans, chapter_sources, revision_sources, source_text, LABELS
from app.reviews.service import paper_evidence


def prose(marker, n=18):
    return (marker+' is described in this source passage with its experimental conditions.\n')*n


def test_experimental_keyword_noise_does_not_replace_mechanism():
    full=('Abstract\n'+prose('Scope',4)+'\n1 Introduction\n'+prose('Motivation',4)+
          '\n2\nMethods\n'+prose('CORE_MECHANISM',8)+
          '\n2.1\nRepresentation Construction\n'+prose('CORE_REPRESENTATION',8)+
          '\n2.2 Optimization\n'+prose('CORE_OBJECTIVE',8)+
          '\n3 Experiments\n'+prose('evaluation dataset baseline split results',110)+
          '\n4 Discussion\n'+prose('BOUNDARY',5)+
          '\nReferences\n'+prose('OTHER_PAPER_METHOD',20)+
          '\nAppendix\n\nMethods\n'+prose('SUPPLEMENT_METHOD',30))
    spans=select_spans(full,'中文检索方法比较','A retrieval study')
    quotes='\n'.join(e['quote'] for e in spans)
    for marker in ('CORE_MECHANISM','CORE_REPRESENTATION','CORE_OBJECTIVE','BOUNDARY'):
        assert marker in quotes
    assert 'OTHER_PAPER_METHOD' not in quotes and 'SUPPLEMENT_METHOD' not in quotes
    assert len(spans)<=9
    for e in spans:assert full[e['start']:e['end']]==e['quote']


def test_chinese_headings_short_and_unstructured_papers_remain_usable():
    full='摘要\n'+'这是研究摘要。'*40+'\n1 方法\n'+'核心机制是分别编码再计算匹配。'*40+'\n2 结果\n'+'条件不同不能直接比较。'*40
    spans=select_spans(full,'方法比较')
    assert any('核心机制' in e['quote'] and e['purpose']==LABELS['method'] for e in spans)
    short='A brief unstructured paper containing a useful finding.'
    assert select_spans(short,'中文主题')[0]['quote']==short
    assert select_spans('','topic')==[]


def test_numbered_related_work_and_supplement_do_not_become_main_methods():
    full=('1 Related Work\n'+prose('PRIOR_ART',8)+'\n2 Methods\n'+prose('OWN_METHOD',12)+
          '\n3 Results\n'+prose('RESULTS',8)+'\nReferences\n'+prose('CITATIONS',8)+
          '\nAppendix\n\n4 Methods\n'+prose('APPENDIX_METHOD',8))
    spans=candidates(full)
    assert all(s['role']=='related' for s in spans if 'PRIOR_ART' in s['quote'])
    assert all(s['region']=='appendix' for s in spans if 'APPENDIX_METHOD' in s['quote'])
    chosen=select_spans(full,'methods')
    assert 'OWN_METHOD' in next(e['quote'] for e in chosen if e['purpose']==LABELS['method'])
    assert not any('CITATIONS' in e['quote'] or 'APPENDIX_METHOD' in e['quote'] for e in chosen)


def test_chapters_get_relevant_sources_for_each_paper_with_partial_index():
    papers=[]
    for pid in range(1,4):
        evidence=[{'quote':f'{kind} P{pid}', 'purpose':LABELS[kind]} for kind in ('background','method','results','discussion')]
        papers.append(SimpleNamespace(paper_id=pid,evidence_json=json.dumps(evidence)))
    recalled=[SimpleNamespace(paper_id=1,ordinal=4,text='Indexed background for P1')]
    methods=chapter_sources(papers,recalled,'主要方法与机制',6)
    assert [e['paper_id'] for e in methods[:3]]==[1,2,3]
    assert all(e['quote'].startswith('method') for e in methods[:3])
    results=chapter_sources(papers,[],'实验结果与评价条件',6)
    assert all(e['quote'].startswith('results') for e in results[:3])
    assert all(e['quote'].startswith('discussion') for e in chapter_sources(papers,[],'局限与未来方向',3))
    assert chapter_sources([],[],'方法')==[]


def test_full_text_source_offsets_and_pages_remain_real(client):
    full='<!-- page:1 -->\nAbstract\n'+prose('ABSTRACT',4)+'\n<!-- page:7 -->\n2 Methods\n'+prose('METHOD_PAGE_SEVEN',8)
    with Session(get_engine()) as session:
        paper=Paper(source='manual',title='Fixture',full_text=full,abstract='Saved abstract')
        session.add(paper);session.commit()
        material=paper_evidence(session,paper.id,'方法')
        assert material['evidence'][0]['scope']=='abstract'
        method=next(e for e in material['evidence'] if 'METHOD_PAGE_SEVEN' in e['quote'])
        assert method['page']==7
        assert full[method['start']:method['end']]==method['quote']
        assert len({e['ref'] for e in material['evidence']})==len(material['evidence'])


def test_counterfinding_survives_many_positive_experiment_passages():
    full=('Abstract\n'+prose('General benefit',4)+'\n1 Methods\n'+prose('Core mechanism',20)+
          '\n2 Results\n'+prose('evaluation accuracy experiment baseline',80)+
          '\n2.1 Exceptions\n'+prose('With the exception of Benchmark Z, the method performs better',8)+
          '\n3 Discussion\n'+prose('Future work',8))
    spans=select_spans(full,'效果比较')
    assert any('Benchmark Z' in e['quote'] for e in spans)
    p=SimpleNamespace(paper_id=1,evidence_json=json.dumps(spans))
    chosen=chapter_sources([p],[],'实验结果',2)
    assert any('Benchmark Z' in e['quote'] for e in chosen)


def test_distinct_experiment_endpoints_survive_ablation_keyword_density():
    full=('Abstract\n'+prose('Aim',4)+'\n1 Methods\n'+prose('METHOD',8)+
          '\n2 Experiments: Component performance\n'+prose('COMPONENT_OUTCOME',8)+
          '\n2.1 Ablation Study\n'+prose('evaluation accuracy experiment performance',70)+
          '\n3 Experiments: End-to-End Evaluation\nWe evaluate overall outcomes.\n3.1 Final System\n'+prose('SYSTEM_OUTCOME',8))
    spans=select_spans(full,'方法综述')
    quotes='\n'.join(e['quote'] for e in spans)
    assert 'COMPONENT_OUTCOME' in quotes and 'SYSTEM_OUTCOME' in quotes
    paper=SimpleNamespace(paper_id=1,evidence_json=json.dumps(spans))
    revision='\n'.join(e['quote'] for e in revision_sources([paper],'结果比较 [P1]'))
    assert 'COMPONENT_OUTCOME' in revision and 'SYSTEM_OUTCOME' in revision
    for e in spans:assert full[e['start']:e['end']]==e['quote']


def test_revision_sources_follow_actual_citations_even_late_in_large_library():
    papers=[]
    for pid in range(1,1001):
        sources=[{'quote':f'{kind} P{pid}\n\nOriginal continuation.', 'purpose':LABELS[kind], 'start':pid}
                 for kind in ('background','method','results','counter','discussion')]
        papers.append(SimpleNamespace(paper_id=pid,evidence_json=json.dumps(sources)))
    evidence=revision_sources(papers,'方法与结果 [P999]，比较 [P800]。')
    assert [e['paper_id'] for e in evidence[:2]]==[999,800]
    assert {e['paper_id'] for e in evidence}=={999,800}
    for pid in (999,800):
        assert {e['purpose'] for e in evidence if e['paper_id']==pid} >= {LABELS[k] for k in ('method','results','counter')}
    fitted=source_text(evidence,150)
    assert '[P999]' in fitted and '[P800]' in fitted and '[P1]' not in fitted
    assert all(p.startswith('[P') for p in fitted.split('\n\n'))


def test_revision_without_sources_still_has_a_writable_draft():
    empty=SimpleNamespace(paper_id=1,evidence_json='[]')
    assert revision_sources([empty],'已有正文 [P1]')==[]
    assert source_text([],100)==''


def test_source_budget_keeps_table_caption_and_skips_oversized_excerpts():
    from app.agent.context import estimate_tokens
    table='Method A 46.3 31.7\nMethod B 46.3 34.2\nTable 1: Both readers use the top-1 retrieved passage.'
    evidence=[dict(paper_id=1,paper_title='A long title '*25,quote='Oversized source. '*500,claim_source=True),
              dict(paper_id=83,paper_title='One Pass',quote=table,claim_source=True),
              dict(paper_id=2,quote='A complete background finding.')]
    original=json.dumps(evidence)
    text=source_text(evidence,180)
    assert table in text and '[P1]' not in text
    assert estimate_tokens(text)<=180
    assert json.dumps(evidence)==original
    assert all(unit.split('\n',1)[1].strip() for unit in text.split('\n\n'))


def test_source_budget_gives_different_papers_complete_excerpts_first():
    first=dict(paper_id=1,quote='First paper result. '*5,claim_source=True)
    extra=dict(paper_id=1,quote='Additional first paper result. '*5,claim_source=True)
    second=dict(paper_id=2,quote='Second paper result. '*5,claim_source=True)
    text=source_text([first,extra,second],100)
    assert first['quote'] in text and second['quote'] in text
    assert extra['quote'] not in text


def test_source_budget_uses_available_room_for_complete_late_conditions():
    from app.agent.context import estimate_tokens
    evidence=[dict(paper_id=i,paper_title=f'Paper {i}',
                   quote=('Source material. '*1000)+f'End condition {i}.',claim_source=i<3) for i in range(1,9)]
    text=source_text(evidence,50000)
    assert all(e['quote'] in text for e in evidence)
    assert estimate_tokens(text)<=50000


def test_small_source_budget_retains_sentences_and_marks_omission():
    from app.agent.context import estimate_tokens
    evidence=[dict(paper_id=i,paper_title='Source study',quote=
                   f'Opening claim {i}. '+('Supporting detail. '*100)+f'Final limitation {i}.') for i in (7,999)]
    text=source_text(evidence,160)
    for i in (7,999):
        assert f'Opening claim {i}.' in text and f'Final limitation {i}.' in text
    assert '原文中间部分省略' in text
    assert estimate_tokens(text)<=160


def test_chapter_retrieval_preserves_page_provenance_without_inventing_it():
    paper=SimpleNamespace(paper_id=1,evidence_json='[]')
    chunks=[SimpleNamespace(paper_id=1,ordinal=4,text='[第 7 页]\nOriginal method evidence.'),
            SimpleNamespace(paper_id=1,ordinal=0,text='Paper title and abstract.')]
    sources=chapter_sources([paper],chunks,'方法',2)
    assert sources[0]['page']==7 and '第 7 页' in sources[0]['locator']
    assert sources[0]['quote']==chunks[0].text
    assert sources[1]['page'] is None


def test_semantic_english_hits_survive_chinese_chapter_role_selection():
    papers=[SimpleNamespace(paper_id=i,evidence_json=json.dumps([
        {'quote':f'Core mechanism {i}.','purpose':LABELS['method']},
        {'quote':f'Benchmark conditions {i}.','purpose':LABELS['results']},
        {'quote':f'Exception case {i}.','purpose':LABELS['counter']},
    ])) for i in range(1,19)]
    hits=[SimpleNamespace(paper_id=i,ordinal=7,text=f'[第 5 页]\nDistinct semantic evidence {i}.') for i in (18,17,16,15,14,13,12,11)]
    sources=chapter_sources(papers,hits,'检索与生成的耦合机制',12)
    assert len(sources)==12
    assert [e['paper_id'] for e in sources if e.get('purpose')=='章节相关原文']==[18,17,16,15,14,13]
    assert sum(e.get('purpose')==LABELS['method'] for e in sources)==6
    assert all(e['page']==5 for e in sources if e.get('purpose')=='章节相关原文')


def test_chapter_hits_are_diverse_unique_and_belong_to_selected_papers():
    papers=[SimpleNamespace(paper_id=i,evidence_json='[]') for i in (1,2,3)]
    hit=lambda pid,text:SimpleNamespace(paper_id=pid,ordinal=2,text=text)
    sources=chapter_sources(papers,[hit(999,'OUTSIDE'),hit(1,'A'),hit(1,'B'),hit(1,'A'),hit(2,'C'),hit(3,'D')],'方法',4)
    assert len(sources)==4
    assert {e['paper_id'] for e in sources}=={1,2,3}
    assert len({(e['paper_id'],e['quote']) for e in sources})==4
    assert chapter_sources(papers,[hit(1,'A')],'方法',0)==[]
