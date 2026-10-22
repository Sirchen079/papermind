import base64
from types import SimpleNamespace
import pytest
from app.ingestion.institutional_transfer import SOURCE


def transfer():
    namespace = {}
    exec(SOURCE, namespace)
    return namespace['fetch_in_browser']


def test_pdf_uses_the_authenticated_page_and_checks_header_and_size():
    data = b'%PDF-' + b'x' * 300000
    calls = []
    def evaluate(script, arg=None):
        calls.append(script)
        if 'async (url)' in script:
            assert "credentials:'include'" in script
            return {'ok': True, 'size': len(data)}
        if arg is not None:
            return base64.b64encode(data[arg:arg+262144]).decode()
    page = SimpleNamespace(url='https://pdf.example.org/viewer', evaluate=evaluate)
    assert transfer()(page, page.url)[0] == data
    assert 'delete window.__paperMindPdf' in calls[-1]


@pytest.mark.parametrize('meta', [{'ok':False}, {'ok':True,'size':104857601}, {'ok':True,'size':0}])
def test_html_or_oversized_response_is_not_a_pdf(meta):
    page = SimpleNamespace(url='https://pdf.example.org/viewer', evaluate=lambda *args: meta)
    assert transfer()(page, page.url)[0] is None


def test_never_replays_browser_authentication_to_another_origin():
    def unexpected(*args):
        raise AssertionError('another origin must not be fetched')
    page = SimpleNamespace(url='https://library.example.org/', evaluate=unexpected)
    assert transfer()(page, 'https://other.example.org/article.pdf')[0] is None


def test_pdf_plugin_uses_context_request_and_never_waits_for_renderer_javascript():
    data = b'%PDF-' + b'x' * 100
    observed = []
    def get(url, **kwargs):
        assert kwargs['timeout'] == 90000
        observed.append(url)
        return SimpleNamespace(ok=True, headers={'content-length':str(len(data))}, body=lambda:data)
    page = SimpleNamespace(url='https://pdf.example.org/article.pdf',
        context=SimpleNamespace(request=SimpleNamespace(get=get)),
        evaluate=lambda *a: (_ for _ in ()).throw(AssertionError('PDF plugin has no usable JS context')))
    assert transfer()(page, page.url)[0] == data
    assert observed == [page.url]
