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
        self.synth_users = []
        self.synthesize = self.default_synthesize
        self.overview_users = []
        self.overview = self.default_overview
        self.fail_all = False
        self.fail_assign_calls = 0  # 前 N 次归类调用抛 RuntimeError

    @staticmethod
    def default_overview(user):
        data = json.loads(user)
        pool = sorted({r['paper_id'] for t in data['themes'] for r in t['representative']})
        return json.dumps({
            'summary': '主要路线围绕检索增强，证据以合成数据为主，实测闭环不足。',
            'reading_route': [
                {'step': 1, 'goal': '理解基本问题', 'papers': pool[:2], 'why': '开创'},
                {'step': 2, 'goal': '掌握主流机制', 'papers': pool[2:4], 'why': '代表性改进'},
                {'step': 3, 'goal': '进入前沿', 'papers': pool[4:6], 'why': '最新进展'},
            ],
            'research_steps': ['先复现经典基线', '在实测数据上验证', '避免只在合成数据上宣称结论'],
        }, ensure_ascii=False)

    @staticmethod
    def default_synthesize(user):
        data = json.loads(user)
        ids = [c['paper_id'] for c in data['cards']]
        return json.dumps({
            'trend': '该路线从稀疏恢复演进到检索增强。',
            'open_questions': [{'question': 'q', 'why': 'w', 'cannot_claim': 'c', 'cards': ids[:1]}],
            'combination_opportunities': [{'idea': 'i', 'expected': 'e', 'risk': 'r', 'cards': ids[:1]}],
            'representative': [{'paper_id': pid, 'why': '代表'} for pid in ids[:3]],
        }, ensure_ascii=False)

    def complete(self, provider, model, messages, **kwargs):
        system, user = messages[0]['content'], messages[-1]['content']
        if self.fail_all:
            raise RuntimeError('provider down')
        if '论文精读卡片' in system:
            payload = self.card_payload(user) if callable(self.card_payload) else self.card_payload
            return SimpleNamespace(content=payload)
        if '请提出 6 到 10 个研究主题' in system:
            self.propose_users.append(user)
            payload = self.propose_responses.pop(0) if self.propose_responses else themes_payload()
            return SimpleNamespace(content=payload)
        if '合并含义重复的主题' in system:
            self.merge_users.append(user)
            return SimpleNamespace(content=self.merge_response)
        if '分配 1 到 2 个最贴切的主题 id' in system:
            self.assign_users.append(user)
            if len(self.assign_users) <= self.fail_assign_calls:
                raise RuntimeError('assign provider down')
            return SimpleNamespace(content=self.assign_for(user))
        if '文献地图中一个研究主题的分析' in system:
            self.synth_users.append(user)
            return SimpleNamespace(content=self.synthesize(user))
        if '一份文献地图中各研究主题的分析' in system:
            self.overview_users.append(user)
            return SimpleNamespace(content=self.overview(user))
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


def test_diff_themes_classifies_rename_remove_add_and_identity():
    from app.reviews import themes as themes_mod

    old = [{'id': 'T1', 'name': 'a', 'definition': 'd', 'include': 'i', 'exclude': 'e'},
           {'id': 'T2', 'name': 'b', 'definition': 'd2', 'include': 'i', 'exclude': 'e'}]
    renamed = [dict(old[0], name='a2'), dict(old[1])]
    assert themes_mod.diff_themes(old, renamed) == {'changed': ['T1'], 'removed': [], 'added': []}
    assert themes_mod.diff_themes(old, [dict(old[0])]) == {'changed': [], 'removed': ['T2'], 'added': []}
    added = old + [dict(old[0], id='T3')]
    assert themes_mod.diff_themes(old, added) == {'changed': [], 'removed': [], 'added': ['T3']}
    assert themes_mod.diff_themes(old, [dict(t) for t in old]) == {'changed': [], 'removed': [], 'added': []}


