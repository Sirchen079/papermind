"""导入外部 Agent Skills 技能包（GitHub 仓库 / 本地文件夹 / zip）。

导入后的技能与内置 Nature 技能走完全相同的路径：catalog() 合并目录 ->
load_builtin_skill -> read_builtin_skill_resource。文件复制到应用级导入根目录，
只读取不执行——导入包里的脚本永远不会被运行。导入先写临时目录再原子替换，
失败不留半截内容。
"""
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import urlparse
import uuid
import zipfile

import httpx
import yaml

from app import paths

MAX_BYTES = 100 * 1024 * 1024
MAX_FILES = 5000
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '__MACOSX'}
LICENSE_NAMES = {'license', 'license.md', 'license.txt', 'copying'}
# Windows 保留名：写入会失败，按不可写名称跳过。
_RESERVED = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{prefix}{i}' for prefix in ('COM', 'LPT') for i in range(1, 10)}
CATALOG_FORMAT = 1
_CHUNK = 1 << 16
_FRONT = re.compile(r'^\s*---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z', re.S)


class DownloadError(Exception):
    """GitHub 下载失败（网络错误或非 200）；接口层映射为 502。"""


_cache = None  # ((catalog 路径, mtime), 目录内容)


def root() -> Path:
    return paths.imported_skills_dir()


def catalog() -> dict:
    """导入目录的 catalog.json，按路径与 mtime 缓存；导入/删除后立即失效。"""
    global _cache
    path = root() / 'catalog.json'
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {'format': CATALOG_FORMAT, 'families': []}
    if _cache is not None and _cache[0] == (str(path), mtime):
        return _cache[1]
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or not isinstance(data.get('families'), list):
        data = {'format': CATALOG_FORMAT, 'families': []}
    _cache = ((str(path), mtime), data)
    return data


def parse_github_url(url: str):
    """https://github.com/<owner>/<repo>[/tree/<ref>[/<子路径>]] -> (owner, repo, ref, subpath)。"""
    parsed = urlparse((url or '').strip())
    if parsed.scheme not in ('http', 'https') or parsed.netloc.lower() not in ('github.com', 'www.github.com'):
        raise ValueError('GitHub 地址无效：请提供 https://github.com/<owner>/<repo> 形式的地址')
    segments = [s for s in parsed.path.split('/') if s]
    if len(segments) < 2:
        raise ValueError('GitHub 地址无效：缺少仓库名')
    owner, repo = segments[0], segments[1]
    if repo.endswith('.git'):
        repo = repo[:-4]
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', owner) or not re.fullmatch(r'[A-Za-z0-9_.-]+', repo):
        raise ValueError('GitHub 地址无效：owner 或仓库名含有不支持的字符')
    ref = subpath = None
    if len(segments) > 2:
        if segments[2] != 'tree' or len(segments) < 4:
            raise ValueError('GitHub 地址无效：仅支持 /tree/<ref>/<子路径> 形式')
        ref = segments[3]
        subpath = '/'.join(segments[4:]) or None
    return owner, repo, ref, subpath


def import_github(url: str) -> dict:
    owner, repo, ref, subpath = parse_github_url(url)
    data = _download(f'https://codeload.github.com/{owner}/{repo}/zip/{ref or "HEAD"}')
    revision = _resolve_commit(owner, repo, ref)
    source = f'https://github.com/{owner}/{repo}'
    if ref:
        source += '/tree/' + ref
    if subpath:
        source += '/' + subpath
    staging = _new_staging()
    try:
        # codeload 归档外层目录名随 ref 变化，导入前剥离，技能 id 才能跨版本稳定。
        _extract_zip(data, staging, subpath=subpath, strip_top=True, always_strip=True)
        family = _build_family(staging, source=source,
            source_key=f'github:{owner.lower()}/{repo.lower()}/{subpath or ""}',
            revision=revision, name=repo, base_slug=_slug(repo))
        _commit(family, staging)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return family


