from types import SimpleNamespace

from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models.provider import Model, Provider
from app.providers.client import EmptyResponseError
from app.reviews.structured import ModelUnavailable, StructuredAsker, model_window


class ScriptedClient:
    """按预设序列返回结果或抛异常，记录每次调用参数。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def complete(self, provider, model, messages, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError('脚本用尽： unexpected extra call')
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def ok(text='ok'):
    return SimpleNamespace(content=text, output_exhausted=False)


def make_asker(client, window=128000):
    return StructuredAsker(client, SimpleNamespace(id=1, base_url=''), 'fake-model',
                           ref_id='r1', window=window)


def test_budget_is_half_the_window():
    client = ScriptedClient([ok()])
    asker = make_asker(client, window=128000)
    asker.ask('s', 'u', 2000)
    assert client.calls[0]['max_tokens'] == 64000

    client = ScriptedClient([ok()])
    asker = make_asker(client, window=32768)
    asker.ask('s', 'u', 2000)
    assert client.calls[0]['max_tokens'] == 16384


def test_call_shape_no_reasoning_effort_and_library_review_kind():
    client = ScriptedClient([ok()])
    asker = make_asker(client)
    assert asker.ask('system text', 'user text', 2000) == 'ok'
    kwargs = client.calls[0]
    assert kwargs['reasoning_effort'] is None
    assert kwargs['request_kind'] == 'library_review'


def test_empty_response_is_reraised_without_retry():
    client = ScriptedClient([EmptyResponseError('empty', output_exhausted=True)])
    asker = make_asker(client)
    try:
        asker.ask('s', 'u', 2000)
        raise AssertionError('应当抛出 EmptyResponseError')
    except EmptyResponseError:
        pass
    assert len(client.calls) == 1  # 不做额度重试


def test_consecutive_errors_raise_model_unavailable_and_success_resets():
    client = ScriptedClient([RuntimeError('a'), RuntimeError('b'), RuntimeError('c')])
    asker = make_asker(client)
    for _ in range(2):
        try:
            asker.ask('s', 'u', 2000)
            raise AssertionError('应当抛出 RuntimeError')
        except ModelUnavailable:
            raise AssertionError('前两次不应是 ModelUnavailable')
        except RuntimeError:
            pass
    try:
        asker.ask('s', 'u', 2000)
        raise AssertionError('第三次应当抛出 ModelUnavailable')
    except ModelUnavailable as exc:
        assert '模型连续 3 次调用失败（RuntimeError）' in str(exc)

    client = ScriptedClient([RuntimeError('a'), ok(), RuntimeError('b'), RuntimeError('c')])
    asker = make_asker(client)
    try:
        asker.ask('s', 'u', 2000)
    except RuntimeError:
        pass
    assert asker.ask('s', 'u', 2000) == 'ok'  # 成功后计数清零
    try:
        asker.ask('s', 'u', 2000)
    except RuntimeError:
        pass
    try:
        asker.ask('s', 'u', 2000)
        raise AssertionError('连续两次后第三次应当仍是 RuntimeError，未到 3 次不应是 ModelUnavailable')
    except RuntimeError:
        pass


def test_model_window_prefers_stored_context_window(client):
    with Session(get_engine()) as s:
        provider = Provider(type='openai_chat', name='p-structured', base_url='https://test.invalid')
        s.add(provider)
        s.commit()
        s.refresh(provider)
        s.add(Model(provider_id=provider.id, model_id='wide', context_window=200000))
        s.add(Model(provider_id=provider.id, model_id='narrow'))
        s.commit()
        wide_pid, narrow_pid = provider.id, provider.id
    with Session(get_engine()) as s:
        provider = s.get(Provider, wide_pid)
        assert model_window(s, provider, 'wide') == 200000
        assert model_window(s, provider, 'narrow') == 32768  # 未配置时回退默认
        assert model_window(s, SimpleNamespace(id=999999), 'anything') == 32768