def _seed_syntheses_and_overview(review_id):
    with Session(get_engine()) as s:
        row = s.exec(select(ReviewMap).where(ReviewMap.review_id == review_id)).first()
        row.syntheses_json = service.encode({f'T{i}': {'summary': f's{i}'} for i in range(1, 8)})
        row.overview_json = service.encode({'text': '总览'})
        s.add(row)
        s.commit()


def test_rename_theme_clears_only_affected_papers(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=8)
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    t2_papers = [pid for pid in ids if result['assignments'][str(pid)]['themes'] == ['T2']]
    _seed_syntheses_and_overview(prefix.rsplit('/', 1)[-1])
    edited = [dict(t, name='机制改名') if t['id'] == 'T2' else t for t in result['themes']]
    res = client.put(prefix + '/map/themes',
                     json={'themes': edited, 'expected_version': result['version']})
    assert res.status_code == 200, res.text
    updated = client.get(prefix + '/map').json()
    assert str(t2_papers[0]) not in updated['assignments']
    assert str(t2_papers[1]) not in updated['assignments']
    assert all(str(pid) in updated['assignments'] for pid in ids if pid not in t2_papers)
    assert set(updated['syntheses']) == {f'T{i}' for i in range(1, 8)} - {'T2'}
    assert updated['overview'] == {'text': '总览'}  # 未新增、归类未清空 → 保留
    client.post(prefix + '/map/run')
    assert sorted(int(m) for m in re.findall(r'^\[P(\d+)\]', fake.assign_users[-1], re.M)) == sorted(t2_papers)
    final = client.get(prefix + '/map').json()
    assert final['status'] == 'ready' and final['counts']['assigned'] == 8


def test_delete_theme_clears_only_its_papers(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=8)
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    t3_papers = [pid for pid in ids if 'T3' in result['assignments'][str(pid)]['themes']]
    _seed_syntheses_and_overview(prefix.rsplit('/', 1)[-1])
    edited = [t for t in result['themes'] if t['id'] != 'T3']
    res = client.put(prefix + '/map/themes',
                     json={'themes': edited, 'expected_version': result['version']})
    assert res.status_code == 200
    updated = client.get(prefix + '/map').json()
    assert all(str(pid) not in updated['assignments'] for pid in t3_papers)
    assert all(str(pid) in updated['assignments'] for pid in ids if pid not in t3_papers)
    assert 'T3' not in updated['syntheses']
    client.post(prefix + '/map/run')
    assert sorted(int(m) for m in re.findall(r'^\[P(\d+)\]', fake.assign_users[-1], re.M)) == sorted(t3_papers)


def test_add_theme_clears_all_assignments_and_overview(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=8)
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    _seed_syntheses_and_overview(prefix.rsplit('/', 1)[-1])
    edited = result['themes'] + [{'name': '新主题', 'definition': '新路线', 'include': '', 'exclude': ''}]
    res = client.put(prefix + '/map/themes',
                     json={'themes': edited, 'expected_version': result['version']})
    assert res.status_code == 200
    updated = client.get(prefix + '/map').json()
    assert updated['assignments'] == {}
    assert updated['overview'] == {}
    new_ids = [t['id'] for t in updated['themes']]
    assert new_ids[-1] == 'T8'  # 未给 id 时程序分配下一个 T 编号
    assert updated['syntheses']  # 未删除的主题综合保留
    client.post(prefix + '/map/run')
    final = client.get(prefix + '/map').json()
    assert final['counts']['assigned'] == 8  # 全部重新归类


def test_update_themes_rejects_version_conflict_and_running(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=4)
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    res = client.put(prefix + '/map/themes',
                     json={'themes': result['themes'], 'expected_version': result['version'] - 1})
    assert res.status_code == 409
    from app.reviews import map as review_map

    with Session(get_engine()) as s:
        review_map.start_map(s, prefix.rsplit('/', 1)[-1])
    res = client.put(prefix + '/map/themes',
                     json={'themes': result['themes'], 'expected_version': result['version']})
    assert res.status_code == 409
    assert '请先暂停' in res.json()['detail']


