import pytest
from app.wiki.citations import model_payload,resolve_citations


def test_aliases_keep_stable_ids_and_do_not_modify_input():
    ref='W'+'a'*24
    inputs={'evidence':[{'ref':ref}],'model_evidence':[{'ref':ref,'quote':'evidence'}],'prior_content':'old ['+ref+']'}
    payload,aliases=model_payload(inputs)
    assert payload['model_evidence'][0]['ref']=='S1'
    assert payload['prior_content']=='old [S1]'
    assert 'evidence' not in payload
    assert inputs['model_evidence'][0]['ref']==ref
    assert resolve_citations('fact [S1]',aliases)==('fact ['+ref+']',[ref])


def test_grouped_citations_and_repeated_refs_have_one_derived_list():
    a,b='W'+'a'*24,'A'+'b'*24
    text,refs=resolve_citations('both [S2, S1] again [S2] [link](https://example.org)',{'S1':a,'S2':b})
    assert refs==[b,a]
    assert text=='both ['+b+']['+a+'] again ['+b+'] [link](https://example.org)'


@pytest.mark.parametrize('text',['unsupported [S9]','mixed [S1, S9]','no source','forged [W'+'f'*24+']','range [S1-S9]'])
def test_unknown_missing_and_ambiguous_citations_are_rejected(text):
    with pytest.raises(ValueError):
        resolve_citations(text,{'S1':'W'+'a'*24})


@pytest.mark.parametrize('bad',['```json\n{"content":','{"content":"wrong [S9]","change_note":"x"}'])
def test_truncated_json_and_unknown_reference_are_regenerated_once(bad):
    import json
    from types import SimpleNamespace
    from app.wiki.service import generate_document
    calls=[]
    def complete(*args,**kwargs):
        calls.append(kwargs['max_tokens'])
        return SimpleNamespace(content=bad if len(calls)==1 else json.dumps({'content':'supported [S1]','change_note':'x'}))
    result=generate_document(SimpleNamespace(complete=complete),None,'m',{'model_evidence':[{'ref':'S1','quote':'source'}]}, {'S1':'W'+'a'*24},(10000,4000),'job')
    assert result['content']=='supported [S1]' and len(calls)==2
