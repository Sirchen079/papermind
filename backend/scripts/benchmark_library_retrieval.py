"""Reproducible synthetic load test; not a scientific quality evaluation."""
import json
import os
from pathlib import Path
import random
import statistics
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlmodel import SQLModel,Session,select
from app.db.engine import make_engine
from app.models import Paper,PaperChunk
from app.rag.scalable import rank
from app.rag.vector import serialize

root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
path=root/'retrieval-1000.sqlite';engine=make_engine(path);SQLModel.metadata.create_all(engine)
random.seed(71)
dimension=1024
query=[random.uniform(-1,1) for _ in range(dimension)]
with Session(engine) as s:
    if s.exec(select(Paper.id).limit(1)).first() is None:
        for batch in range(20):
            rows=[Paper(source='manual',title=f'Synthetic load document {i}') for i in range(batch*50,(batch+1)*50)]
            s.add_all(rows);s.flush()
            blobs=[serialize([random.uniform(-1,1) for _ in range(dimension)]) for _ in range(50)]
            values=[{'paper_id':p.id,'ordinal':j,'text':f'Load-test chunk {p.id}/{j}', 'embedding':serialize(query) if p.id==1000 and j==49 else blobs[j],'embedding_model':'benchmark'} for p in rows for j in range(50)]
            s.execute(PaperChunk.__table__.insert(),values);s.commit()
timings=[]
for i in range(5):
    with Session(engine) as s:
        start=time.perf_counter();hits=rank(s,query,'benchmark',12);timings.append(time.perf_counter()-start)
        assert hits[0][0].paper_id==1000 and hits[0][0].ordinal==49
with Session(engine) as s:
    scoped=rank(s,query,'benchmark',12,[1,2,3]);assert all(h.paper_id in {1,2,3} for h,_ in scoped)
result={'papers':1000,'chunks':50000,'dimensions':dimension,'database_bytes':path.stat().st_size,'seconds':timings,'median_seconds':statistics.median(timings),'top_hit_correct':True,'scope_filter_correct':True,'corpus':'synthetic'}
(root/'retrieval-benchmark.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
