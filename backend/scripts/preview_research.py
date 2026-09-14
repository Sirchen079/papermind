"""Start a local development preview using only seeded synthetic papers."""
import getpass
import os
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[2]
empty='--empty' in sys.argv
preview=root/'.research-dev'/('onboarding-preview' if empty else 'preview')
preview.mkdir(parents=True,exist_ok=True)
os.environ['PAPERMIND_DATA_DIR']=str(preview)
os.environ['PAPERMIND_DB_PATH']=str(preview/'preview.sqlite')
os.environ['PAPERMIND_MASTER_KEY_PATH']=str(preview/'master.key')
os.environ['PAPERMIND_NO_AUTOLOAD_SKILLS']='1'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='True'
sys.path.insert(0,str(root/'backend'))

from sqlmodel import Session, select
from app.main import create_app
from app.db.engine import get_engine
from app.models import Model, Paper, Provider
from app.security.crypto import get_crypto


def main():
    app=create_app()
    with Session(get_engine()) as session:
        existing=session.exec(select(Provider)).first()
        if existing is None and not empty:
            key=getpass.getpass('API key for isolated preview (hidden): ')
            provider=Provider(name='GLM Responses',type='openai_responses',base_url='https://open.bigmodel.cn/api/v1',api_key_encrypted=get_crypto().encrypt(key))
            session.add(provider);session.commit();session.refresh(provider)
            for model in ['glm-5.3','glm-5.3-flash']:
                session.add(Model(provider_id=provider.id,model_id=model,role_default='chat' if model=='glm-5.3' else None,is_manual=True,context_window=1048576))
            session.add(Paper(source='manual',title='合成示例 A · 稀疏检索',abstract='A sparse retrieval baseline.',full_text='Synthetic example only. On split S1, sparse retrieval scores nDCG@10 0.42. No supervised training labels are used. This is not a real experimental observation.'))
            session.add(Paper(source='manual',title='合成示例 B · 稠密检索',abstract='A dense retrieval baseline.',full_text='Synthetic example only. On split S2, dense retrieval scores nDCG@10 0.39 using supervised query-passage pairs. S2 has a different query distribution from S1. This is not a real experimental observation.'))
            session.add(Paper(source='manual',title='合成示例 C · 仅摘要',abstract='Synthetic abstract only. Sparse and dense retrieval are combined; full evaluation conditions are unavailable.'))
            session.commit()
    import uvicorn
    port=4290 if empty else 4289
    print(f'Isolated preview: http://127.0.0.1:{port}/',flush=True)
    uvicorn.run(app,host='127.0.0.1',port=port,log_level='warning')


if __name__=='__main__':main()
