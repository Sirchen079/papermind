"""Apply a configured reranker once, after the caller assembles its candidates."""
import logging
from sqlmodel import select
from app.models import Model, Paper
from app.providers.purposes import purpose_model, rerank_mode


def configuration(session):
    mode=rerank_mode(session)
    if mode=='off':return None
    try:
        ctx=purpose_model(session,'rerank_llm' if mode=='llm' else 'rerank')
        return (mode,ctx) if ctx else None
    except Exception:
        logging.getLogger(__name__).warning('Reranking configuration unavailable; using recall order')
        return None


def candidate_limit(k, config):
    return max(k,min(30 if config[0]=='llm' else 100,max(30,k*4))) if config else k


def apply(session, query, candidates, k, config):
    if config and candidates:
        mode,ctx=config
        client,provider,model=ctx
        try:
            # A table fragment often contains neither the paper name nor its
            # title. Keep that identity with the passage so named-paper queries
            # do not rank unrelated tables with the same numbers above it.
            paper_ids={row.paper_id for row,_ in candidates}
            titles=dict(session.exec(select(Paper.id,Paper.title).where(Paper.id.in_(paper_ids))).all())
            documents=[f'Paper: {titles.get(row.paper_id, "")[:500]}\nPassage:\n{row.text}' for row,_ in candidates]
            if mode=='llm':
                from app.rag.llm_rerank import rank
                row=session.exec(select(Model).where(Model.provider_id==provider.id,Model.model_id==model)).first()
                ranks=rank(ctx,query,documents,k,row.context_window if row else None,
                           reasoning_effort=row.reasoning_effort if row else None)
            else:
                ranks=client.rerank(provider,model,query,documents,k)
            return [(candidates[index][0],score) for index,score in ranks]
        except Exception:
            logging.getLogger(__name__).warning('Reranking unavailable; using original recall order')
    return candidates[:k]
