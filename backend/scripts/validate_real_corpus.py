"""Opt-in, resumable acceptance run over distinct public ACL papers.

Run `prepare`, configure models in this dedicated test database, then `index`
and `review`. The last two phases use the configured paid model APIs. Paper
selection is a deterministic topical sample, not a systematic literature search.
Never point --data at a user's existing library.
"""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def emit(**value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def text(element):
    return ''.join(element.itertext()).strip() if element is not None else ''


def manifest(root, count):
    import httpx
    saved = root / 'manifest.json'
    if saved.exists():
        data = json.loads(saved.read_text(encoding='utf-8'))
        if len(data['papers']) != count:
            raise ValueError('Use the original count or a new test directory')
        return data['papers']
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        response = client.get('https://api.github.com/repos/acl-org/acl-anthology/commits/master')
        # Anonymous GitHub API quotas can be exhausted. The saved XML and its
        # content hash still identify the exact metadata used in that case.
        commit = response.json()['sha'] if response.is_success else None
        candidates = []
        sources = []
        for year in (2023, 2024):
            for venue in ('acl', 'emnlp', 'findings'):
                filename = f'{year}.{venue}.xml'
                url = f'https://raw.githubusercontent.com/acl-org/acl-anthology/{commit or "master"}/data/xml/{filename}'
                response = client.get(url)
                response.raise_for_status()
                (root / filename).write_bytes(response.content)
                sources.append(dict(url=url, sha256=hashlib.sha256(response.content).hexdigest()))
                collection = ET.fromstring(response.content)
                for volume in collection.findall('volume'):
                    for paper in volume.findall('paper'):
                        title, abstract = text(paper.find('title')), text(paper.find('abstract'))
                        if not re.search(r'retriev|\brag\b', title, re.I):
                            continue
                        if not re.search(r'generation|language model|question answering', title + ' ' + abstract, re.I):
                            continue
                        aid = f'{collection.attrib["id"]}-{volume.attrib["id"]}.{paper.attrib["id"]}'
                        candidates.append(dict(id=aid, title=title, abstract=abstract, year=year,
                            venue=venue, doi=text(paper.find('doi')) or None,
                            authors=[' '.join(filter(None, [text(a.find('first')), text(a.find('last'))])) for a in paper.findall('author')],
                            url=f'https://aclanthology.org/{aid}/', pdf_url=f'https://aclanthology.org/{aid}.pdf'))
                emit(phase='metadata', collection=filename, candidates=len(candidates))
        # Fixed hash order avoids just selecting the first conference's papers.
        candidates.sort(key=lambda p: hashlib.sha256(p['id'].encode()).hexdigest())
        if len(candidates) < count:
            raise ValueError(f'Only {len(candidates)} matching distinct papers found')
        papers = candidates[:count]
        write(saved, dict(selection='2023–2024 ACL/EMNLP/Findings: retrieval in title; generation/LLM/QA in title or abstract; fixed SHA256 order',
                          commit=commit, eligible=len(candidates), metadata=sources, papers=papers))
        return papers


def prepare(root, engine, count):
    import httpx
    from sqlmodel import Session, select
    from app.models import Paper
    from app.ingestion.service import persist_fetched
    from app.ingestion.sources import FetchedPaper
    papers = manifest(root, count)
    downloads = root / 'downloads'
    downloads.mkdir(exist_ok=True)
    results = []
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        for p in papers:
            started = time.monotonic()
            try:
                path = downloads / (p['id'] + '.pdf')
                if not path.exists():
                    for attempt in range(3):
                        try:
                            response = client.get(p['pdf_url'])
                            break
                        except httpx.TransportError:
                            if attempt == 2:
                                raise
                            time.sleep(2)
                    response.raise_for_status()
                    if not response.content.startswith(b'%PDF-'):
                        raise ValueError('Response is not a PDF')
                    path.write_bytes(response.content)
                    time.sleep(1)  # Avoid a burst of requests to the public archive.
                with Session(engine) as session:
                    existing = session.exec(select(Paper).where(Paper.source_ref == p['id'])).first()
                    if existing is None or '<!-- page:' not in (existing.full_text or ''):
                        existing = persist_fetched(session, FetchedPaper(source='acl', source_ref=p['id'],
                            title=p['title'], abstract=p['abstract'], authors=p['authors'], year=p['year'],
                            venue=p['venue'], doi=p['doi'], pdf_bytes=path.read_bytes()), root / 'pdfs')
                    result = dict(id=p['id'], paper_id=existing.id, characters=len(existing.full_text or ''),
                                  page_markers=len(re.findall(r'<!-- page:\d+ -->', existing.full_text or '')),
                                  pdf_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), seconds=round(time.monotonic()-started, 2))
            except Exception as exc:
                result = dict(id=p['id'], error_type=type(exc).__name__)
            results.append(result)
            write(root / 'prepare-result.json', results)
            emit(phase='prepare', position=len(results), total=count, **result)
    return not any('error_type' in r or not r.get('characters') for r in results)


