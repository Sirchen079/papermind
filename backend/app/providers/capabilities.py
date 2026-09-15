"""Narrow, documented provider capabilities absent from older SDK catalogs.

Verified 2026-09-15 against:
https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3
https://docs.bigmodel.cn/cn/guide/capabilities/thinking-mode
"""
from urllib.parse import urlsplit


def official_glm53(provider,model_id):
    return (getattr(provider,'type',None)=='openai_chat'
            and urlsplit(getattr(provider,'base_url',None) or '').hostname=='open.bigmodel.cn'
            and model_id.lower() in {'glm-5.3','glm-5.3-flash'})


def reasoning_options(provider,model_id,effort=None):
    if not official_glm53(provider,model_id):
        return {}
    effort=effort or 'low'
    if effort not in {'low','high','max'}:
        raise ValueError('GLM-5.3 的推理强度必须为 low、high 或 max')
    # Send documented vendor fields through extra_body: older LiteLLM model
    # catalogs must not silently erase an explicitly supported parameter.
    return {'extra_body':{'reasoning_effort':effort,'thinking':{'type':'enabled','clear_thinking':True}}}


def known_context_window(provider,model_id):
    return 1_000_000 if official_glm53(provider,model_id) and model_id.lower()=='glm-5.3' else None
