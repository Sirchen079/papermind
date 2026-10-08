import json
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Paper
from app.models.card import PaperCard
from app.models.review import ReviewMap
from app.reviews import service

BACKEND = Path(__file__).resolve().parent.parent

VALID_CARD = json.dumps({
    'problem': {'value': '稀疏恢复问题', 'quote': ''},
    'mechanism': {'value': '检索增强机制', 'quote': ''},
    'data_setting': {'value': '合成数据', 'quote': ''},
    'contributions': [{'value': '提升效果', 'quote': ''}],
    'boundary': {'value': '需核对原文', 'quote': ''},
})


def themes_payload(n=7):
    return json.dumps({'themes': [
        {'id': f'T{i}', 'name': f'主题{i}', 'definition': f'解决问题{i}的机制', 'include': '纳入', 'exclude': '不纳入'}
        for i in range(1, n + 1)
    ]}, ensure_ascii=False)


class FakeMapModel:
    """按提示内容返回固定 JSON；记录每次调用供测试断言。"""

    def __init__(self, propose_responses=None, card_payload=VALID_CARD):
        self.propose_responses = propose_responses if propose_responses is not None else [themes_payload()]
        self.merge_response = themes_payload()
        self.card_payload = card_payload
        self.propose_users, self.merge_users, self.assign_users = [], [], []

    def complete(self, provider, model, messages, **kwargs):
        system, user = messages[0]['content'], messages[-1]['content']
        if '论文精读卡片' in system:
            return SimpleNamespace(content=self.card_payload)
        if '请提出 6 到 10 个研究主题' in system:
            self.propose_users.append(user)
            payload = self.propose_responses.pop(0) if self.propose_responses else themes_payload()
            return SimpleNamespace(content=payload)
        if '合并含义重复的主题' in system:
            self.merge_users.append(user)
            return SimpleNamespace(content=self.merge_response)
        if '分配 1 到 2 个最贴切的主题 id' in system:
            self.assign_users.append(user)
            return SimpleNamespace(content=self.assign_for(user))
        raise AssertionError(f'unexpected prompt: {system[:40]} / {user[:40]}')

    @staticmethod
    def assign_for(user):
        ids = [int(m) for m in re.findall(r'^\[P(\d+)\]', user, re.M)]
        return json.dumps({'assignments': [
            {'paper_id': pid, 'themes': [f'T{pid % 7 + 1}'], 'reason': '机制匹配'} for pid in ids
        ]}, ensure_ascii=False)


def setup_map(client, monkeypatch, count=8, fake=None, abstract='Study of retrieval augmentation methods.'):
    with Session(get_engine()) as s:
        rows = [Paper(source='manual', title=f'Paper {i}', year=2020, abstract=abstract) for i in range(count)]
        s.add_all(rows)
        s.commit()
        ids = [r.id for r in rows]
    fake = fake or FakeMapModel()
    monkeypatch.setattr(service, 'pick_llm', lambda *_: (fake, SimpleNamespace(id=7, base_url=''), 'map-fake'))
    monkeypatch.setattr('app.rag.scalable.hybrid', lambda *a, **k: [])
    response = client.post('/api/reviews', json={'request_id': str(uuid4()), 'question': '地图综述', 'paper_ids': ids})
    assert response.status_code == 201, response.text
    return '/api/reviews/' + response.json()['id'], fake, ids


def test_map_full_run_ready_with_themes_and_assignments(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=8)
    assert client.post(prefix + '/map/run').status_code == 202
    result = client.get(prefix + '/map').json()
    assert result['status'] == 'ready', result['error']
    assert result['stage'] == '文献地图已生成' and result['version'] == 1
    assert len(result['themes']) == 7
    assert [t['id'] for t in result['themes']] == [f'T{i}' for i in range(1, 8)]
    assert set(result['assignments']) == {str(pid) for pid in ids}
    assert all(1 <= len(a['themes']) <= 2 for a in result['assignments'].values())
    assert result['counts'] == {'papers': 8, 'cards_done': 8, 'assigned': 8, 'unassigned': 0}


def test_map_propose_retries_once_then_fails_persistently(client, monkeypatch):
    # 第一次返回 4 个主题（不足 6），重试后正确 → 继续
    prefix, fake, ids = setup_map(client, monkeypatch, count=8,
                                  fake=FakeMapModel(propose_responses=[themes_payload(4), themes_payload(7)]))
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    assert result['status'] == 'ready' and len(result['themes']) == 7
    assert len(fake.propose_users) == 2
    # 重试仍不足 → failed
    prefix2, fake2, _ = setup_map(client, monkeypatch, count=8,
                                  fake=FakeMapModel(propose_responses=[themes_payload(4), themes_payload(4)]))
    client.post(prefix2 + '/map/run')
    result2 = client.get(prefix2 + '/map').json()
    assert result2['status'] == 'failed'
    assert result2['error'] == '主题提出失败，可重新运行'
    assert len(fake2.propose_users) == 2