def import_folder(path: str) -> dict:
    source = Path(path or '')
    if not source.is_absolute():
        raise ValueError('请提供文件夹的绝对路径')
    source = source.resolve()
    if not source.is_dir():
        raise ValueError('文件夹不存在：' + str(path))
    staging = _new_staging()
    try:
        try:
            _copy_tree(source, staging)
        except OSError as exc:
            raise ValueError('无法读取文件夹内容：' + type(exc).__name__) from exc
        family = _build_family(staging, source=str(source),
            source_key='folder:' + os.path.normcase(str(source)),
            revision='local', name=source.name, base_slug=_slug(source.name))
        _commit(family, staging)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return family


def import_zip(data: bytes, filename: str = 'upload.zip') -> dict:
    name = Path(filename or 'upload.zip').name or 'upload.zip'
    if not data:
        raise ValueError('zip 文件为空')
    staging = _new_staging()
    try:
        _extract_zip(data, staging, strip_top=True)
        stem = Path(name).stem or name
        family = _build_family(staging, source='zip:' + name,
            source_key='zip:' + name.lower(), revision='zip',
            name=stem, base_slug=_slug(stem))
        _commit(family, staging)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return family


def remove(family_id: str) -> None:
    """删除一个导入 family 的文件与目录条目；不存在时抛 LookupError。"""
    current = catalog()
    if family_id not in {f['id'] for f in current['families']}:
        raise LookupError('导入技能不存在')
    dest = root() / family_id
    trash = None
    if dest.exists():
        trash = root() / ('.trash-' + uuid.uuid4().hex)
        dest.rename(trash)
    try:
        _write_catalog({'format': CATALOG_FORMAT,
                        'families': [f for f in current['families'] if f['id'] != family_id]})
    except BaseException:
        if trash is not None and trash.exists():
            trash.rename(dest)
        raise
    if trash is not None:
        shutil.rmtree(trash, ignore_errors=True)


# --- 准备工作（下载、复制、解压、发现、落盘） -------------------------------


def _download(url: str) -> bytes:
    chunks = []
    total = 0
    try:
        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60.0, read=300.0)) as client:
            with client.stream('GET', url) as response:
                if response.status_code != 200:
                    raise DownloadError(f'GitHub 下载失败：HTTP {response.status_code}')
                for chunk in response.iter_bytes(_CHUNK):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ValueError('下载内容超过 100MB 上限，已中止')
                    chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise DownloadError('GitHub 下载失败：无法连接 codeload.github.com，请检查网络后重试') from exc
    return b''.join(chunks)


def _resolve_commit(owner: str, repo: str, ref: str = None) -> str:
    """尽力解析 commit sha 作为 revision；失败时退回 ref（默认分支用 HEAD）。"""
    try:
        response = httpx.get(f'https://api.github.com/repos/{owner}/{repo}/commits/{ref or "HEAD"}',
            headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'PaperMind'},
            follow_redirects=True, timeout=10)
        if response.status_code == 200:
            sha = response.json().get('sha')
            if sha:
                return sha
    except (httpx.HTTPError, ValueError):
        pass
    return ref or 'HEAD'


def _new_staging() -> Path:
    base = root()
    base.mkdir(parents=True, exist_ok=True)
    staging = base / ('.staging-' + uuid.uuid4().hex)
    staging.mkdir()
    return staging


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    checker = getattr(path, 'is_junction', None)
    return bool(checker and checker())


def _copy_tree(source: Path, staging: Path) -> None:
    count = 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        directory = Path(dirpath)
        dirnames[:] = sorted(name for name in dirnames
                             if name not in SKIP_DIRS and not _is_link(directory / name))
        out_dir = staging / directory.relative_to(source)
        for name in sorted(filenames):
            item = directory / name
            if _is_link(item) or not item.is_file():
                continue
            count += 1
            total += item.stat().st_size
            if count > MAX_FILES:
                raise ValueError('文件数超过 5000 上限')
            if total > MAX_BYTES:
                raise ValueError('导入内容超过 100MB 大小限制')
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, out_dir / name)


