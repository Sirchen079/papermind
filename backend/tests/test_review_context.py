import hashlib
import pytest
from sqlmodel import Session
from types import SimpleNamespace
from app.agent.context import estimate_tokens, total_tokens
from app.reviews.context import prepare, segments
from app.reviews.writing import guides, stage_guide, CHAPTER
from app.reviews.service import SYSTEM
from app.skills.builtin import resource_path


@pytest.mark.parametrize('window',[4096,8192,32768,1048576])
@pytest.mark.parametrize('effort',['low','medium','high','max'])
def test_reasoning_budget_leaves_room_for_evidence(window,effort):
    from app.reviews.context import text_budget
    messages,output,_=prepare(SYSTEM,'主题','修订', '原始实验依据。'*10000,
                              window,754,reasoning_effort=effort)
    assert total_tokens(messages)+output<=window
    assert '原始实验依据' in messages[-1]['content']
    assert text_budget(window,754)==754
    if effort=='low':assert output==754
    if effort=='high' and window>=32768:assert output>=8192+754


@pytest.mark.parametrize('window',[4096,8192,32768])
def test_whole_request_fits_and_late_evidence_survives(window):
    guide=stage_guide(guides()[0],'related-work',window//5)
    material={'plan':'论证与术语。'*800,'previous':'此前讨论的共同机制。'*900,
        'papers':'\n\n'.join(f'[P{i}] 方法{i}具有不同的适用条件。'+'来源材料。'*600 for i in range(1,5)),
        'sources':'[P99] ORIGINAL_EVIDENCE 评价采用独立测试集。'+'原文结果。'*800}
    messages,output,full=prepare(SYSTEM,'检索方法比较',CHAPTER,material,window,3500,guide['text'])
    assert total_tokens(messages)+output<=window
    assert '[P99] ORIGINAL_EVIDENCE' in messages[-1]['content']
    assert '[P4]' in messages[-1]['content']
    assert not full


def test_stage_routing_uses_verbatim_resources_and_distinct_instructions():
    original=guides()[0]
    plan=stage_guide(original,'plan',1600)
    edit=stage_guide(original,'edit',1600)
    assert 'not a survey list' in plan['text']
    assert 'paragraph-flow.md' in edit['text']
    assert plan['fingerprint']!=edit['fingerprint']
    assert 'manifest.yaml' not in plan['text']
    for guide in (plan,edit):
        assert guide['estimated_tokens']<=1600
        for resource in guide['resources']:
            raw=resource_path(guide['id'],resource['path']).read_text(encoding='utf-8-sig')
            assert hashlib.sha256(raw.encode()).hexdigest()==resource['sha256']
            assert resource['excerpt_chars']>0


@pytest.mark.parametrize('budget', [1600, 3200, 12000])
def test_edit_guidance_keeps_conclusion_changing_evidence_before_deletion(budget):
    guide = stage_guide(guides()[0], 'edit', budget)
    principle = 'Do not use compression to hide inconvenient evidence.'
    assert principle in guide['text']
    assert 'keep it visible in the main text' in ' '.join(guide['text'].split())
    assert guide['estimated_tokens'] <= budget
    path = '../nature-shared/core/main-text-discipline.md'
    raw = resource_path(guide['id'], path).read_text(encoding='utf-8-sig')
    assert principle in raw
    receipt = next(row for row in guide['resources'] if row['path'] == path)
    assert receipt['sha256'] == hashlib.sha256(raw.encode()).hexdigest()


@pytest.mark.parametrize('window',[4096,8192,32768])
def test_revision_request_keeps_late_cited_papers_in_a_thousand_paper_library(window):
    import json
    from app.reviews.evidence import revision_sources, source_text, LABELS
    from app.reviews.writing import EDIT
    papers=[SimpleNamespace(paper_id=i,evidence_json=json.dumps([
        {'purpose':LABELS[role],'quote':f'ORIGINAL_{i}_{role} '+('Detailed original evidence. '*200)}
        for role in ('method','results','counter','discussion')])) for i in range(1,1001)]
    draft='这些方法采用不同机制 [P999]，其结果存在例外 [P800]。'
    sources=source_text(revision_sources(papers,draft),window//8)
    guide=stage_guide(guides()[0],'edit',window//5)
    messages,output,_=prepare(SYSTEM,'方法比较',EDIT,{'当前正文':draft,'原文依据':sources},
                             window,600,guide['text'])
    request=messages[-1]['content']
    assert 'ORIGINAL_999_method' in request and 'ORIGINAL_800_method' in request
    assert 'ORIGINAL_1_' not in request
    assert total_tokens(messages)+output<=window


def test_long_draft_split_loses_no_characters():
    text='开头。'*1000+'\n\n'+'第二段，中文α🧪。'*600+'\n\n最后一个证据 [P77]'
    parts=segments(text,900)
    assert ''.join(parts)==text and len(parts)>2
    assert all(estimate_tokens(p)<=900 for p in parts)


def test_revision_preserves_target_before_allocating_background():
    target='需保留的完整论证 [P7]。'*90+'结尾证据。'
    evidence='\n\n'.join(f'SOURCE_{i} '+('evidence conditions '*200) for i in range(8))
    material={'写作安排':'background '*800,'当前正文':target,'原文依据':evidence}
    plain,_,_=prepare(SYSTEM,'主题','修订当前正文',material,8192,1200,'skill '*400,reasoning_budget=6000)
    assert target not in plain[-1]['content']
    messages,cap,_=prepare(SYSTEM,'主题','修订当前正文',material,8192,1200,'skill '*400,reasoning_budget=6000,required_text=target)
    assert target in messages[-1]['content']
    assert 'SOURCE_0' in messages[-1]['content'] and 'SOURCE_7' in messages[-1]['content']
    assert total_tokens(messages)+cap<=8192


def test_small_context_review_revises_every_section_and_reuses(client,monkeypatch):
    from test_library_reviews import setup
    from app.db.engine import get_engine
    from app.models import Provider, Model
    prefix,fake,_=setup(client,monkeypatch)
    with Session(get_engine()) as session:
        session.add(Provider(id=123,name='fixture',type='openai_compat',base_url='https://test.invalid'))
        session.flush()
        session.add(Model(provider_id=123,model_id='fake',context_window=8192));session.commit()
    original=fake.complete
    edits=[]
    def strict(provider,model,messages,**kwargs):
        assert total_tokens(messages)+kwargs['max_tokens']<=8192
        text=messages[-1]['content']
        if '只写当前章节' in text:
            fake.calls.append(text)
            return SimpleNamespace(content=('这一机制依赖材料条件，需要结合研究设置解释其作用。[P1]\n\n'*70))
        if '修订当前正文片段' in text:
            fake.calls.append(text);edits.append(text)
            return SimpleNamespace(content='这是一段保留原始论点与来源的修订正文。[P1]')
        return original(provider,model,messages,**kwargs)
    fake.complete=strict
    client.post(prefix+'/run');result=client.get(prefix).json()
    assert result['status']=='ready',result['error']
    assert len(edits)>=3
    for section in result['sections']:assert '## '+section['title'] in result['content']
    assert any(g['stage']=='edit' for g in result['writing_skills'])
    count=len(fake.calls)
    client.post(prefix+'/run')
    assert len(fake.calls)==count


def test_model_outline_markdown_and_numbering_do_not_leak_into_titles():
    from app.reviews.service import outline_titles, document_body
    assert outline_titles('1. **章节 1**：研究背景与目标\n## 第二章：证据与比较\n- **Chapter 3: Open questions**')==['研究背景与目标','证据与比较','Open questions']
    assert outline_titles('# 综述总标题\n1. 研究问题\n2. 检索机制\n3. 生成机制\n4. 实验条件\n5. 局限与未来')==['研究问题','检索机制','生成机制','实验条件','局限与未来']
    assert outline_titles('# 综述总标题\n## 研究问题\n## 方法比较')==['研究问题','方法比较']
    assert document_body('# 模型额外总标题\n\n## 研究问题\n\n完整正文 [P1]。')=='## 研究问题\n\n完整正文 [P1]。'
    assert document_body('## 研究问题\n\n完整正文。')=='## 研究问题\n\n完整正文。'


def test_large_context_can_edit_complete_chinese_manuscript(client,monkeypatch):
    from test_library_reviews import setup
    from app.db.engine import get_engine
    from app.models import Provider, Model
    prefix,fake,_=setup(client,monkeypatch)
    with Session(get_engine()) as session:
        session.add(Provider(id=123,name='fixture',type='openai_compat',base_url='https://test.invalid'))
        session.flush()
        session.add(Model(provider_id=123,model_id='fake',context_window=131072));session.commit()
    original=fake.complete;whole=[]
    def complete(provider,model,messages,**kwargs):
        text=messages[-1]['content']
        assert total_tokens(messages)+kwargs['max_tokens']<=131072
        if '只写当前章节' in text:
            return SimpleNamespace(content='机制比较应保留不同方法的适用条件与实际原文依据。[P1]\n\n'*80)
        if '完成整篇修订' in text:
            whole.append(text)
            assert all('## '+title in text for title in ('研究问题','方法比较','结果与局限'))
            return SimpleNamespace(content='## 研究问题\n\n原文与条件。[P1]\n\n## 方法比较\n\n比较机制。[P2]\n\n## 结果与局限\n\n保留边界。[P3]')
        assert '修订当前正文片段' not in text
        return original(provider,model,messages,**kwargs)
    fake.complete=complete
    client.post(prefix+'/run');result=client.get(prefix).json()
    assert result['status']=='ready' and len(whole)==1


@pytest.mark.parametrize('window',[8192,32768])
@pytest.mark.parametrize('recover',[True,False])
def test_partial_revision_recovers_or_keeps_complete_chapters(client,monkeypatch,window,recover):
    from test_library_reviews import setup
    from app.models import Provider,Model
    from app.db.engine import get_engine
    prefix,fake,_=setup(client,monkeypatch)
    with Session(get_engine()) as s:
        s.add(Provider(id=123,name='fixture',type='openai_compat',base_url='https://test.invalid'));s.flush()
        # 显式 low：本用例测“截断→学习更大额度→重试恢复”路径，卡 24 的 high 默认
        # 会把推理预留一次给足（cap 触及 window/2 上限），该学习路径不可达。
        s.add(Model(provider_id=123,model_id='fake',context_window=window,reasoning_effort='low'));s.commit()
    original=fake.complete;edits=[]
    def complete(provider,model,messages,**kwargs):
        text=messages[-1]['content']
        if '只写当前章节' in text:
            return SimpleNamespace(content=('各方法保留不同实验条件与机制。[P1]\n\n'*100 if window==8192 else '完整的章节内容 [P1]。')+'章节尾部证据。')
        if '完成整篇修订' in text or '修订当前正文片段' in text:
            # Evidence may shrink on retry; identify the call pair by output cap.
            assert total_tokens(messages)+kwargs['max_tokens']<=window
            edits.append(kwargs['max_tokens'])
            if len(edits)==1:
                return SimpleNamespace(content='残缺修订',output_incomplete=True,output_exhausted=True)
            if len(edits)==2:assert edits[-1]>edits[-2]
            if recover:return SimpleNamespace(content='完整恢复的修订 [P1]。')
            raise TimeoutError('fixture')
        return original(provider,model,messages,**kwargs)
    fake.complete=complete
    client.post(prefix+'/run');result=client.get(prefix).json()
    assert result['status']=='ready' and edits
    assert '残缺修订' not in result['content']
    if recover:
        assert '完整恢复的修订' in result['content'] and not result['error']
    else:
        assert result['content'].count('章节尾部证据。')==3
        assert '已保留已有内容' in result['error']
        analysis_count=sum('逐篇分析。' in text for text in fake.calls)
        def retry(provider,model,messages,**kwargs):
            text=messages[-1]['content']
            # Once the fallback manuscript is published, continuation updates
            # that current manuscript rather than discarding it for old drafts.
            if '完成整篇修订' in text or '修订当前正文片段' in text:
                # No researcher edit followed the partial initial publication;
                # finish its existing generation checkpoints in that case.
                assert total_tokens(messages)+kwargs['max_tokens']<=window
                return SimpleNamespace(content='重新完成的修订 [P1]。')
            return original(provider,model,messages,**kwargs)
        fake.complete=retry
        client.post(prefix+'/run');result=client.get(prefix).json()
        assert '重新完成的修订' in result['content'] and not result['error']
        assert sum('逐篇分析。' in text for text in fake.calls)==analysis_count
