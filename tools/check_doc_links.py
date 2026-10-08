"""Check relative links between tracked markdown files in this repository."""
from pathlib import Path
from urllib.parse import unquote
import re
import subprocess
import sys

EXCLUDED_DIRS = {'node_modules', 'backend/builtin_skills', 'third_party'}
INLINE_LINK = re.compile(r'\]\(\s*(?:<([^<>]*)>|([^)\s]+))(?:\s+"[^"]*")?\s*\)')
REFERENCE_LINK = re.compile(r'^\s{0,3}\[[^\]\n]+\]:\s*(?:<([^<>]*)>|(\S+))', re.MULTILINE)


def tracked_markdown_files(repo_root):
    out = subprocess.check_output(['git', 'ls-files', '-z', '--', '*.md']).decode('utf-8').split('\0')
    for name in filter(None, out):
        posix = name.replace('\\', '/')
        if any(posix.startswith(prefix + '/') for prefix in EXCLUDED_DIRS):
            continue
        yield repo_root / name


def link_targets(text):
    for match in INLINE_LINK.finditer(text):
        yield next(group for group in match.groups() if group is not None)
    for match in REFERENCE_LINK.finditer(text):
        yield next(group for group in match.groups() if group is not None)


def checkable(target):
    stripped = target.strip()
    if not stripped or stripped.startswith('#'):
        return None
    if '://' in stripped or stripped.startswith('mailto:'):
        return None
    return stripped.split('#', 1)[0].strip()


def main():
    repo_root = Path(__file__).resolve().parent.parent
    broken = []
    for md_path in tracked_markdown_files(repo_root):
        text = md_path.read_text(encoding='utf-8', errors='replace')
        for raw in link_targets(text):
            target = checkable(raw)
            if target is None:
                continue
            resolved = md_path.parent / unquote(target)
            if not resolved.exists():
                broken.append(f'{md_path.relative_to(repo_root).as_posix()}: {raw}')
    for item in broken:
        print(item)
    print(f'Broken doc links: {len(broken)}')
    return 1 if broken else 0


if __name__ == '__main__':
    sys.exit(main())
