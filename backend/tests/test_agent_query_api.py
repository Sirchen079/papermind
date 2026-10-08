import json

from sqlmodel import Session

from app.config import get_settings
from app.db.engine import get_engine
from app.models import Paper, PaperChunk
from app.rag import scalable
from app.security.local_token import get_or_create_token, reset_token_cache


def local_token():
    reset_token_cache()
    return get_or_create_token()


def make_library():
    with Session(get_engine()) as session:
        paper = Paper(title='Hybrid retrieval for waveform inversion', source='pdf', year=2024)
        session.add(paper)
        session.commit()
        session.refresh(paper)
        session.add(PaperChunk(paper_id=paper.id, ordinal=0, text='Abstract about retrieval baselines.',
                               embedding_model='test'))
        session.add(PaperChunk(paper_id=paper.id, ordinal=1,
                               text='[第 3 页] The Landmark paper reports BGE sentence accuracy 39.8 on the benchmark.',
                               embedding_model='test'))
        session.commit()
        return paper.id


def test_agent_endpoints_require_local_token(client):
    assert client.get('/api/agent/summary').status_code == 403
    assert client.get('/api/agent/search', params={'q': 'retrieval'}).status_code == 403


def test_agent_summary_reports_library(client):
    pid = make_library()
    body = client.get('/api/agent/summary', headers={'X-Local-Token': local_token()}).json()
    assert body['app'] == 'PaperMind'
    assert body['papers']['total'] >= 1
    assert any(item['id'] == pid for item in body['papers']['recent'])
    assert 'recent' in body['saved_documents']


def test_agent_search_uses_agent_retrieval_with_keyword_fallback(client, monkeypatch):
    pid = make_library()
    headers = {'X-Local-Token': local_token()}
    # No embedding provider is configured in tests; force the fallback so the
    # result is deterministic and matches the in-app degradation path.
    def unavailable(*args, **kwargs):
        raise RuntimeError('embedding provider unavailable')

    monkeypatch.setattr(scalable, 'hybrid', unavailable)
    rows = client.get('/api/agent/search', params={'q': 'Landmark BGE accuracy'}, headers=headers).json()
    assert rows and rows[0]['paper_id'] == pid
    assert '39.8' in rows[0]['text']
    assert rows[0]['retrieval_mode'] == 'keyword_fallback'
    assert rows[0]['pages'] == [3]

    scoped = client.get('/api/agent/search', params={'q': 'Landmark', 'paper_ids': str(pid)},
                        headers=headers).json()
    assert scoped and scoped[0]['paper_id'] == pid
    assert client.get('/api/agent/search', params={'q': 'x', 'paper_ids': 'a,b'},
                      headers=headers).status_code == 422
