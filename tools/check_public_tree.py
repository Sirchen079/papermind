"""Check staged publication files without printing matched private content."""
from pathlib import PurePosixPath
import re
import subprocess
import sys

PRIVATE_ROOTS=('docs/product/','docs/superpowers/','docs/internal/','private/','outputs/','work/','.codex/','.mimosa/','.superpowers/')
PRIVATE_NAMES={'context.md','agents.md','claude.md','master.key','connections.key','api_token','.env'}
PRIVATE_SUFFIXES={'.sqlite','.sqlite-wal','.sqlite-shm','.log','.jsonl','.har','.zip','.7z','.exe','.pfx','.p12','.pem'}
PATTERNS={
    'personal_home_path':re.compile(rb'(?i)(?:[a-z]:[\\/]{1,2}Users[\\/]{1,2}(?!Public|Default)[a-z0-9_.-]+|/Users/[a-z0-9_.-]+|/home/[a-z0-9_.-]+)'),
    'private_key':re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'access_key':re.compile(rb'\bAKIA[0-9A-Z]{16}\b'),
}
PROFILE_MARKERS=('用户长期偏好','个人画像','用户画像','侧写','主研究方向','导师要求')


def check_file(name, data):
    path=PurePosixPath(name)
    reasons=[]
    if name.lower().startswith(PRIVATE_ROOTS) or path.name.lower() in PRIVATE_NAMES or path.suffix.lower() in PRIVATE_SUFFIXES:
        reasons.append('private_or_generated_file')
    # This policy file names the patterns it checks, without storing user data.
    if name != 'tools/check_public_tree.py':
        for label, pattern in PATTERNS.items():
            if pattern.search(data):reasons.append(label)
        if any(marker.encode() in data for marker in PROFILE_MARKERS):
            reasons.append('personal_profile_marker')
    return reasons


def main():
    names=subprocess.check_output(['git','ls-files','-z']).decode('utf-8').split('\0')
    failures=[]
    with subprocess.Popen(['git','cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE) as reader:
        for name in filter(None,names):
            if '\n' in name or '\r' in name:
                failures.append(('invalid_filename','unsupported_filename'));continue
            reader.stdin.write((':'+name+'\n').encode());reader.stdin.flush()
            header=reader.stdout.readline().split()
            if len(header)!=3 or header[1]!=b'blob':
                failures.append((name,'unreadable_staged_file'));continue
            data=reader.stdout.read(int(header[2]));reader.stdout.read(1)
            for reason in check_file(name,data):
                failures.append((name,reason))
        reader.stdin.close()
        reader.wait()
    for name,reason in failures:
        print(f'{name}: {reason}')
    print(f'Publication check: {len(failures)} finding(s). Matched contents are not displayed.')
    return int(bool(failures))


if __name__=='__main__':
    sys.exit(main())