def test_theme_stats_counts_years_settings_and_evidence():
    from app.reviews import themes as themes_mod

    members = [
        {'paper_id': 1, 'year': 2021, 'evidence_level': 'full_text', 'data_setting_value': 'Marmousi 合成数据'},
        {'paper_id': 2, 'year': 2021, 'evidence_level': 'abstract', 'data_setting_value': 'field case study'},
        {'paper_id': 3, 'year': None, 'evidence_level': 'metadata', 'data_setting_value': 'Field 与 synthetic 并用'},
        {'paper_id': 4, 'year': 2020, 'evidence_level': 'abstract', 'data_setting_value': '数值模拟 numerical'},
        {'paper_id': 5, 'year': 2020, 'evidence_level': 'metadata', 'data_setting_value': ''},
    ]
    stats = themes_mod.theme_stats(members)
    assert stats['count'] == 5
    assert stats['years'] == {'2020': 2, '2021': 2, '未知': 1}
    assert stats['setting'] == {'field': 1, 'synthetic': 2, 'both': 1, 'unknown': 1}
    assert stats['evidence'] == {'full_text': 1, 'abstract': 2, 'metadata': 2}


def test_synthesis_drops_unknown_ids_and_marks_source_missing(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=6)

    def synthesize(user):
        data = json.loads(user)
        valid = [c['paper_id'] for c in data['cards']]
        return json.dumps({
            'trend': '演变说明',
            'open_questions': [
                {'question': '只引坏号', 'why': 'w', 'cannot_claim': 'c', 'cards': [999]},
                {'question': '混合', 'why': 'w', 'cannot_claim': 'c', 'cards': [999] + valid[:1]},
            ],
            'combination_opportunities': [
                {'idea': 'i', 'expected': 'e', 'risk': 'r', 'cards': [999]},
                {'idea': 'j', 'expected': 'e', 'risk': 'r', 'cards': valid[:1]},
            ],
            'representative': [{'paper_id': valid[0], 'why': '成员'}] if valid else [],
        }, ensure_ascii=False)

    fake.synthesize = synthesize
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    assert result['status'] == 'ready', result['error']
    for entry in result['syntheses'].values():
        questions = entry['open_questions']
        combos = entry['combination_opportunities']
        assert questions[0]['cards'] == [] and questions[0]['source_missing'] is True
        if entry['stats']['count']:  # 有成员的主题：混合条目保留 1 个合法编号
            assert len(questions[1]['cards']) == 1 and 999 not in questions[1]['cards']
            assert 'source_missing' not in questions[1]
            assert 'source_missing' not in combos[1]
        else:  # 空成员主题：合法编号不存在，全部按来源缺失处理
            assert questions[1]['cards'] == [] and questions[1]['source_missing'] is True
        assert combos[0]['cards'] == [] and combos[0]['source_missing'] is True
        assert all(rep['paper_id'] != 999 for rep in entry['representative'])


def test_synthesis_representative_must_be_theme_member(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=8)
    all_ids = list(ids)

    def synthesize(user):
        data = json.loads(user)
        members = {c['paper_id'] for c in data['cards']}
        outsiders = [p for p in all_ids if p not in members][:2]
        return json.dumps({
            'trend': 't',
            'open_questions': [],
            'combination_opportunities': [],
            'representative': [{'paper_id': p, 'why': 'x'} for p in outsiders]
            + [{'paper_id': p, 'why': '成员'} for p in sorted(members)[:1]],
        }, ensure_ascii=False)

    fake.synthesize = synthesize
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    assert result['status'] == 'ready'
    assignments = result['assignments']
    for tid, entry in result['syntheses'].items():
        members = {int(pid) for pid, a in assignments.items() if tid in a['themes']}
        for rep in entry['representative']:
            assert rep['paper_id'] in members
        assert len(entry['representative']) == 1  # 非成员条目被删


