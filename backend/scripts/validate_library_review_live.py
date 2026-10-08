"""Opt-in public-paper test. Credentials come only from process environment.

Run with PAPERMIND_DATA_DIR pointing to a dedicated test directory.
No user library is read. All network documents below are public arXiv papers.
"""
import os
os.environ.setdefault('LITELLM_LOCAL_MODEL_COST_MAP','True')
import json
import logging
from pathlib import Path
import sys
import time
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
import pymupdf
from sqlmodel import Session, SQLModel, select
from app.db.engine import get_engine
from app.models import Paper, Provider, Model, TokenUsage
from app.security.crypto import get_crypto
from app.reviews import service
from app.rag.index import index_paper, retrieve

logging.getLogger('LiteLLM').setLevel(logging.CRITICAL)
DATA=[
 ('2005.11401','Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks'),
 ('2004.04906','Dense Passage Retrieval for Open-Domain Question Answering'),
 ('2004.12832','ColBERT: Efficient and Effective Passage Search via Contextualized Late Interaction over BERT'),
 ('2310.11511','Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection'),
 ('2401.15884','Corrective Retrieval Augmented Generation'),
 ('2212.10496','Precise Zero-Shot Dense Retrieval without Relevance Labels'),
 ('2404.16130','From Local to Global: A Graph RAG Approach to Query-Focused Summarization'),
 ('2312.10997','Retrieval-Augmented Generation for Large Language Models: A Survey'),
]


def main():
    root=Path(os.environ['PAPERMIND_DATA_DIR']);root.mkdir(parents=True,exist_ok=True)
    engine=get_engine();SQLModel.metadata.create_all(engine)
    crypto=get_crypto()
    with Session(engine) as s:
        for name,kind,base,key_env,mid,role in [
          ('Live Responses','openai_responses','https://open.bigmodel.cn/api/v1','PM_LIVE_BIGMODEL','glm-5.3-flash','chat'),
          ('Live Embedding','openai_compat','https://api.siliconflow.cn/v1','PM_LIVE_SILICONFLOW','BAAI/bge-m3','embedding')]:
            p=s.exec(select(Provider).where(Provider.name==name)).first()
            if p is None:
                p=Provider(name=name,type=kind,base_url=base,api_key_encrypted=crypto.encrypt(os.environ[key_env]));s.add(p);s.commit();s.refresh(p)
                s.add(Model(provider_id=p.id,model_id=mid,role_default=role,context_window=1048576 if role=='chat' else 8192,reasoning_effort='low' if role=='chat' else None));s.commit()
    for aid,title in DATA:
        with Session(engine) as s:
            existing=s.exec(select(Paper).where(Paper.source_ref==aid)).first()
            if existing:
                if existing.title!=title:
                    existing.title=title;s.add(existing);s.commit();index_paper(s,existing)
                continue
        pdf=root/(aid+'.pdf')
        if not pdf.exists():
            r=httpx.get('https://arxiv.org/pdf/'+aid,timeout=60,follow_redirects=True);r.raise_for_status();pdf.write_bytes(r.content)
        doc=pymupdf.open(pdf)
        text='\n\n'.join(f'<!-- page:{i+1} -->\n'+page.get_text() for i,page in enumerate(doc));doc.close()
        with Session(engine) as s:
            p=Paper(source='arxiv',source_ref=aid,arxiv_id=aid,title=title,full_text=text,citation_key='arxiv'+aid.replace('.',''))
            s.add(p);s.commit();s.refresh(p)
            try:n=index_paper(s,p);print(json.dumps({'indexed':aid,'chunks':n}),flush=True)
            except Exception as exc:print(json.dumps({'index_failed':aid,'type':type(exc).__name__}),flush=True)
    started=time.monotonic()
    with Session(engine) as s:
        hits=retrieve(s,'How do retrieval and self-reflection improve factual correctness?',k=8)
        print(json.dumps({'retrieval_hits':len(hits),'latency_seconds':round(time.monotonic()-started,3)}),flush=True)
        rid=str(uuid4());service.create(s,rid,'检索增强生成的研究路线：比较检索、生成与自我反思机制、评测条件及局限。',[],True)
    with Session(engine) as s:token=service.start(s,rid)
    print(json.dumps({'review_id':rid,'phase':'running'}),flush=True)
    service.run(engine,rid,token)
    with Session(engine) as s:
        result=service.detail(s,rid)
        (root/'review.md').write_text(result['content'],encoding='utf-8')
        (root/'coverage.jsonl').write_text(service.coverage(s,rid),encoding='utf-8')
        summary={k:result[k] for k in ('id','status','stage','error','counts','version')}
        summary['characters']=len(result['content']);summary['seconds']=round(time.monotonic()-started,2)
        usage=s.exec(select(TokenUsage).where(TokenUsage.ref_id==rid)).all()
        summary['model_calls']=len(usage);summary['tokens']=sum(u.total_tokens for u in usage)
        (root/'result.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(summary,ensure_ascii=False),flush=True)
        if result['status']!='ready' or not result['counts']['done']:raise SystemExit(1)


if __name__=='__main__':main()
