"""Populate the verified tokenizer data before freezing an offline desktop app.

Some LiteLLM wheels omit tiktoken's cl100k cache even though importing LiteLLM
requires it. tiktoken verifies each resource against its embedded SHA256. A
first build may download these public files; the delivered app uses local data.
"""
import importlib.util
import os
from pathlib import Path


def main():
    spec = importlib.util.find_spec('litellm')
    if spec is None or spec.origin is None:
        raise RuntimeError('Install the backend dependencies before preparing tokenizers.')
    cache = Path(spec.origin).parent / 'litellm_core_utils' / 'tokenizers'
    cache.mkdir(parents=True, exist_ok=True)
    os.environ['TIKTOKEN_CACHE_DIR'] = str(cache)
    os.environ['CUSTOM_TIKTOKEN_CACHE_DIR'] = str(cache)
    import tiktoken
    for name in tiktoken.list_encoding_names():
        encoding = tiktoken.get_encoding(name)
        assert encoding.decode(encoding.encode('PaperMind 中文启动检查')) == 'PaperMind 中文启动检查'
        print(f'Tokenizer ready: {name}', flush=True)


if __name__ == '__main__':
    main()