def index(root, engine):
    from sqlmodel import Session, select
    from app.models import Paper, PaperChunk
    from app.rag.index import index_paper
    from app.providers.selection import pick_llm
    with Session(engine) as session:
        ctx = pick_llm(session, 'embedding')
        if not ctx:
            raise ValueError('Configure an embedding model in the test database first')
        ids = list(session.exec(select(Paper.id).where(Paper.is_deleted == False)))
        model = ctx[2]
    results = []
    for pid in ids:
        started = time.monotonic()
        try:
            with Session(engine) as session:
                existing = session.exec(select(PaperChunk.id).where(PaperChunk.paper_id == pid, PaperChunk.embedding_model == model)).first()
                if existing is not None:
                    result = dict(paper_id=pid, reused=True)
                else:
                    result = dict(paper_id=pid, chunks=index_paper(session, session.get(Paper, pid)))
        except Exception as exc:
            result = dict(paper_id=pid, error_type=type(exc).__name__)
        result['seconds'] = round(time.monotonic()-started, 2)
        results.append(result)
        write(root / 'index-result.json', results)
        emit(phase='index', position=len(results), total=len(ids), **result)
        if 'error_type' in result:
            return False  # Resume without repeating successful paid embeddings.
    return True


def review(root, engine):
    from sqlmodel import Session, select
    from uuid import uuid4
    from app.models import TokenUsage
    from app.reviews import service
    rid_path = root / 'review-id.txt'
    if rid_path.exists():
        rid = rid_path.read_text().strip()
    else:
        rid = str(uuid4())
        with Session(engine) as session:
            service.create(session, rid, '检索增强生成与知识密集型问答：比较检索器与生成器如何协同、检索质量和证据使用、训练与推理成本、评价设置及失效条件。围绕机制差异形成连贯综述，不写逐篇摘要列表。', [], True)
        rid_path.write_text(rid)
    with Session(engine) as session:
        before = service.detail(session, rid)
        if before['status'] == 'ready':
            token = None
        else:
            # Recovery requires the old process to be known stopped by the caller.
            if before['status'] == 'running':
                raise ValueError('Review is running; inspect its process before recovering')
            token = service.start(session, rid)
    started = time.monotonic()
    emit(phase='review', review_id=rid, running=bool(token))
    if token:
        service.run(engine, rid, token)
    with Session(engine) as session:
        result = service.detail(session, rid)
        (root / 'review.md').write_text(result['content'], encoding='utf-8')
        (root / 'coverage.jsonl').write_text(service.coverage(session, rid), encoding='utf-8')
        usage = session.exec(select(TokenUsage).where(TokenUsage.ref_id == rid)).all()
        summary = {k: result[k] for k in ('id', 'status', 'stage', 'counts', 'version')}
        summary.update(characters=len(result['content']), seconds=round(time.monotonic()-started, 2),
                       model_calls=len(usage), tokens=sum(u.total_tokens for u in usage), content_quality_accepted=False)
        write(root / 'review-result.json', summary)
        emit(**summary)
        return result['status'] == 'ready'


