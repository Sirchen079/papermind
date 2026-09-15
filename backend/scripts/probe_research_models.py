"""Small explicit provider probe. Secret is read without echo, never persisted."""
import getpass
import json

import httpx


def main():
    key = getpass.getpass('API key (hidden): ')
    tests = [
        ('models', 'GET', '/api/v1/models', None),
        ('responses', 'POST', '/api/v1/responses', {'model': 'glm-5.3', 'input': 'Reply only OK.', 'max_output_tokens': 128}),
        ('chat', 'POST', '/api/paas/v4/chat/completions', {'model': 'glm-5.3', 'messages': [{'role': 'user', 'content': 'Reply only OK.'}], 'max_tokens': 512, 'reasoning_effort': 'low'}),
    ]
    with httpx.Client(timeout=45, follow_redirects=False, headers={'Authorization': 'Bearer ' + key}) as client:
        for name, method, endpoint, payload in tests:
            try:
                response = client.request(method, 'https://open.bigmodel.cn' + endpoint, json=payload)
                data = response.json()
                if name == 'models':
                    result = [{'id':m.get('slug',m.get('id')),'input_modalities':m.get('input_modalities')} for m in data.get('models',data.get('data',[]))]
                elif name == 'responses':
                    result = [b.get('text') for item in data.get('output',[]) if item.get('type')=='message' for b in item.get('content',[]) if b.get('type')=='output_text']
                else:
                    result = [c.get('message',{}).get('content') for c in data.get('choices',[])]
                print(json.dumps({'probe':name,'http_status':response.status_code,'result':result,'usage':data.get('usage')},ensure_ascii=True),flush=True)
            except httpx.HTTPError as exc:
                print(json.dumps({'probe': name, 'error': type(exc).__name__}), flush=True)


if __name__ == '__main__':
    main()
