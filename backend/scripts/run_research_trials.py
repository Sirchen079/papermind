"""Run bounded synthetic trials using the product's Responses adapter."""
import getpass
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('LITELLM_LOCAL_MODEL_COST_MAP', 'True')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.fernet import Fernet
from app.models import Provider
from app.providers.client import ProviderClient
from app.security.crypto import Crypto


class TrialClient(ProviderClient):
    def _record_usage(self, *args):
        pass  # usage is recorded alongside the final output below; no user DB


def main():
    key = getpass.getpass('API key (hidden): ')
    root = Path(__file__).resolve().parents[2]
    revised = '--revised' in sys.argv
    output = root / '.research-dev' / ('model-trials-v2.jsonl' if revised else 'model-trials.jsonl')
    output.parent.mkdir(exist_ok=True)
    if output.exists():
        raise RuntimeError('Trial file already exists; preserve it and select a new round explicitly.')
    crypto = Crypto(Fernet.generate_key())
    provider = Provider(name='Research trial', type='openai_responses', base_url='https://open.bigmodel.cn/api/v1', api_key_encrypted=crypto.encrypt(key))
    client = TrialClient(lambda: None, crypto)
    total_tokens = 0
    with output.open('x', encoding='utf-8') as target:
        for model in ['glm-5.3', 'glm-5.3-flash']:
            for number in range(1, 9):
                case_id = f'T{number:02}'
                prompt = (root / 'docs/product/model-trials/generated' / f'{case_id}.txt').read_text(encoding='utf-8')
                if revised:
                    prompt += '\n协议澄清 p0-v2：route 表示本步交给程序的分支，不是回答是否写完。只有输入明确用户停止/预算为零才选 stop；成功抽取、发现反例、修复或核查修订后选 continue。可比较条件不一致选 conditions_mismatch。目标需要的证据类型与现有材料不相干时 outcome=goal_mismatch、route=conditions_mismatch；仅缺同类字段时为 insufficient/missing_material。材料全部合成，任何数字不得称为真实实验观测。只有两个预算点时只陈述这两个点，不概括未测预算区间。\n'
                for run in range(1, 2 if revised else 4):
                    started = time.monotonic()
                    row = {'case_id':case_id,'run':run,'model':model,'prompt_version':'p0-v2' if revised else 'p0-v1','protocol':'responses','reasoning_effort':'low','max_output_tokens':2400 if revised else 2000,'cost':None}
                    try:
                        result = client.complete(provider, model, [{'role':'user','content':prompt}], 'research_trial', max_tokens=row['max_output_tokens'], reasoning_effort='low')
                        row.update(output=result.content, input_tokens=result.prompt_tokens, output_tokens=result.completion_tokens, total_tokens=result.total_tokens)
                        total_tokens += result.total_tokens
                    except Exception as exc:
                        # Do not serialize exception strings: SDK errors may include request headers.
                        row.update(output='', error_type=type(exc).__name__)
                    row['latency_ms'] = round((time.monotonic()-started)*1000)
                    target.write(json.dumps(row,ensure_ascii=False)+'\n')
                    target.flush()
                    print(json.dumps({k:row.get(k) for k in ['case_id','run','model','latency_ms','total_tokens','error_type']}), flush=True)
                    if row.get('error_type') or total_tokens > 150000:
                        print('Stopped at bounded error/token limit; inspect sanitized output before retrying.',flush=True)
                        return
    print(f'Completed {16 if revised else 48} text trials. Final outputs only; semantic review required.',flush=True)


if __name__ == '__main__':
    main()