def _safe_rel(name: str):
    """zip 条目名规范化；zip-slip（.. / 绝对路径）与不可写名称返回 None 跳过。"""
    name = name.replace('\\', '/')
    if name.startswith('/') or re.match(r'^[A-Za-z]:', name):
        return None
    parts = []
    for part in name.split('/'):
        if part in ('', '.'):
            continue
        part = part.rstrip('. ')
        if part in ('', '..') or ':' in part or any(char in '<>"|?*' for char in part):
            return None
        if part.split('.', 1)[0].upper() in _RESERVED:
            return None
        parts.append(part)
    if not parts or any(part in SKIP_DIRS for part in parts):
        return None
    return '/'.join(parts)


def _common_top(names):
    """所有条目共享同一个顶层目录时返回 '目录/'（GitHub 归档的外层包装）。"""
    if not names:
        return ''
    tops = {name.split('/', 1)[0] for name in names}
    if len(tops) != 1:
        return ''
    top = next(iter(tops))
    if any(name == top for name in names):
        return ''
    return top + '/'


def _extract_zip(data: bytes, staging: Path, subpath: str = None, strip_top: bool = False,
                 always_strip: bool = False) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError('不是有效的 zip 文件') from exc
    with archive:
        entries = []
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = _safe_rel(info.filename)
            if name:
                entries.append((name, info))
        prefix = _common_top([name for name, _ in entries])
        wrapper = prefix.lower()
        wrapper_is_skill = bool(prefix) and any(name.lower() == wrapper + 'skill.md' for name, _ in entries)
        if subpath:
            target = prefix + subpath.strip('/') + '/'
            selected = [(name[len(target):], info) for name, info in entries if name.startswith(target)]
            if not selected:
                raise ValueError('仓库中找不到该路径：' + subpath)
            seen = {name for name, _ in selected}
            for name, info in entries:  # 仓库根许可证随子路径导入，便于记录来源协议。
                rel = name[len(prefix):] if prefix and name.startswith(prefix) else name
                if rel.lower() in LICENSE_NAMES and rel not in seen:
                    selected.append((rel, info))
            entries = selected
        elif strip_top and prefix and (always_strip or not wrapper_is_skill):
            entries = [(name[len(prefix):], info) for name, info in entries]
        if len(entries) > MAX_FILES:
            raise ValueError('文件数超过 5000 上限')
        if sum(info.file_size for _, info in entries) > MAX_BYTES:
            raise ValueError('导入内容超过 100MB 大小限制')
        written = 0
        try:
            for name, info in entries:
                path = staging / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, path.open('wb') as target:
                    while True:
                        chunk = source.read(_CHUNK)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > MAX_BYTES:
                            raise ValueError('导入内容超过 100MB 大小限制')
                        target.write(chunk)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
            raise ValueError('zip 文件无法解压：可能已加密或已损坏') from exc


def _parse_frontmatter(text: str):
    match = _FRONT.match(text)
    if not match:
        return {}, text
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        data = {}  # 解析失败按无 frontmatter 处理，正文照常可用
    return (data if isinstance(data, dict) else {}), (match.group(2) or '')


def _first_paragraph(body: str) -> str:
    for block in re.split(r'\n\s*\n', (body or '').strip()):
        text = ' '.join(line.strip() for line in block.splitlines() if line.strip())
        if text:
            return text
    return ''


def _license_str(value):
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ('name', 'id'):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
    return None


def _version_str(front: dict) -> str:
    value = front.get('version')
    if value is None:
        metadata = front.get('metadata')
        value = metadata.get('version') if isinstance(metadata, dict) else None
    if value is None:
        return '0'
    return value if isinstance(value, str) else str(value)


def _root_license(staging: Path):
    """根目录 LICENSE/LICENSE.md/LICENSE.txt/COPYING 的首个非空行。"""
    wanted = {'license', 'license.md', 'license.txt', 'copying'}
    for path in sorted(staging.iterdir()):
        if not path.is_file() or path.name.lower() not in wanted:
            continue
        for line in path.read_text(encoding='utf-8-sig', errors='replace').splitlines():
            if line.strip():
                return path.name, line.strip()
        return path.name, None
    return None, None


def _inventory(staging: Path):
    files = {}
    total = 0
    for path in sorted(staging.rglob('*')):
        if not path.is_file():
            continue
        payload = path.read_bytes()
        files[path.relative_to(staging).as_posix()] = hashlib.sha256(payload).hexdigest()
        total += len(payload)
    return files, total


