"""The agent tool-step budget (`agent_max_iters` setting) as read by chat_api."""
from sqlmodel import Session

from app.api.chat_api import _max_iters
from app.db.engine import get_engine
from app.models import Setting


def _put(key: str, value: str):
    with Session(get_engine()) as s:
        s.merge(Setting(key=key, value=value))
        s.commit()


def test_max_iters_defaults_to_100(client):
    with Session(get_engine()) as s:
        assert _max_iters(s) == 100


def test_max_iters_reads_setting(client):
    _put('agent_max_iters', '24')
    with Session(get_engine()) as s:
        assert _max_iters(s) == 24


def test_max_iters_clamps_and_falls_back(client):
    _put('agent_max_iters', '1000')
    with Session(get_engine()) as s:
        assert _max_iters(s) == 200
    _put('agent_max_iters', '2')
    with Session(get_engine()) as s:
        assert _max_iters(s) == 4
    _put('agent_max_iters', 'not-a-number')
    with Session(get_engine()) as s:
        assert _max_iters(s) == 100
    _put('agent_max_iters', '')
    with Session(get_engine()) as s:
        assert _max_iters(s) == 100
