"""Program for the isolated engine Python, also usable by frozen desktop builds.

This adapter uses InstSci's public context-taking API. One visible context serves
the whole selection; no credentials/cookies are sent back to PaperMind.
"""
from app.ingestion.institutional_transfer import SOURCE as TRANSFER_SOURCE

SOURCE = TRANSFER_SOURCE + r'''
import json, sys, time
from pathlib import Path
from instsci.config import Config
from instsci.publisher_batch import PublisherBatchDownloader, PaperRecord
from instsci.publisher_profiles import infer_publisher_profile, ACS_PROFILE
from instsci.retry_policy import failure_category

folder = Path(sys.argv[1]).resolve()
request = json.loads((folder / 'request.json').read_text(encoding='utf-8'))
def emit(name, value):
    path = folder / name
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    for attempt in range(8):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(.02)

class Downloader(PublisherBatchDownloader):
    def _fetch_pdf_url(self, url, *, page=None):
        # A PDF viewer may expose no usable Download control after verification.
        body, final_url = fetch_in_browser(page, url)
        if body:
            return body, final_url
        if page is not None and urlsplit(page.url).path.lower().endswith('.pdf'):
            return None, url
        return super()._fetch_pdf_url(url, page=page)

    def _event(self, result, state, detail=''):
        super()._event(result, state, detail)
        if state in ('challenge_resolved', 'login_completed_after_timeout', 'institution_session_return_article'):
            phase = 'downloading'
        elif 'challenge' in state or 'captcha' in state:
            phase = 'waiting_verification'
        elif state in ('sso_start', 'login_state', 'institution_required', 'sso_required', 'reauth_required'):
            phase = 'waiting_login'
        elif state == 'desktop_alert':
            phase = getattr(self, '_phase', 'downloading')
        else:
            phase = 'downloading'
        self._phase = phase
        emit('progress.json', {'paper_id': current['paper_id'], 'phase': phase})

base = folder.parents[1]
cfg = Config(school=request['institution'], carsi_idp_name=request['institution'], carsi_enabled=True,
    institution_name_zh=request['institution'], institution_name_en=request.get('aliases', '').split(';')[0],
    chrome_profile_dir=str(base / 'profile'), cookie_path=str(base / 'cookies.json'),
    carsi_cookie_dir=str(base / 'carsi'), cache_dir=str(base / 'cache'), output_dir=str(folder))
cfg.ensure_dirs()
current = request['papers'][0]
launcher = Downloader(cfg, profile=ACS_PROFILE, institution_query=request['institution'])
context = launcher._launch_context()
captured = {}
def capture_download(file, target):
    path = folder / str(target['paper_id']) / 'browser-download.pdf'
    path.parent.mkdir(parents=True, exist_ok=True)
    file.save_as(str(path))
    item = {'doi': target.get('doi'), 'status': 'success', 'verified_match': True, 'pdf_path': str(path)}
    captured[target['paper_id']] = item
    emit(str(target['paper_id']) + '.json', item)
def watch(page):
    target = dict(current)
    page.on('download', lambda file: capture_download(file, target))
context.on('page', watch)
try:
    if request.get('mode') == 'manual':
        current = request['papers'][0]
        emit('progress.json', {'paper_id': current['paper_id'], 'phase': 'waiting_user'})
        page = context.new_page()
        try:
            page.goto(request.get('library_url') or 'https://ds.carsi.edu.cn/', wait_until='commit', timeout=60000)
        except Exception:
            pass  # A direct PDF download can abort navigation normally.
        deadline = time.monotonic() + 900
        next_check = 0
        while not captured and time.monotonic() < deadline and not (folder / 'cancel').exists():
            if time.monotonic() >= next_check:
                visible = context.pages[-1] if context.pages else page
                phase = 'waiting_verification' if launcher._is_challenge_page(visible) else 'waiting_user'
                emit('progress.json', {'paper_id': current['paper_id'], 'phase': phase})
                next_check = time.monotonic() + 5
            page.wait_for_timeout(500)
        emit(str(current['paper_id']) + '.json', captured.get(current['paper_id'], {'status': 'waiting_user'}))
        request['papers'] = []
    for current in request['papers']:
        if (folder / 'cancel').exists():
            break
        emit('progress.json', {'paper_id': current['paper_id'], 'phase': 'downloading'})
        profile = infer_publisher_profile(current.get('doi') or '')
        if not profile:
            emit(str(current['paper_id']) + '.json', {'paper_id': current['paper_id'], 'status': 'needs_manual'})
            continue
        downloader = Downloader(cfg, profile=profile, institution_query=request['institution'],
            institution_aliases=tuple(x.strip() for x in request.get('aliases', '').split(';') if x.strip()),
            login_timeout_sec=900, pdf_timeout_sec=90, include_supplementary=False)
        run = folder / str(current['paper_id'])
        downloader.run_records_with_context(context,
            [PaperRecord(doi=current['doi'], title=current['title'] or '')], run, retry_failed=False)
        item = json.loads((run / 'complete' / 'manifest.json').read_text(encoding='utf-8'))[0]
        item = captured.get(current['paper_id'], item)
        if item['status'] != 'success':
            summary = run / 'primary' / 'summary.json'
            if summary.is_file():
                raw = json.loads(summary.read_text(encoding='utf-8')).get('results', [{}])[0]
                item['reason'] = raw.get('reason', '')
            category = failure_category(item.get('reason', ''))
            verification = item.get('reason') in ('captcha_required', 'challenge_or_viewer_timeout')
            item['status'] = 'verification_required' if verification else {
                'human_action': 'waiting_user', 'access_denied': 'no_permission'}.get(category, 'needs_attention')
        emit(str(current['paper_id']) + '.json', item)
        if item['status'] in ('waiting_user', 'verification_required', 'needs_attention'):
            break
        time.sleep(3)
finally:
    context.close()
'''
