"""S1 导入外部 Agent Skills：GitHub / 本地文件夹 / zip。

导入后的技能与内置 Nature 技能走同一条发现-加载-读取路径；导出（GitHub）
在测试里用 respx 伪造，不访问真实网络。
"""
import json
import re
import time

import httpx
import pytest
import respx
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Skill
from app.skills import builtin, importer


@pytest.fixture
def imported_dir(tmp_path, monkeypatch):
    target = tmp_path / 'imported'
    monkeypatch.setenv('PAPERMIND_IMPORTED_SKILLS_DIR', str(target))
    return target


@pytest.fixture
def local_token(env):
    from app.security import local_token
    local_token.reset_token_cache()
    yield local_token
    local_token.reset_token_cache()


def auth(local_token):
    return {'X-Local-Token': local_token.get_or_create_token()}


def make_folder(tmp_path, name='skill-pack'):
    root = tmp_path / name
    (root / 'pdf-extract').mkdir(parents=True)
    (root / 'pdf-extract' / 'SKILL.md').write_text(
        '---\nname: pdf-extract\ndescription: 从 PDF 提取正文\nversion: 1.2.0\nlicense: MIT\n---\n'
        '第一步：解析版面。\n', encoding='utf-8')
    (root / 'pdf-extract' / 'references').mkdir()
    (root / 'pdf-extract' / 'references' / 'layout.md').write_text('版面规则原文', encoding='utf-8')
    (root / 'summarize').mkdir()
    (root / 'summarize' / 'SKILL.md').write_text(
        '没有 frontmatter 的摘要技能。\n\n第二段不用于描述。\n', encoding='utf-8')
    (root / 'LICENSE').write_text('MIT License\n\nCopyright (c) 2026\n', encoding='utf-8')
    return root


def make_zip(entries):
    import io
    import zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


def github_zip():
    return make_zip([
        ('skillpack-v1.2.0/README.md', '# repo readme'),
        ('skillpack-v1.2.0/LICENSE', 'MIT License\n'),
        ('skillpack-v1.2.0/skills/pdf-extract/SKILL.md',
         '---\nname: pdf-extract\ndescription: PDF 正文提取\n---\n正文流程。\n'),
        ('skillpack-v1.2.0/skills/pdf-extract/references/notes.md', '提取备注'),
        ('skillpack-v1.2.0/skills/other/readme.txt', 'no SKILL.md here'),
    ])


# --- 文件夹导入 -------------------------------------------------------------