def pause(root, engine):
    from sqlmodel import Session
    from app.reviews import service
    rid = (root / 'review-id.txt').read_text().strip()
    with Session(engine) as session:
        result = service.stop(session, rid)
        emit(phase='pause', review_id=rid, status=result['status'], counts=result['counts'])
    return True


# Known-item probes, grounded in the saved official abstracts. These labels are
# intentionally non-exhaustive; a hit rate is not retrieval precision or proof
# that generated claims are correct.
QUERIES = [
    ('2024.findings-emnlp.133', '通过反事实提示改变检索质量和证据使用方式，评估检索增强回答的不确定性和风险'),
    ('2023.acl-long.557', '将思维链推理步骤与检索交替执行来回答多步问题'),
    ('2023.findings-emnlp.655', '通过摘要压缩和语义压缩减少检索增强生成的输入 token 成本'),
    ('2024.emnlp-industry.66', '比较检索增强与长上下文模型，并依据模型自我反思在两条路线之间选择'),
    ('2024.emnlp-main.813', '为每份检索文档生成阅读笔记，降低无关文档和噪声对回答的影响'),
    ('2024.emnlp-main.1241', '在生物医学语料上无监督预训练，再结合标注数据与合成样本进行指令微调的稠密检索器'),
    ('2024.findings-emnlp.143', '代码生成中同步演化检索查询和多来源知识库，应对更新频繁的库与长尾编程语言'),
    ('2024.findings-emnlp.237', '在一次前向传递中统一文本生成和向量检索，让语言模型生成检索 token'),
]


def retrieve(root, engine):
    from sqlmodel import Session, select, func
    from app.models import Paper, PaperChunk
    from app.rag.scalable import hybrid
    results = []
    with Session(engine) as session:
        papers = {p.source_ref: p for p in session.exec(select(Paper).where(Paper.is_deleted == False))}
        chunks = session.exec(select(func.count()).select_from(PaperChunk)).one()
        for aid, query in QUERIES:
            if aid not in papers:
                continue
            started = time.monotonic()
            hits = hybrid(session, query, [p.id for p in papers.values()], k=12)
            target = papers[aid].id
            found = next((i+1 for i, hit in enumerate(hits) if hit.paper_id == target), None)
            results.append(dict(expected=aid, query=query, expected_chunk_rank=found,
                seconds=round(time.monotonic()-started, 3),
                hits=[dict(paper_id=h.paper_id, ordinal=h.ordinal, text=h.text) for h in hits]))
            emit(phase='retrieve', expected=aid, rank=found, seconds=results[-1]['seconds'])
    report = dict(papers=len(papers), chunks=chunks, probes=len(results),
                  known_item_hits=sum(r['expected_chunk_rank'] is not None for r in results),
                  all_returned_chunks_have_pages=all(h['ordinal']==0 or re.match(r'^\[第 \d+ 页\]', h['text']) for r in results for h in r['hits']),
                  scope='Chinese known-item queries over English papers; not an exhaustive relevance or writing-quality evaluation',
                  results=results)
    write(root / 'retrieval-result.json', report)
    return len(results) == len(QUERIES)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--count', type=int, default=100)
    parser.add_argument('phase', choices=['prepare', 'index', 'retrieve', 'review', 'pause'])
    args = parser.parse_args()
    root = args.data.resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / '.papermind-acceptance'
    if not marker.exists():
        if any(root.iterdir()):
            raise ValueError('Choose an empty directory for the isolated test library')
        marker.write_text('Public ACL corpus acceptance database; not a user library.\n')
    os.environ.update(PAPERMIND_DATA_DIR=str(root), PAPERMIND_DB_PATH=str(root / 'test.sqlite'),
                      PAPERMIND_MASTER_KEY_PATH=str(root / 'master.key'), PAPERMIND_NO_AUTOLOAD_SKILLS='1',
                      LITELLM_LOCAL_MODEL_COST_MAP='True')
    from sqlmodel import SQLModel
    from app.db.engine import get_engine
    import app.models  # register tables
    logging.getLogger('LiteLLM').setLevel(logging.CRITICAL)
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    ok = prepare(root, engine, args.count) if args.phase == 'prepare' else globals()[args.phase](root, engine)
    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    main()
