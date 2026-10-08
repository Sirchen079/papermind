"""Native SQLite vector scans: keep blobs in SQLite and only hydrate winners."""
import heapq
import math
import re
from sqlalchemy import func, case
from sqlmodel import select
from app.models import PaperChunk, Paper
from app.rag.vector import serialize, deserialize, cosine


def rank(session, query, model_id, k, paper_ids=None):
    filters = [Paper.is_deleted == False, PaperChunk.embedding_model == model_id,
               func.length(PaperChunk.embedding) == len(query) * 4]
    if paper_ids is not None:
        filters.append(PaperChunk.paper_id.in_(paper_ids))
    if not query or not any(query) or not all(math.isfinite(x) for x in query):
        return []
    try:
        connection = session.connection().connection.driver_connection
        try:
            connection.execute('select vec_version()').fetchone()
        except Exception:
            import sqlite_vec
            connection.enable_load_extension(True)
            try:
                sqlite_vec.load(connection)
            finally:
                connection.enable_load_extension(False)
        distance = func.vec_distance_cosine(PaperChunk.embedding, serialize(query))
        hits = session.exec(select(PaperChunk.id, distance.label('distance')).join(Paper)
            .where(*filters, distance.is_not(None)).order_by(distance, PaperChunk.id).limit(k)).all()
        scores = [(key, 1 - value) for key, value in hits if math.isfinite(value)]
    except Exception:
        # Hosts without the loadable extension still work without materializing
        # the entire corpus as Python float objects.
        rows = session.exec(select(PaperChunk.id, PaperChunk.embedding).join(Paper)
            .where(*filters).execution_options(yield_per=256))
        def candidates():
            for key, blob in rows:
                vec = deserialize(blob)
                if any(vec):
                    score = cosine(query, vec)
                    if math.isfinite(score):
                        yield score, -key, key
        scores = [(key, score) for score, _, key in heapq.nlargest(k, candidates())]
    if not scores:
        return []
    objects = {r.id:r for r in session.exec(select(PaperChunk).where(PaperChunk.id.in_([key for key,_ in scores])))}
    return [(objects[key], score) for key, score in scores]


def lexical(session, query, paper_ids, k=20):
    # Decimal results and identifiers such as 1-PAGER / Recall@1 carry the
    # question's conditions. Splitting 0.7 into single digits dropped it entirely.
    tokens = list(dict.fromkeys(t for t in re.findall(
        r'\d+(?:\.\d+)+|[a-zA-Z0-9_]+(?:[-@][a-zA-Z0-9_]+)*|[\u4e00-\u9fff]{2,}',
        query.lower()) if len(t)>1))[:16]
    if not tokens:
        return []
    score = sum(case((func.instr(func.lower(PaperChunk.text), word) > 0, 1), else_=0) for word in tokens)
    statement = select(PaperChunk, score.label('score')).join(Paper).where(Paper.is_deleted == False, score > 0)
    if paper_ids is not None:
        statement = statement.where(PaperChunk.paper_id.in_(paper_ids))
    return list(session.exec(statement.order_by(score.desc(), PaperChunk.id).limit(k)))


def hybrid(session, query, paper_ids, k=12):
    from app.rag.index import retrieve
    from app.rag import reranking
    query=(query or '').strip()
    if not query or k<=0 or paper_ids==[]:return []
    config=reranking.configuration(session)
    limit=reranking.candidate_limit(max(k,20),config)
    # Fuse raw recall first. Reranking only the semantic branch would omit
    # keyword-only evidence and let the later fusion override the model's order.
    from app.rag.queries import variants
    channels=[]
    for variant in variants(query,config):
        channels.append(retrieve(session,variant,limit,paper_ids,rerank=False))
        channels.append(lexical(session,variant,paper_ids,limit))
    scores = {}; objects = {}
    for results in channels:
        for position, (row, _) in enumerate(results):
            objects[row.id] = row
            scores[row.id] = scores.get(row.id, 0) + 1 / (60 + position)
    # Keep library discovery diverse, but let an explicit small paper scope use
    # the candidate budget. A fixed three-chunk cap here discarded methods and
    # result tables before the configured reranker could see them.
    candidate_count = limit if config else k
    per_paper = max(3, math.ceil(candidate_count / len(set(paper_ids)))) if paper_ids else 3
    result = []; counts = {}
    for key in sorted(scores, key=scores.get, reverse=True):
        row = objects[key]
        if counts.get(row.paper_id, 0) >= per_paper:
            continue
        result.append((row,scores[key])); counts[row.paper_id] = counts.get(row.paper_id, 0) + 1
        if len(result) == candidate_count:
            break
    return [row for row,_ in reranking.apply(session,query,result,k,config)]