VERIFIED_CARD = json.dumps({
    'problem': {'value': '稀疏恢复问题', 'quote': 'Study of retrieval augmentation methods.'},
    'mechanism': {'value': '检索增强机制', 'quote': 'Study of retrieval augmentation methods.'},
    'data_setting': {'value': '合成数据', 'quote': 'Study of retrieval augmentation methods.'},
    'contributions': [{'value': '提升效果', 'quote': 'Study of retrieval augmentation methods.'}],
    'boundary': {'value': '需核对原文', 'quote': 'Study of retrieval augmentation methods.'},
})


def test_synthesis_caps_full_cards_at_40_ranked_by_verified_fields(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=45)
    fake.card_payload = lambda user: VERIFIED_CARD if '"title": "Paper 44"' in user else VALID_CARD
    fake.assign_for = staticmethod(lambda user: json.dumps({'assignments': [
        {'paper_id': int(m), 'themes': ['T1'], 'reason': 'r'} for m in re.findall(r'^\[P(\d+)\]', user, re.M)
    ]}, ensure_ascii=False))
    client.post(prefix + '/map/run')
    t1_user = next(u for u in fake.synth_users if json.loads(u)['theme']['id'] == 'T1')
    data = json.loads(t1_user)
    cards = data['cards']
    assert len(cards) == 45
    full = [c for c in cards if 'problem' in c]
    brief = [c for c in cards if 'problem' not in c]
    assert len(full) == 40 and len(brief) == 5
    assert full[0]['paper_id'] == ids[44]  # 已核对字段数最多的排最前
    assert all(set(c) == {'paper_id', 'year', 'title'} for c in brief)
    result = client.get(prefix + '/map').json()
    assert result['syntheses']['T1']['stats']['count'] == 45


def test_synthesis_failure_isolated_other_themes_and_map_ready(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=6)

    def synthesize(user):
        data = json.loads(user)
        if data['theme']['id'] == 'T2':
            return 'not-json'
        return FakeMapModel.default_synthesize(user)

    fake.synthesize = synthesize
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    assert result['status'] == 'ready', result['error']
    assert result['syntheses']['T2']['error'] == '本主题综合未完成，可重新运行'
    assert 'stats' in result['syntheses']['T2'] and 'fingerprint' not in result['syntheses']['T2']
    others = [e for tid, e in result['syntheses'].items() if tid != 'T2']
    assert others and all('trend' in e for e in others)
    assert sum(1 for u in fake.synth_users if json.loads(u)['theme']['id'] == 'T2') == 2  # 重试一次


def test_synthesis_reuses_cache_and_partial_rerun_after_theme_edit(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=8)
    client.post(prefix + '/map/run')
    base = len(fake.synth_users)
    client.post(prefix + '/map/run')  # 无变化 → 全部跳过
    assert len(fake.synth_users) == base
    result = client.get(prefix + '/map').json()
    edited = [dict(t, name='改名') if t['id'] == 'T2' else t for t in result['themes']]
    res = client.put(prefix + '/map/themes', json={'themes': edited, 'expected_version': result['version']})
    assert res.status_code == 200
    client.post(prefix + '/map/run')
    assert len(fake.synth_users) == base + 1  # 只重新综合被改的主题
    assert json.loads(fake.synth_users[-1])['theme']['id'] == 'T2'
    final = client.get(prefix + '/map').json()
    assert final['status'] == 'ready' and set(final['syntheses']) == {f'T{i}' for i in range(1, 8)}


def test_overview_full_run_has_summary_route_and_steps(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=8)
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    assert result['status'] == 'ready', result['error']
    overview = result['overview']
    assert overview['summary']
    assert 3 <= len(overview['reading_route']) <= 5
    assert all('goal' in step and 'papers' in step and 'why' in step for step in overview['reading_route'])
    assert len(overview['research_steps']) >= 3
    assert 'fingerprint' in overview


