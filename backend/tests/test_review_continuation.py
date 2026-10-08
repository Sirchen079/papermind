from types import SimpleNamespace
from sqlmodel import Session, select
from app.db.engine import get_engine
from app.models import Paper
from app.models.review import ReviewSection
from test_library_reviews import setup
import pytest


def test_unchanged_run_preserves_manual_correction_without_writing_calls(client,monkeypatch):
    prefix,fake,ids=setup(client,monkeypatch,count=2)
    client.post(prefix+'/run')
    first=client.get(prefix).json()
    corrected=first['content'].replace('不同设置不能直接排名。','只支持已核对数据集；候选解释未被验证。')
    saved=client.post(prefix+'/content',json={'content':corrected,'expected_version':first['version']}).json()
    calls=len(fake.calls)
    client.post(prefix+'/run')
    resumed=client.get(prefix).json()
    assert resumed['content']==corrected
    assert resumed['version']==saved['version']
    assert len(fake.calls)==calls
    assert resumed['counts']['reused']==2


def test_new_paper_update_receives_current_version_and_retains_it_on_failure(client,monkeypatch):
    prefix,fake,ids=setup(client,monkeypatch,count=2)
    client.post(prefix+'/run')
    first=client.get(prefix).json()
    correction='人工核对：只支持数据集甲；未报告不能改为未执行。'
    corrected=first['content'].replace('不同设置不能直接排名。',correction)
    client.post(prefix+'/content',json={'content':corrected,'expected_version':first['version']})
    with Session(get_engine()) as s:
        new=Paper(source='manual',title='New evidence',abstract='A new study with a different dataset.')
        s.add(new);s.commit();new_id=new.id
    client.post(prefix+'/papers',json={'paper_ids':[new_id]})
    original=fake.complete;edits=[]
    def complete(provider,model,messages,**kwargs):
        text=messages[-1]['content']
        if '当前版本的综述正文' in text:
            edits.append(text)
            raise TimeoutError('test update failure')
        return original(provider,model,messages,**kwargs)
    monkeypatch.setattr(fake,'complete',complete)
    client.post(prefix+'/run')
    result=client.get(prefix).json()
    assert edits and all(correction in text for text in edits)
    assert correction in result['content']
    assert result['counts']['total']==3 and result['counts']['reused']==2
    assert result['error']
    # A failed update remains retryable, rather than being declared unchanged.
    before=len(edits);client.post(prefix+'/run')
    assert len(edits)>before


def test_legacy_review_without_publication_checkpoint_uses_current_draft(client,monkeypatch):
    prefix,fake,ids=setup(client,monkeypatch,count=1)
    client.post(prefix+'/run')
    first=client.get(prefix).json()
    corrected='## 核对后的范围\n\n研究者限定的比较条件 [P%d]。'%ids[0]
    client.post(prefix+'/content',json={'content':corrected,'expected_version':first['version']})
    with Session(get_engine()) as s:
        row=s.exec(select(ReviewSection).where(ReviewSection.review_id==prefix.rsplit('/',1)[1],ReviewSection.ordinal==-99994)).first()
        if row:s.delete(row);s.commit()
    original=fake.complete;seen=[]
    def complete(provider,model,messages,**kwargs):
        if '当前版本的综述正文' in messages[-1]['content']:
            seen.append(messages[-1]['content']);return SimpleNamespace(content='{"edits":[]}')
        return original(provider,model,messages,**kwargs)
    monkeypatch.setattr(fake,'complete',complete)
    client.post(prefix+'/run')
    assert seen and corrected in seen[0]
    assert corrected in client.get(prefix).json()['content']


@pytest.mark.parametrize('references',['','- [P1] Paper 1'])
def test_current_body_keeps_user_notes_after_managed_footer(references):
    from app.reviews.continuation import body
    text=('# Topic\n\n## Corrected scope\n\nExact constraint.\n\n## 引用文献\n\n'+references+
          '\n\n## 材料范围\n\n本次范围 1 篇；完成模型分析 1 篇，使用摘录或已有内容 0 篇，缺少可读材料 0 篇。'
          '正文按主题选用相关文献，并非每篇都会被引用。全文分析使用选取的相关片段；这份综述基于本次材料范围。\n'
          '\n## User addendum\n\nKeep this too.')
    result=body(text)
    assert 'Exact constraint.' in result and 'Keep this too.' in result
    assert '## 引用文献' not in result and '## 材料范围' not in result


def test_long_current_manuscript_is_segmented_and_not_replaced_by_candidates(client,monkeypatch):
    from app.models import Provider,Model
    from app.agent.context import total_tokens
    prefix,fake,ids=setup(client,monkeypatch,count=1)
    with Session(get_engine()) as s:
        s.add(Provider(id=123,name='fixture',type='openai_chat',base_url='https://test.invalid'));s.commit()
        s.add(Model(provider_id=123,model_id='fake',context_window=8192));s.commit()
    client.post(prefix+'/run');first=client.get(prefix).json()
    paragraphs=[f'核对条件{i}：'+('同一数据条件下保留研究者纠正。'*25) for i in range(35)]
    corrected='## Current scope\n\n'+'\n\n'.join(paragraphs)
    client.post(prefix+'/content',json={'content':corrected,'expected_version':first['version']})
    with Session(get_engine()) as s:
        paper=s.get(Paper,ids[0]);paper.full_text+=' New evidence.';s.add(paper);s.commit()
    original=fake.complete;seen=[]
    def complete(provider,model,messages,**kwargs):
        text=messages[-1]['content']
        if '本次只更新给出的正文片段' in text:
            assert total_tokens(messages)+kwargs['max_tokens']<=8192
            seen.append(text)
            return SimpleNamespace(content='',output_incomplete=False)
        return original(provider,model,messages,**kwargs)
    monkeypatch.setattr(fake,'complete',complete)
    client.post(prefix+'/run');result=client.get(prefix).json()
    assert len(seen)>2
    assert all(any(p in text for text in seen) for p in paragraphs)
    assert corrected in result['content'] and result['error']
