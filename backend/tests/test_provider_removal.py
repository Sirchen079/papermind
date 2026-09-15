from datetime import date
from sqlmodel import Session, select
from app.db.engine import get_engine
from app.models import TokenUsage


def test_remove_used_provider_preserves_usage_and_hides_connection(client):
    pid=client.post('/api/providers',json={'name':'Synthetic','type':'openai_chat'}).json()['id']
    with Session(get_engine()) as session:
        session.add(TokenUsage(provider_id=pid,model='test',request_kind='chat',day=date.today(),total_tokens=17))
        session.commit()
    response=client.delete(f'/api/providers/{pid}')
    assert response.status_code==204,response.text
    assert client.get('/api/providers').json()==[]
    with Session(get_engine()) as session:
        assert session.exec(select(TokenUsage)).one().total_tokens==17
