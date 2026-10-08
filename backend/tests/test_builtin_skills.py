import hashlib
import json
import pytest
from sqlmodel import Session, select
from app.db.engine import get_engine
from app.models import Skill
from app.skills import builtin
from app.reviews.writing import guides


def test_full_bundles_match_file_inventory_and_all_routers_load():
    families=builtin.catalog()['families']
    assert {f['id'] for f in families}=={'nature','oh-my-paper'}
    for family in families:
        for path,expected in family['files'].items():
            assert hashlib.sha256((builtin.root()/family['id']/path).read_bytes()).hexdigest()==expected,path
        for entry in family['skills']:
            loaded=builtin.load(entry['id'])
            assert loaded['resources'][0]['path']=='SKILL.md'
            assert loaded['fingerprint'] and builtin.ADAPTER in loaded['text']


def test_shared_resources_pagination_and_bundle_boundary(client):
    sid='nature/nature-writing'
    full=builtin.resource_path(sid,'../nature-shared/core/terminology-ledger.md').read_text(encoding='utf-8-sig')
    result=client.get('/api/builtin-skills/resource',params={'skill_id':sid,'path':'../nature-shared/core/terminology-ledger.md'}).json()
    assert result['text']==full
    start=0;parts=[]
    while True:
        chunk=builtin.read_resource(sid,'SKILL.md',start,97);parts.append(chunk['text'])
        if chunk['next_start'] is None:break
        start=chunk['next_start']
    assert ''.join(parts)==builtin.resource_path(sid).read_text(encoding='utf-8-sig')
    assert client.get('/api/builtin-skills/resource',params={'skill_id':sid,'path':'../../../app/config.py'}).status_code==404
    assert client.get(result['download_url']).status_code==200


def test_sync_preserves_edits_and_chat_loads_core(client):
    with Session(get_engine()) as s:
        assert builtin.sync(s)==55
        skill=s.exec(select(Skill).where(Skill.name=='nature-writing')).one()
        skill.enabled=False;skill.body+='\n研究者的写作偏好';s.add(skill);s.commit()
        assert builtin.sync(s)==0
        s.refresh(skill);assert not skill.enabled and skill.body.endswith('研究者的写作偏好')
        prompt=builtin.chat_prompt(skill)
        assert '研究者的写作偏好' in prompt and 'Write the argument before writing the sentences' in prompt


def test_review_uses_actual_skill_fragments_and_fingerprints():
    nature,researcher,handoff=guides()
    assert nature['id']=='nature/nature-writing'
    assert 'A review is **not a survey list**' in nature['text']
    assert any(r['path']=='static/fragments/paper_type/review.md' for r in nature['resources'])
    assert researcher['id'].startswith('oh-my-paper/') and handoff['id'].startswith('oh-my-paper/')
    assert nature['fingerprint']!=researcher['fingerprint']