def test_overview_drops_unknown_ids_and_marks_missing_steps(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=8)

    def overview(user):
        data = json.loads(user)
        known = sorted({r['paper_id'] for t in data['themes'] for r in t['representative']})
        return json.dumps({
            'summary': 's',
            'reading_route': [
                {'step': 1, 'goal': 'g1', 'papers': [999, known[0]], 'why': 'w'},
                {'step': 2, 'goal': 'g2', 'papers': [999], 'why': 'w'},
            ],
            'research_steps': ['a', 'b'],
        }, ensure_ascii=False)

    fake.overview = overview
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    route = result['overview']['reading_route']
    assert route[0]['papers'] == [result['overview']['reading_route'][0]['papers'][0]] and 999 not in route[0]['papers']
    assert route[1]['papers'] == [] and route[1]['source_missing'] is True


def test_overview_reuses_cache_and_regenerates_after_theme_change(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=8)
    client.post(prefix + '/map/run')
    base = len(fake.overview_users)
    client.post(prefix + '/map/run')  # 无变化 → 跳过
    assert len(fake.overview_users) == base
    result = client.get(prefix + '/map').json()
    edited = [dict(t, name='改名') if t['id'] == 'T3' else t for t in result['themes']]
    client.put(prefix + '/map/themes', json={'themes': edited, 'expected_version': result['version']})
    client.post(prefix + '/map/run')  # T3 综合指纹变化 → 总览重新生成
    assert len(fake.overview_users) == base + 1
    assert client.get(prefix + '/map').json()['status'] == 'ready'


def test_overview_failure_keeps_map_ready(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=6)
    fake.overview = lambda user: 'not-json'
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    assert result['status'] == 'ready', result['error']
    assert result['overview']['error'] == '总览未完成，可重新运行'
    assert len(fake.overview_users) == 2  # 重试一次


def test_map_detail_includes_papers_with_themes_and_evidence(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=8)
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    papers = result['papers']
    assert len(papers) == 8
    assert {p['paper_id'] for p in papers} == set(ids)
    for paper in papers:
        assert {'paper_id', 'title', 'year', 'venue', 'doi', 'themes', 'evidence_level',
                'card_status'} <= set(paper)
        assert isinstance(paper['themes'], list) and paper['themes']
        assert paper['evidence_level'] == 'abstract' and paper['card_status'] == 'done'
    by_id = {p['paper_id']: p for p in papers}
    assert by_id[ids[0]]['title'] == 'Paper 0' and by_id[ids[0]]['year'] == 2020


def test_map_assign_batch_error_keeps_ready_and_rerun_fixes(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=8)
    fake.fail_assign_calls = 1  # 第一批归类抛一次 RuntimeError
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    assert result['status'] == 'ready', result['error']
    failed = [pid for pid in ids if result['assignments'][str(pid)]['themes'] == []]
    assert failed and '未能归类' in result['stage'] and '可点击继续补齐' in result['stage']
    client.post(prefix + '/map/run')
    final = client.get(prefix + '/map').json()
    assert all(final['assignments'][str(pid)]['themes'] for pid in ids)
    assert final['stage'] == '文献地图已生成'


def test_map_all_calls_failing_marks_map_failed(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=8)
    fake.fail_all = True
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    assert result['status'] == 'failed'
    assert '模型连续' in result['error']
    assert '请检查模型设置后点击继续' in result['error']


def test_map_synth_exception_isolated_to_theme(client, monkeypatch):
    prefix, fake, ids = setup_map(client, monkeypatch, count=6)

    def synthesize(user):
        data = json.loads(user)
        if data['theme']['id'] == 'T2':
            raise RuntimeError('synth provider down')
        return FakeMapModel.default_synthesize(user)

    fake.synthesize = synthesize
    client.post(prefix + '/map/run')
    result = client.get(prefix + '/map').json()
    assert result['status'] == 'ready', result['error']
    assert result['syntheses']['T2']['error'] == '本主题综合未完成，可重新运行'
    others = [e for tid, e in result['syntheses'].items() if tid != 'T2']
    assert others and all('trend' in e for e in others)
    assert '主题综合未完成' in result['stage']
