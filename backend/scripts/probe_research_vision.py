"""Three synthetic image probes using only the isolated preview configuration."""
import base64
import json
import os
from pathlib import Path
import sys
import time

root=Path(__file__).resolve().parents[2]
preview=root/'.research-dev'/'preview'
os.environ['PAPERMIND_DATA_DIR']=str(preview)
os.environ['PAPERMIND_DB_PATH']=str(preview/'preview.sqlite')
os.environ['PAPERMIND_MASTER_KEY_PATH']=str(preview/'master.key')
os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='True'
sys.path.insert(0,str(root/'backend'))

import fitz
from sqlmodel import Session, select
from app.db.engine import get_engine
from app.models import Provider
from app.providers.client import ProviderClient
from app.security.crypto import get_crypto


def main():
    output=root/'.research-dev'/'vision-trials.jsonl'
    with Session(get_engine()) as session:
        provider=session.exec(select(Provider).where(Provider.name=='GLM Responses')).one()
    client=ProviderClient(lambda:Session(get_engine()),get_crypto())
    with output.open('x',encoding='utf-8') as target:
        for number,rows in enumerate([
            ['Method | Split | nDCG@10','A | S1 | 0.42','B | S2 | 0.39'],
            ['Method | nDCG@10','A | 0.42','B | 0.39','Dataset and split not provided.'],
            ['Method | Split | nDCG@10','A | S1 | 0.42','B | S1 | 0.39','No variance or significance test provided.'],
        ],1):
            doc=fitz.open();page=doc.new_page(width=500,height=240)
            page.insert_text((24,30),'SYNTHETIC EXAMPLE - NOT REAL EXPERIMENT',fontsize=13)
            for i,text in enumerate(rows):page.insert_text((24,65+i*32),text,fontsize=16)
            png=page.get_pixmap(matrix=fitz.Matrix(1.5,1.5)).tobytes('png');doc.close()
            prompt='Read this synthetic table. Return JSON with fields rows (extracted values), directly_comparable (true/false/null), significance_known (boolean), limitations (array). Different splits are not directly comparable; missing splits remain unknown. No actual experiment was run. Do not output reasoning.'
            started=time.monotonic()
            try:
                result=client.complete(provider,'glm-5.3-flash',[{'role':'user','content':[{'type':'input_text','text':prompt},{'type':'input_image','image_url':'data:image/png;base64,'+base64.b64encode(png).decode()}]}],'research_vision_trial',max_tokens=2400,reasoning_effort='low')
                row={'case_id':f'V{number:02}','model':'glm-5.3-flash','output':result.content,'tokens':result.total_tokens,'latency_ms':round((time.monotonic()-started)*1000)}
            except Exception as exc:
                row={'case_id':f'V{number:02}','error_type':type(exc).__name__}
            target.write(json.dumps(row,ensure_ascii=False)+'\n');target.flush()
            print(json.dumps({k:v for k,v in row.items() if k!='output'}),flush=True)
            if row.get('error_type'):return


if __name__=='__main__':main()
