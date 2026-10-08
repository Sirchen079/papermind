"""Fetch the pinned CPU runtime once; packaging is offline after this step."""
import hashlib
from pathlib import Path
import shutil
import zipfile
import httpx

VERSION='b11146'
ARCHIVE=f'llama-{VERSION}-bin-win-cpu-x64.zip'
SHA256='14cf1303ca9ac3abd94816850532f9f9a69ac66fbaca3776fc6f9061c2fac1d1'
URL=f'https://github.com/ggml-org/llama.cpp/releases/download/{VERSION}/{ARCHIVE}'


def main():
    build=Path(__file__).resolve().parent
    vendor=build/'vendor';vendor.mkdir(exist_ok=True)
    archive=vendor/ARCHIVE
    if not archive.exists():
        temporary=archive.with_suffix('.part')
        with httpx.stream('GET',URL,follow_redirects=True,timeout=120) as response:
            response.raise_for_status()
            with temporary.open('wb') as output:
                for chunk in response.iter_bytes(1024*1024):output.write(chunk)
        temporary.replace(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=SHA256:
        raise RuntimeError('The downloaded llama.cpp archive does not match its pinned SHA256.')
    destination=vendor/'llama_cpp';destination.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.namelist():
            name=Path(member).name
            if name!=member:raise RuntimeError('Unexpected directory in runtime archive')
            if name.endswith('.dll') or name in {'llama-server.exe','LICENSE-LLVM-OpenMP'}:
                target=destination/name; contents=bundle.read(member)
                # Avoid rewriting identical DLLs while a development model is running.
                if not target.is_file() or target.read_bytes()!=contents:target.write_bytes(contents)
    shutil.copy2(build.parent/'third_party/llama_cpp/LICENSE',destination/'LICENSE')
    print(f'Local CPU runtime ready: {VERSION}',flush=True)


if __name__=='__main__':main()
