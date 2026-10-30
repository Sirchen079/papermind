"""Researcher corrections survive regeneration and reach downstream updates."""
import json

from sqlmodel import Session, select
from app.db.engine import get_engine
from app.models.card import PaperCard
from app.reviews.cards import save_card
from test_review_map import setup_map


def test_edit_conflict_history_and_regeneration(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=1)
    client.post(prefix + '/map/run')
    entry = client.get(prefix + '/cards').json()[0]
    payload = dict(field='data_setting', value='仅验证了合成数据', quote='', expected_version=entry['version'])
    saved = client.post(prefix + f'/cards/{ids[0]}', json=payload)
    assert saved.status_code == 200, saved.text
    edited = saved.json()
    assert edited['card']['data_setting']['researcher_edited']
    assert edited['card']['data_setting']['status'] == 'no_quote'
    assert edited['card']['manual_fields']['data_setting']['original']['value'] == '合成数据'
    assert client.post(prefix + f'/cards/{ids[0]}', json=payload).status_code == 409
    # Regeneration from changed source/model cannot erase the saved correction.
    with Session(get_engine()) as s:
        row = s.exec(select(PaperCard).where(PaperCard.paper_id == ids[0])).one()
        result = dict(status='done', card=entry['card'], warning='')
        save_card(s, ids[0], row.fingerprint + '-new', result, 'new-model')
    latest = client.get(prefix + '/cards').json()[0]
    assert latest['card']['data_setting']['value'] == payload['value']
    assert len(latest['card']['edit_history']) == 1
    payload.update(value='仍未验证实测数据', expected_version=latest['version'])
    again = client.post(prefix + f'/cards/{ids[0]}', json=payload).json()
    assert len(again['card']['edit_history']) == 2
    assert again['card']['edit_history'][1]['before']['value'] == '仅验证了合成数据'


def test_card_correction_updates_only_affected_map_work(client, monkeypatch):
    monkeypatch.setattr('app.reviews.themes.SYNTH_FULL_CARDS', 0)
    prefix, fake, ids = setup_map(client, monkeypatch, count=8)
    client.post(prefix + '/map/run')
    entry = client.get(prefix + '/cards').json()[1]
    a, s, o = len(fake.assign_users), len(fake.synth_users), len(fake.overview_users)
    correction = '只在受控合成条件下验证，实测泛化待核对'
    result = client.post(prefix + f'/cards/{ids[1]}', json=dict(
        field='data_setting', value=correction, quote='', expected_version=entry['version']))
    assert result.status_code == 200, result.text
    assert client.get(prefix + '/map').json()['needs_update']
    # Editing a theme must not accidentally declare the corrected card up to date.
    current = client.get(prefix + '/map').json()
    client.put(prefix + '/map/themes', json=dict(themes=current['themes'], expected_version=current['version']))
    client.post(prefix + '/map/run')
    assert len(fake.assign_users) == a + 1
    assert correction in fake.assign_users[-1]
    assert len(fake.synth_users) == s + 1 and correction in fake.synth_users[-1]
    assert len(fake.overview_users) == o + 1
    assert not client.get(prefix + '/map').json()['needs_update']


def test_card_correction_reaches_review_as_researcher_record(client, monkeypatch):
    from test_library_reviews import setup
    from test_paper_cards import _card_responder
    prefix, fake, ids = setup(client, monkeypatch, count=3)
    _card_responder(fake)
    client.post(prefix + '/run')
    entry = client.get(prefix + '/cards').json()[1]
    before = len(fake.calls)
    correction = '训练只使用数据集甲，数据集乙用于测试'
    result = client.post(prefix + f'/cards/{ids[1]}', json=dict(
        field='data_setting', value=correction, quote='', expected_version=entry['version']))
    assert result.status_code == 200, result.text
    client.post(prefix + '/run')
    changed = fake.calls[before:]
    analyses = [x for x in changed if '逐篇分析。' in x]
    assert len(analyses) == 1 and correction in analyses[0]
    patches = [x for x in changed if '仅返回需要修改的段落' in x]
    assert patches and all(correction in x and '不是论文原文' in x for x in patches)
    evidence = client.get(prefix + f'/papers/{ids[1]}').json()['evidence']
    assert any(e.get('scope') == 'researcher_note' and correction in e['quote'] for e in evidence)
    before = len(fake.calls)
    client.post(prefix + '/run')
    assert len(fake.calls) == before