def _slug(text: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')
    return slug[:60].strip('-') or 'skills'


def _family_id_for(source_key: str, base: str) -> str:
    families = catalog()['families']
    for family in families:
        if family.get('source_key') == source_key:
            return family['id']  # 同来源再次导入：原地更新，保留 family_id
    from app.skills.builtin import catalog as builtin_catalog
    taken = {f['id'] for f in families} | {f['id'] for f in builtin_catalog()['families']}
    candidate, counter = base, 2
    while candidate in taken:
        candidate, counter = f'{base}-{counter}', counter + 1
    return candidate


def _snapshot(files: dict) -> str:
    digest = hashlib.sha256()
    for path, sha in sorted(files.items()):
        digest.update(f'{path}\0{sha}\n'.encode())
    return digest.hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _build_family(staging: Path, *, source: str, source_key: str, revision: str,
                  name: str, base_slug: str) -> dict:
    discovered = []
    for dirpath, dirnames, filenames in os.walk(staging):
        dirnames.sort()
        skill_file = next((entry for entry in filenames if entry.lower() == 'skill.md'), None)
        if skill_file is None:
            continue
        directory = Path(dirpath)
        text = (directory / skill_file).read_text(encoding='utf-8-sig', errors='replace')
        front, body = _parse_frontmatter(text)
        discovered.append((directory.relative_to(staging).as_posix(), directory, skill_file, front, body))
    if not discovered:
        raise ValueError('未找到 SKILL.md：所选位置不是 Agent Skills 技能目录')
    discovered.sort(key=lambda item: item[0])
    license_file, root_license = _root_license(staging)
    front_license = next((value for value in
        (_license_str(item[3].get('license')) for item in discovered) if value), None)
    family_license = root_license or front_license
    family_id = _family_id_for(source_key, 'import-' + _slug(base_slug))
    files, total = _inventory(staging)
    skills = []
    used = set()
    for rel, directory, skill_file, front, body in discovered:
        candidate = base_slug if rel == '.' else rel
        slug, counter = candidate, 2
        while slug in used:  # 根技能 slug 与同名子目录去重
            slug, counter = f'{candidate}-{counter}', counter + 1
        used.add(slug)
        skills.append({
            'id': f'{family_id}/{slug}',
            'slug': slug,
            'name': str(front.get('name') or (name if rel == '.' else directory.name)),
            'description': str(front.get('description') or _first_paragraph(body)),
            'version': _version_str(front),
            'entry': f'{family_id}/{rel}/{skill_file}' if rel != '.' else f'{family_id}/{skill_file}',
            'files': len(files) if rel == '.' else sum(1 for p in files if p.startswith(rel + '/')),
            'license': _license_str(front.get('license')) or family_license})
    return {'id': family_id, 'name': name, 'source': source, 'revision': revision,
            'snapshot_sha256': _snapshot(files), 'skills': skills, 'files': files,
            'bytes': total, 'imported': True, 'imported_at': _now_iso(),
            'license': family_license, 'license_file': license_file, 'source_key': source_key}


def _with_family(current: dict, family: dict) -> dict:
    families = list(current.get('families') or [])
    for index, existing in enumerate(families):
        if existing.get('id') == family['id']:
            families[index] = family
            break
    else:
        families.append(family)
    return {'format': CATALOG_FORMAT, 'families': families}


def _write_catalog(data: dict) -> None:
    global _cache
    base = root()
    base.mkdir(parents=True, exist_ok=True)
    tmp = base / ('.catalog-' + uuid.uuid4().hex + '.json')
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(tmp, base / 'catalog.json')
    finally:
        if tmp.exists():
            tmp.unlink()
    _cache = None


def _commit(family: dict, staging: Path) -> None:
    """先替换目录再原子写目录条目；失败回滚，不留半截内容。"""
    base = root()
    dest = base / family['id']
    backup = None
    if dest.exists():
        backup = base / ('.backup-' + uuid.uuid4().hex)
        dest.rename(backup)
    try:
        staging.rename(dest)
        _write_catalog(_with_family(catalog(), family))
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        if backup is not None and backup.exists():
            backup.rename(dest)
        raise
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)