def test_folder_import_discovers_skills_license_and_references(client, tmp_path, imported_dir, local_token):
    source = make_folder(tmp_path)
    response = client.post('/api/skill-imports/folder', json={'path': str(source)}, headers=auth(local_token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['id'] == 'import-skill-pack'
    assert body['source'] == str(source.resolve())
    assert body['revision'] == 'local'
    assert body['license'] == 'MIT License' and body['license_file'] == 'LICENSE'
    assert body['imported_at'] and body['bytes'] > 0 and body['file_count'] == 4
    assert body['skills_added'] == 2
    skills = {s['id']: s for s in body['skills']}
    assert set(skills) == {'import-skill-pack/pdf-extract', 'import-skill-pack/summarize'}
    assert skills['import-skill-pack/pdf-extract']['name'] == 'pdf-extract'
    assert skills['import-skill-pack/pdf-extract']['description'] == '从 PDF 提取正文'
    assert skills['import-skill-pack/pdf-extract']['license'] == 'MIT'
    assert skills['import-skill-pack/summarize']['description'] == '没有 frontmatter 的摘要技能。'
    assert skills['import-skill-pack/summarize']['license'] == 'MIT License'
    assert (imported_dir / 'import-skill-pack' / 'pdf-extract' / 'references' / 'layout.md').is_file()
    listed = client.get('/api/skill-imports', headers=auth(local_token)).json()
    assert [f['id'] for f in listed] == ['import-skill-pack']
    assert listed[0]['file_count'] == 4


def test_folder_import_rejects_invalid_path(client, tmp_path, imported_dir, local_token):
    missing = client.post('/api/skill-imports/folder', json={'path': str(tmp_path / 'nope')}, headers=auth(local_token))
    assert missing.status_code == 400 and '文件夹不存在' in missing.json()['detail']
    relative = client.post('/api/skill-imports/folder', json={'path': 'some/relative'}, headers=auth(local_token))
    assert relative.status_code == 400 and '绝对路径' in relative.json()['detail']
    empty_dir = tmp_path / 'empty'
    empty_dir.mkdir()
    no_skill = client.post('/api/skill-imports/folder', json={'path': str(empty_dir)}, headers=auth(local_token))
    assert no_skill.status_code == 400 and '未找到 SKILL.md' in no_skill.json()['detail']


def test_builtin_catalog_and_load_include_imported(client, tmp_path, imported_dir, local_token):
    source = make_folder(tmp_path)
    client.post('/api/skill-imports/folder', json={'path': str(source)}, headers=auth(local_token))
    catalog = builtin.public_catalog()
    family = next(f for f in catalog if f['id'] == 'import-skill-pack')
    assert family['imported'] is True and family['license'] == 'MIT License'
    assert {s['id'] for s in family['skills']} == {'import-skill-pack/pdf-extract', 'import-skill-pack/summarize'}
    assert family['file_count'] == 4 and 'files' not in family
    listed = json.loads(builtin.list_builtin_skills(None, query='import-skill-pack'))
    assert [s['id'] for s in listed] == ['import-skill-pack/pdf-extract', 'import-skill-pack/summarize']
    loaded = json.loads(builtin.load_builtin_skill(None, 'import-skill-pack/pdf-extract'))
    assert loaded['text'].startswith('[import-skill-pack/pdf-extract / SKILL.md]')
    assert '第一步：解析版面。' in loaded['text'] and builtin.ADAPTER in loaded['text']
    resource = json.loads(builtin.read_builtin_skill_resource(
        None, 'import-skill-pack/pdf-extract', 'references/layout.md'))
    assert resource['text'] == '版面规则原文'


def test_imported_resource_keeps_path_traversal_blocked(client, tmp_path, imported_dir, local_token):
    source = make_folder(tmp_path)
    client.post('/api/skill-imports/folder', json={'path': str(source)}, headers=auth(local_token))
    sid = 'import-skill-pack/pdf-extract'
    assert builtin.resource_path(sid, 'references/layout.md').is_file()
    with pytest.raises(LookupError):
        builtin.resource_path(sid, '../../../app/config.py')
    response = client.get('/api/builtin-skills/resource',
                          params={'skill_id': sid, 'path': '../../catalog.json'})
    assert response.status_code == 404


def test_reimport_folder_updates_in_place(client, tmp_path, imported_dir, local_token):
    source = make_folder(tmp_path)
    first = client.post('/api/skill-imports/folder', json={'path': str(source)}, headers=auth(local_token)).json()
    skill_md = source / 'pdf-extract' / 'SKILL.md'
    skill_md.write_text(skill_md.read_text(encoding='utf-8').replace('从 PDF 提取正文', '第二版说明'), encoding='utf-8')
    (source / 'pdf-extract' / 'references' / 'layout.md').unlink()
    second = client.post('/api/skill-imports/folder', json={'path': str(source)}, headers=auth(local_token)).json()
    assert second['id'] == first['id'] and second['skills_added'] == 0
    assert second['file_count'] == 3
    target = imported_dir / first['id'] / 'pdf-extract'
    assert not (target / 'references' / 'layout.md').exists()
    with Session(get_engine()) as session:
        row = session.exec(select(Skill).where(Skill.file_path == 'builtin://import-skill-pack/pdf-extract')).one()
        assert row.source == 'imported' and '第二版说明' in row.body


# --- zip 导入 ---------------------------------------------------------------


def test_zip_import_skips_zip_slip_and_dependency_dirs(client, tmp_path, imported_dir, local_token):
    payload = make_zip([
        ('pack/SKILL.md', '---\nname: pack\ndescription: zip 技能\n---\n正文'),
        ('pack/references/a.md', '内容'),
        ('pack/node_modules/dep.js', 'should not land'),
        ('pack/__pycache__/x.pyc', 'should not land'),
        ('../evil.txt', 'zip slip file'),
        ('/abs.txt', 'absolute entry'),
        ('pack/../../evil2.txt', 'zip slip nested'),
        ('pack/sub/evil3.txt/../../..', 'unresolvable'),
    ])
    response = client.post('/api/skill-imports/zip',
        files={'file': ('my-skills.zip', payload, 'application/zip')}, headers=auth(local_token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['id'] == 'import-my-skills' and body['source'] == 'zip:my-skills.zip'
    assert [s['id'] for s in body['skills']] == ['import-my-skills/pack']
    assert body['skills_added'] == 1
    assert body['file_count'] == 2
    copied = {p.relative_to(imported_dir / body['id']).as_posix()
              for p in (imported_dir / body['id']).rglob('*') if p.is_file()}
    assert copied == {'pack/SKILL.md', 'pack/references/a.md'}
    assert not (tmp_path / 'evil.txt').exists() and not (tmp_path / 'evil2.txt').exists()
    assert not (imported_dir.parent / 'evil.txt').exists()


def test_zip_import_rejects_invalid_archive(client, imported_dir, local_token):
    response = client.post('/api/skill-imports/zip',
        files={'file': ('bad.zip', b'not a zip', 'application/zip')}, headers=auth(local_token))
    assert response.status_code == 400 and 'zip' in response.json()['detail']


# --- GitHub 导入（respx 伪造） ---------------------------------------------


def github_blobs():
    """伪仓库内容：路径 -> 文本，形态对齐 codeload 归档剥离外层目录后的结果。"""
    return [
        ('README.md', '# repo readme'),
        ('LICENSE', 'MIT License\n'),
        ('skills/pdf-extract/SKILL.md',
         '---\nname: pdf-extract\ndescription: PDF 正文提取\n---\n正文流程。\n'),
        ('skills/pdf-extract/references/notes.md', '提取备注'),
        ('skills/pdf-extract/node_modules/dep.js', 'should not land'),
        ('skills/other/readme.txt', 'no SKILL.md here'),
    ]


def blob_entries(entries):
    return [{'path': path, 'type': 'blob', 'size': len(content.encode('utf-8'))}
            for path, content in entries]


def mock_github_api(owner, repo, ref, sha, entries):
    respx.get(f'https://api.github.com/repos/{owner}/{repo}/commits/{ref}').mock(
        return_value=httpx.Response(200, json={'sha': sha}))
    respx.get(f'https://api.github.com/repos/{owner}/{repo}/git/trees/{sha}',
              params={'recursive': '1'}).mock(
        return_value=httpx.Response(200, json={'truncated': False, 'tree': blob_entries(entries)}))


def mock_raw(owner, repo, sha, entries):
    for path, content in entries:
        respx.get(f'https://raw.githubusercontent.com/{owner}/{repo}/{sha}/' + path).mock(
            return_value=httpx.Response(200, content=content.encode('utf-8')))


def request_urls():
    return [str(call.request.url) for call in respx.calls]


def test_api_headers_add_token_for_api_host_only(monkeypatch):
    """GITHUB_TOKEN/GH_TOKEN 只随 api.github.com 请求发出，raw/codeload 不携带。"""
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    monkeypatch.delenv('GH_TOKEN', raising=False)
    api_url = 'https://api.github.com/repos/acme/skillpack'
    assert 'Authorization' not in importer._api_headers(api_url)
    monkeypatch.setenv('GITHUB_TOKEN', 'tok-first')
    assert importer._api_headers(api_url)['Authorization'] == 'Bearer tok-first'
    monkeypatch.delenv('GITHUB_TOKEN')
    monkeypatch.setenv('GH_TOKEN', 'tok-second')
    assert importer._api_headers(api_url)['Authorization'] == 'Bearer tok-second'
    assert 'Authorization' not in importer._api_headers('https://raw.githubusercontent.com/acme/skillpack/main/a.md')
    assert 'Authorization' not in importer._api_headers('https://codeload.github.com/acme/skillpack/zip/main')


@respx.mock
def test_github_subpath_import_uses_tree_and_raw_without_codeload(client, imported_dir, local_token):
    entries = github_blobs()
    sha = 'a' * 40
    mock_github_api('acme', 'skillpack', 'v1.2.0', sha, entries)
    mock_raw('acme', 'skillpack', sha, [item for item in entries if item[0] != 'README.md' and 'node_modules' not in item[0]])
    response = client.post('/api/skill-imports/github',
        json={'url': 'https://github.com/acme/skillpack/tree/v1.2.0/skills'}, headers=auth(local_token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['id'] == 'import-skillpack'
    assert body['source'] == 'https://github.com/acme/skillpack/tree/v1.2.0/skills'
    assert body['revision'] == sha  # tree 对应的 commit sha
    assert [s['id'] for s in body['skills']] == ['import-skillpack/pdf-extract']
    assert body['file_count'] == 4 and body['license'] == 'MIT License'
    target = imported_dir / 'import-skillpack'
    assert (target / 'pdf-extract' / 'SKILL.md').is_file()
    assert (target / 'pdf-extract' / 'references' / 'notes.md').read_text(encoding='utf-8') == '提取备注'
    assert not (target / 'README.md').exists()  # 子路径之外的文件不导入
    assert not (target / 'pdf-extract' / 'node_modules').exists()  # SKIP_DIRS 内的 blob 不下载
    assert (target / 'LICENSE').is_file()  # 仓库根许可证随子路径导入
    urls = request_urls()
    assert not any('codeload.github.com' in url for url in urls)  # 子目录导入不碰整仓归档
    api_calls = [call for call in respx.calls if 'api.github.com' in str(call.request.url)]
    assert api_calls, urls
    assert all(call.request.headers.get('user-agent') == 'PaperMind' for call in api_calls)
    assert all(call.request.headers.get('accept') == 'application/vnd.github+json' for call in api_calls)


@pytest.mark.parametrize('env_name', ['GITHUB_TOKEN', 'GH_TOKEN'])
@respx.mock
def test_github_token_is_sent_to_api_requests_only(client, imported_dir, local_token, monkeypatch, env_name):
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    monkeypatch.delenv('GH_TOKEN', raising=False)
    monkeypatch.setenv(env_name, 'ghp-local-secret')
    entries = github_blobs()
    sha = 'a' * 40
    mock_github_api('acme', 'skillpack', 'v1.2.0', sha, entries)
    mock_raw('acme', 'skillpack', sha, [item for item in entries
                                        if item[0] != 'README.md' and 'node_modules' not in item[0]])
    response = client.post('/api/skill-imports/github',
        json={'url': 'https://github.com/acme/skillpack/tree/v1.2.0/skills'}, headers=auth(local_token))
    assert response.status_code == 200, response.text
    api_calls = [call for call in respx.calls if 'api.github.com' in str(call.request.url)]
    raw_calls = [call for call in respx.calls if 'raw.githubusercontent.com' in str(call.request.url)]
    assert api_calls and raw_calls
    assert all(call.request.headers.get('authorization') == 'Bearer ghp-local-secret' for call in api_calls)
    assert all('authorization' not in call.request.headers for call in raw_calls)
    assert 'ghp-local-secret' not in response.text  # 令牌不进错误信息/响应


@respx.mock
def test_github_subpath_import_falls_back_to_zip_when_tree_truncated(client, imported_dir, local_token):
    sha = 'a' * 40
    respx.get('https://api.github.com/repos/acme/skillpack/commits/v1.2.0').mock(
        return_value=httpx.Response(200, json={'sha': sha}))
    respx.get('https://api.github.com/repos/acme/skillpack/git/trees/' + sha,
              params={'recursive': '1'}).mock(
        return_value=httpx.Response(200, json={'truncated': True, 'tree': []}))
    respx.get('https://codeload.github.com/acme/skillpack/zip/v1.2.0').mock(
        return_value=httpx.Response(200, content=github_zip()))
    response = client.post('/api/skill-imports/github',
        json={'url': 'https://github.com/acme/skillpack/tree/v1.2.0/skills'}, headers=auth(local_token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['revision'] == sha
    assert [s['id'] for s in body['skills']] == ['import-skillpack/pdf-extract']
    assert body['file_count'] == 4
    urls = request_urls()
    assert any('codeload.github.com' in url for url in urls)
    assert not any('raw.githubusercontent.com' in url for url in urls)


@pytest.mark.parametrize('status', [403, 429])
@respx.mock
def test_github_api_limited_falls_back_to_zip_with_ref_revision(client, imported_dir, local_token,
                                                                monkeypatch, status):
    """API 受限时退回整仓归档解出子路径，revision 用 ref；令牌不发往 codeload。"""
    monkeypatch.setenv('GITHUB_TOKEN', 'ghp-local-secret')
    respx.get('https://api.github.com/repos/acme/skillpack/commits/v1.2.0').mock(
        return_value=httpx.Response(status, headers={'X-RateLimit-Reset': str(int(time.time()) + 300)}))
    respx.get('https://codeload.github.com/acme/skillpack/zip/v1.2.0').mock(
        return_value=httpx.Response(200, content=github_zip()))
    response = client.post('/api/skill-imports/github',
        json={'url': 'https://github.com/acme/skillpack/tree/v1.2.0/skills'}, headers=auth(local_token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['id'] == 'import-skillpack' and body['revision'] == 'v1.2.0'
    assert [s['id'] for s in body['skills']] == ['import-skillpack/pdf-extract']
    assert body['file_count'] == 4 and body['license'] == 'MIT License'
    urls = request_urls()
    assert any('codeload.github.com' in url for url in urls)
    assert not any('raw.githubusercontent.com' in url for url in urls)
    api_calls = [call for call in respx.calls if 'api.github.com' in str(call.request.url)]
    codeload_calls = [call for call in respx.calls if 'codeload.github.com' in str(call.request.url)]
    assert all(call.request.headers.get('authorization') == 'Bearer ghp-local-secret' for call in api_calls)
    assert codeload_calls and all('authorization' not in call.request.headers for call in codeload_calls)


@respx.mock
def test_github_api_network_error_falls_back_to_zip(client, imported_dir, local_token):
    respx.get('https://api.github.com/repos/acme/skillpack/commits/main').mock(
        side_effect=httpx.ConnectError('api.github.com unreachable'))
    respx.get('https://codeload.github.com/acme/skillpack/zip/main').mock(
        return_value=httpx.Response(200, content=github_zip()))
    response = client.post('/api/skill-imports/github',
        json={'url': 'https://github.com/acme/skillpack/tree/main/skills'}, headers=auth(local_token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['revision'] == 'main'
    assert [s['id'] for s in body['skills']] == ['import-skillpack/pdf-extract']


@respx.mock
def test_github_api_error_and_zip_over_limit_is_502_with_both_reasons(client, imported_dir,
                                                                      local_token, monkeypatch):
    """API 非受限失败且归档超限：两类原因合并后仍按 DownloadError 映射 502。"""
    monkeypatch.setattr(importer, 'MAX_BYTES', 32)
    respx.get('https://api.github.com/repos/acme/skillpack/commits/main').mock(
        return_value=httpx.Response(500))
    respx.get('https://codeload.github.com/acme/skillpack/zip/main').mock(
        return_value=httpx.Response(200, content=b'x' * 64))
    response = client.post('/api/skill-imports/github',
        json={'url': 'https://github.com/acme/skillpack/tree/main/skills'}, headers=auth(local_token))
    assert response.status_code == 502
    detail = response.json()['detail']
    assert 'HTTP 500' in detail and '100MB' in detail


@respx.mock
def test_github_subpath_missing_is_400(client, imported_dir, local_token):
    entries = github_blobs()
    mock_github_api('acme', 'skillpack', 'main', 'a' * 40, entries)
    response = client.post('/api/skill-imports/github',
        json={'url': 'https://github.com/acme/skillpack/tree/main/skills/nonexistent'},
        headers=auth(local_token))
    assert response.status_code == 400
    assert response.json()['detail'] == '仓库中找不到该路径：skills/nonexistent'
    urls = request_urls()
    assert not any('raw.githubusercontent.com' in url for url in urls)
    assert not any('codeload.github.com' in url for url in urls)


@respx.mock
def test_github_subpath_tree_size_precheck_skips_downloads(client, imported_dir, local_token, monkeypatch):
    monkeypatch.setattr(importer, 'MAX_BYTES', 16)
    entries = [('skills/huge/SKILL.md', 'x' * 100)]
    mock_github_api('acme', 'skillpack', 'main', 'a' * 40, entries)
    response = client.post('/api/skill-imports/github',
        json={'url': 'https://github.com/acme/skillpack/tree/main/skills/huge'},
        headers=auth(local_token))
    assert response.status_code == 400 and '100MB' in response.json()['detail']
    assert not any('raw.githubusercontent.com' in url for url in request_urls())


@pytest.mark.parametrize('status', [403, 429])
@respx.mock
def test_github_api_rate_limit_is_502(client, imported_dir, local_token, status):
    """受限且归档退路也失败（HTTP 错误）时报 502 并给出办法。"""
    respx.get('https://api.github.com/repos/acme/skillpack/commits/main').mock(
        return_value=httpx.Response(status, headers={'X-RateLimit-Reset': str(int(time.time()) + 300)}))
    respx.get('https://codeload.github.com/acme/skillpack/zip/main').mock(
        return_value=httpx.Response(404))
    response = client.post('/api/skill-imports/github',
        json={'url': 'https://github.com/acme/skillpack/tree/main/skills/pdf-extract'},
        headers=auth(local_token))
    assert response.status_code == 502
    detail = response.json()['detail']
    assert 'GitHub API 访问受限' in detail
    assert '仓库归档' in detail and 'GITHUB_TOKEN' in detail and '文件夹导入' in detail
    assert any('codeload.github.com' in url for url in request_urls())  # 先尝试了归档退路


@pytest.mark.parametrize('reset_seconds', [None, 600])
@respx.mock
def test_github_api_limited_and_zip_over_limit_reports_remedies(client, imported_dir, local_token,
                                                                monkeypatch, reset_seconds):
    monkeypatch.setattr(importer, 'MAX_BYTES', 32)
    headers = {'X-RateLimit-Reset': str(int(time.time()) + reset_seconds)} if reset_seconds else {}
    respx.get('https://api.github.com/repos/acme/skillpack/commits/main').mock(
        return_value=httpx.Response(403, headers=headers))
    respx.get('https://codeload.github.com/acme/skillpack/zip/main').mock(
        return_value=httpx.Response(200, content=b'x' * 64))
    response = client.post('/api/skill-imports/github',
        json={'url': 'https://github.com/acme/skillpack/tree/main/skills/pdf-extract'},
        headers=auth(local_token))
    assert response.status_code == 502
    detail = response.json()['detail']
    assert 'GitHub API 访问受限' in detail and '仓库归档超过 100MB' in detail
    assert 'GITHUB_TOKEN' in detail and '文件夹导入' in detail
    if reset_seconds:
        match = re.search(r'约 (\d+) 分钟后恢复', detail)
        assert match and 9 <= int(match.group(1)) <= 11  # 600 秒 -> 约 10 分钟
    else:
        assert '分钟后恢复' not in detail  # 无 X-RateLimit-Reset 时省略这句


@respx.mock
def test_commit_tree_uses_default_branch_when_ref_missing(imported_dir):
    sha = 'b' * 40
    respx.get('https://api.github.com/repos/acme/skillpack').mock(
        return_value=httpx.Response(200, json={'default_branch': 'trunk'}))
    respx.get('https://api.github.com/repos/acme/skillpack/commits/trunk').mock(
        return_value=httpx.Response(200, json={'sha': sha}))
    respx.get('https://api.github.com/repos/acme/skillpack/git/trees/' + sha,
              params={'recursive': '1'}).mock(
        return_value=httpx.Response(200, json={'truncated': False,
                                               'tree': [{'path': 'SKILL.md', 'type': 'blob', 'size': 3}]}))
    revision, commit_sha, tree = importer._commit_tree('acme', 'skillpack', None)
    assert revision == commit_sha == sha
    assert [entry['path'] for entry in tree['tree']] == ['SKILL.md']


@respx.mock
def test_github_repo_archive_over_limit_hints_subpath(client, imported_dir, local_token, monkeypatch):
    monkeypatch.setattr(importer, 'MAX_BYTES', 32)
    respx.get('https://codeload.github.com/acme/skillpack/zip/HEAD').mock(
        return_value=httpx.Response(200, content=b'x' * 64))
    respx.get('https://api.github.com/repos/acme/skillpack/commits/HEAD').mock(
        return_value=httpx.Response(200, json={'sha': 'c' * 40}))
    response = client.post('/api/skill-imports/github',
        json={'url': 'https://github.com/acme/skillpack'}, headers=auth(local_token))
    assert response.status_code == 400
    detail = response.json()['detail']
    assert '请改用' in detail and '/tree/' in detail


@respx.mock
def test_github_import_falls_back_to_ref_when_commit_lookup_fails(client, imported_dir, local_token):
    respx.get('https://codeload.github.com/acme/headless/zip/HEAD').mock(
        return_value=httpx.Response(200, content=make_zip([
            ('headless-main/SKILL.md', '---\nname: headless\n---\n正文')])))
    respx.get('https://api.github.com/repos/acme/headless/commits/HEAD').mock(return_value=httpx.Response(404))
    response = client.post('/api/skill-imports/github',
        json={'url': 'https://github.com/acme/headless'}, headers=auth(local_token))
    assert response.status_code == 200, response.text
    assert response.json()['revision'] == 'HEAD'


@respx.mock
def test_github_download_failure_is_502(client, imported_dir, local_token):
    respx.get('https://codeload.github.com/acme/broken/zip/HEAD').mock(return_value=httpx.Response(500))
    respx.get('https://api.github.com/repos/acme/broken/commits/HEAD').mock(return_value=httpx.Response(500))
    response = client.post('/api/skill-imports/github',
        json={'url': 'https://github.com/acme/broken'}, headers=auth(local_token))
    assert response.status_code == 502 and 'GitHub 下载失败' in response.json()['detail']


def test_github_url_validation_400(client, imported_dir, local_token):
    for url in ['https://gitlab.com/acme/skillpack', 'https://github.com/acme', 'not a url',
                'https://github.com/acme/skillpack/blob/main/x']:
        response = client.post('/api/skill-imports/github', json={'url': url}, headers=auth(local_token))
        assert response.status_code == 400, url
        assert 'GitHub 地址无效' in response.json()['detail']


# --- 对话路径与删除 ---------------------------------------------------------


def test_discovery_and_chat_prompt_skip_deleted_import(client, tmp_path, imported_dir, local_token):
    source = make_folder(tmp_path)
    client.post('/api/skill-imports/folder', json={'path': str(source)}, headers=auth(local_token))
    with Session(get_engine()) as session:
        directory = builtin.discovery_prompt(session)
        assert 'import-skill-pack/pdf-extract' in directory
        row = session.exec(select(Skill).where(Skill.file_path == 'builtin://import-skill-pack/pdf-extract')).one()
        assert row.source == 'imported'
        assert '第一步：解析版面。' in builtin.chat_prompt(row)
        importer.remove('import-skill-pack')  # 目录已删除、数据库行仍在
        assert 'import-skill-pack/pdf-extract' not in builtin.discovery_prompt(session)
        assert builtin.chat_prompt(row)  # 返回存量正文，不抛异常
        assert builtin.sync(session) == 0
        assert session.exec(select(Skill).where(Skill.source == 'imported')).all() == []


def test_delete_removes_files_catalog_and_rows(client, tmp_path, imported_dir, local_token):
    source = make_folder(tmp_path)
    client.post('/api/skill-imports/folder', json={'path': str(source)}, headers=auth(local_token))
    assert (imported_dir / 'import-skill-pack').is_dir()
    assert client.delete('/api/skill-imports/import-skill-pack', headers=auth(local_token)).status_code == 204
    assert not (imported_dir / 'import-skill-pack').exists()
    assert client.get('/api/skill-imports', headers=auth(local_token)).json() == []
    with Session(get_engine()) as session:
        assert session.exec(select(Skill).where(Skill.source == 'imported')).all() == []
        assert 'import-skill-pack' not in builtin.discovery_prompt(session)
    assert client.delete('/api/skill-imports/import-skill-pack', headers=auth(local_token)).status_code == 404


def test_imports_require_local_token(client, imported_dir):
    assert client.get('/api/skill-imports').status_code == 403
    assert client.post('/api/skill-imports/folder', json={'path': 'C:/tmp'}).status_code == 403
    assert client.delete('/api/skill-imports/import-x').status_code == 403
    assert client.post('/api/skill-imports/github', json={'url': 'https://github.com/a/b'}).status_code == 403


@respx.mock
def test_github_single_skill_subpath_is_named_after_its_directory(client, imported_dir, local_token):
    entries = github_blobs()
    sha = 'a' * 40
    mock_github_api('acme', 'skillpack', 'v1.2.0', sha, entries)
    mock_raw('acme', 'skillpack', sha, [item for item in entries if item[0] != 'README.md' and 'node_modules' not in item[0]])
    response = client.post('/api/skill-imports/github',
        json={'url': 'https://github.com/acme/skillpack/tree/v1.2.0/skills/pdf-extract'}, headers=auth(local_token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['id'] == 'import-pdf-extract' and body['name'] == 'pdf-extract'
    assert [s['id'] for s in body['skills']] == ['import-pdf-extract/pdf-extract']
