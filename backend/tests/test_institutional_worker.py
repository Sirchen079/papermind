import json
import sys
from types import ModuleType, SimpleNamespace

from app.ingestion.institutional_worker import SOURCE


def test_worker_reuses_one_visible_context_and_never_downloads_si(tmp_path, monkeypatch):
    request = {'institution': 'Example', 'aliases': 'Example University;示例大学', 'papers': [
        {'paper_id': 1, 'doi': '10.1000/a', 'title': 'A'},
        {'paper_id': 2, 'doi': '10.1000/b', 'title': 'B'}]}
    (tmp_path / 'request.json').write_text(json.dumps(request))
    handlers = {}
    context = SimpleNamespace(close=lambda: calls.append('closed'), on=lambda name, callback: handlers.update({name:callback}))
    calls = []
    class Config:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
        def ensure_dirs(self):
            pass
    class Downloader:
        def __init__(self, cfg, **kw):
            assert not kw.get('include_supplementary', False)
        def _launch_context(self):
            calls.append('launched')
            return context
        def _event(self, *args):
            pass
        def run_records_with_context(self, ctx, records, run, **kw):
            assert ctx is context and kw['retry_failed'] is False
            self._event(None, 'challenge_manual_wait')
            assert json.loads((tmp_path / 'progress.json').read_text())['phase'] == 'waiting_verification'
            self._event(None, 'desktop_alert')
            assert json.loads((tmp_path / 'progress.json').read_text())['phase'] == 'waiting_verification'
            self._event(None, 'challenge_resolved')
            assert json.loads((tmp_path / 'progress.json').read_text())['phase'] == 'downloading'
            self._event(None, 'sso_start')
            assert json.loads((tmp_path / 'progress.json').read_text())['phase'] == 'waiting_login'
            self._event(None, 'login_completed_after_timeout')
            assert json.loads((tmp_path / 'progress.json').read_text())['phase'] == 'downloading'
            calls.append(records[0].doi)
            (run / 'complete').mkdir(parents=True)
            (run / 'complete' / 'manifest.json').write_text('[{"status":"success"}]')
    modules = {'instsci': {}, 'instsci.config': {'Config': Config},
        'instsci.publisher_batch': {'PublisherBatchDownloader': Downloader, 'PaperRecord': SimpleNamespace},
        'instsci.publisher_profiles': {'ACS_PROFILE': 'acs', 'infer_publisher_profile': lambda _: 'profile'},
        'instsci.retry_policy': {'failure_category': lambda _: 'human_action'}}
    for name, attrs in modules.items():
        module = ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(sys, 'argv', ['worker', str(tmp_path)])
    monkeypatch.setattr('time.sleep', lambda _: None)
    # Windows readers can briefly prevent replacement of the progress file.
    from pathlib import Path
    original_replace, blocked = Path.replace, []
    def replace(path, target):
        if not blocked:
            blocked.append(True)
            raise PermissionError('reader has a handle open')
        return original_replace(path, target)
    monkeypatch.setattr(Path, 'replace', replace)
    namespace = {}
    exec(compile(SOURCE, 'institutional-worker', 'exec'), namespace)
    assert calls == ['launched', '10.1000/a', '10.1000/b', 'closed']
    assert (tmp_path / '1.json').is_file() and (tmp_path / '2.json').is_file()
    assert 'page' in handlers
    downloads = {}
    handlers['page'](SimpleNamespace(on=lambda name, callback: downloads.update({name:callback})))
    # The page retains its paper identity even if the batch moves on.
    namespace['current'] = request['papers'][0]
    downloads['download'](SimpleNamespace(save_as=lambda p: __import__('pathlib').Path(p).write_bytes(b'%PDF-test')))
    assert json.loads((tmp_path / '2.json').read_text())['pdf_path'].endswith('browser-download.pdf')