def test_map_assignment_drops_unknown_ids_and_truncates_to_two(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=3)

    def assign_for(user):
        pids = [int(m) for m in re.findall(r'^\[P(\d+)\]', user, re.M)]
        if len(pids) == 3:  # 首轮整批
            return json.dumps({'assignments': [
                {'paper_id': pids[0], 'themes': ['T99', 'T1', 'T2', 'T3'], 'reason': '未知与超量'},
                {'paper_id': pids[1], 'themes': ['T2'], 'reason': '单个'},
            ]}, ensure_ascii=False)
        return json.dumps({'assignments': [
            {'paper_id': pid, 'themes': ['T3'], 'reason': '重试'} for pid in pids
        ]}, ensure_ascii=False)

    fake.assign_for = staticmethod(assign_for)
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    a0, a1, a2 = (result['assignments'][str(pid)] for pid in ids)
    assert a0['themes'] == ['T1', 'T2']  # T99 丢弃，3 个截到 2
    assert a1['themes'] == ['T2']
    assert a2['themes'] == ['T3']  # 首轮缺失 → 重试补上


def test_map_assignment_retries_only_missing_papers(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=4)
    first_call = {'n': 0}

    def assign_for(user):
        pids = [int(m) for m in re.findall(r'^\[P(\d+)\]', user, re.M)]
        if len(pids) == 4:  # 首轮整批
            return json.dumps({'assignments': [
                {'paper_id': pid, 'themes': ['T1'], 'reason': '首轮'} for pid in pids[:2]
            ]}, ensure_ascii=False)
        return json.dumps({'assignments': [
            {'paper_id': pid, 'themes': ['T3'], 'reason': '重试'} for pid in pids
        ]}, ensure_ascii=False)

    fake.assign_for = staticmethod(assign_for)
    client.post(prefix + '/map/run')
    assert len(fake.assign_users) == 2
    retry_lines = fake.assign_users[1]
    assert sorted(int(m) for m in re.findall(r'^\[P(\d+)\]', retry_lines, re.M)) == sorted(ids[2:])
    result = client.get(prefix + '/map').json()
    assert result['assignments'][str(ids[2])]['themes'] == ['T3']
    assert result['assignments'][str(ids[3])]['themes'] == ['T3']


def test_map_rerun_reuses_cards_and_themes_without_model_calls(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=8)
    client.post(prefix + '/map/run')
    propose, assign = len(fake.propose_users), len(fake.assign_users)
    client.post(prefix + '/map/run')
    assert len(fake.propose_users) == propose
    assert len(fake.assign_users) == assign
    result = client.get(prefix + '/map').json()
    assert result['status'] == 'ready' and result['version'] == 2


def test_map_rerun_keeps_researcher_edited_themes(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=5)
    edited = [{'id': 'X1', 'name': '研究者定义', 'definition': '自定义路线', 'include': 'a', 'exclude': 'b'}]
    with Session(get_engine()) as s:
        review_id = prefix.rsplit('/', 1)[-1]
        row = s.exec(select(ReviewMap).where(ReviewMap.review_id == review_id)).first() or ReviewMap(review_id=review_id)
        s.add(row)
        s.commit()
    with Session(get_engine()) as s:
        row = s.exec(select(ReviewMap).where(ReviewMap.review_id == review_id)).first()
        row.themes_json = service.encode(edited)
        row.themes_fingerprint = service.digest(edited)
        s.add(row)
        s.commit()
    client.post(prefix + '/map/run')
    assert fake.propose_users == []  # 研究者改过的主题不覆盖
    result = client.get(prefix + '/map').json()
    assert result['themes'] == edited
    assert result['status'] == 'ready'


def test_map_run_conflict_while_running(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=2)
    from app.reviews import map as review_map

    with Session(get_engine()) as s:
        review_map.start_map(s, prefix.rsplit('/', 1)[-1])
    res = client.post(prefix + '/map/run')
    assert res.status_code == 409
    assert '文献地图正在生成' in res.json()['detail']


def test_map_propose_batches_long_input_and_merges(client, monkeypatch):
    abstract = 'retrieval augmentation evidence. ' * 15  # 摘要行约 340 字符
    prefix, fake, ids = setup_map(client, monkeypatch, count=200, fake=FakeMapModel(card_payload='not-a-card'), abstract=abstract)
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    assert result['status'] == 'ready', result['error']
    assert len(fake.propose_users) == 4  # 200 行 / 每批 60
    assert all(user.count('\n') + 1 <= 60 for user in fake.propose_users)
    assert len(fake.merge_users) == 1
    assert len(result['themes']) == 7


def test_map_migration_upgrade_and_downgrade(tmp_path):
    db = tmp_path / 'map-mig.sqlite'
    cfg = Config(str(BACKEND / 'alembic.ini'))
    cfg.set_main_option('script_location', str(BACKEND / 'migrations'))
    cfg.set_main_option('sqlalchemy.url', f'sqlite:///{db}')
    command.upgrade(cfg, 'head')
    inspector = inspect(create_engine(f'sqlite:///{db}'))
    assert 'reviewmap' in inspector.get_table_names()
    columns = {column['name'] for column in inspector.get_columns('reviewmap')}
    assert {'id', 'review_id', 'status', 'stage', 'run_token', 'error', 'themes_json',
            'themes_fingerprint', 'assignments_json', 'syntheses_json', 'overview_json',
            'version', 'updated_at'} <= columns
    uniques = {tuple(uq['column_names']) for uq in inspector.get_unique_constraints('reviewmap')}
    indexes = {tuple(ix['column_names']) for ix in inspector.get_indexes('reviewmap')}
    assert ('review_id',) in uniques | indexes
    command.downgrade(cfg, 'd7b4c2e9f6a3')
    inspector = inspect(create_engine(f'sqlite:///{db}'))
    assert 'reviewmap' not in inspector.get_table_names()
    assert 'papercard' in inspector.get_table_names()
