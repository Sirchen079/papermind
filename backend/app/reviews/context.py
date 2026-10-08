"""Budget the entire request and share space across evidence, not just its prefix."""
from app.agent.context import estimate_tokens
from app.providers.output_budget import text_budget, response_budget


def clip(text, tokens):
    if estimate_tokens(text) <= tokens:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if estimate_tokens(text[:mid]) <= tokens: lo = mid
        else: hi = mid - 1
    return text[:lo]


def balanced(text, tokens):
    """Water-fill complete paragraphs, so later evidence keeps its own space."""
    parts = [p for p in text.split('\n\n') if p.strip()]
    if estimate_tokens(text) <= tokens: return text
    if not parts: return ''
    available = max(0, tokens - len(parts))
    costs = [estimate_tokens(p) for p in parts]
    grants = [0] * len(parts)
    pending = set(range(len(parts)))
    while pending and available > 0:
        share = max(1, available // len(pending))
        for i in sorted(pending):
            given = min(share, costs[i] - grants[i], available)
            grants[i] += given; available -= given
        pending = {i for i in pending if grants[i] < costs[i]}
    return '\n\n'.join(clip(p, n) for p, n in zip(parts, grants) if n)


def segments(text, tokens):
    """Split a long draft without dropping any characters; prefer paragraph boundaries."""
    result=[]
    while text:
        part=clip(text,tokens)
        if not part:part=text[:1]
        if len(part)<len(text):
            boundary=part.rfind('\n\n')
            if boundary>len(part)//2:part=part[:boundary+2]
        result.append(part);text=text[len(part):]
    return result


def prepare(system, question, instruction, material, window, output, guide_text='',
            reasoning_effort=None, reasoning_budget=None, required_text=None):
    output = response_budget(window, output, reasoning_effort, reasoning_budget)
    prefix = f'综述主题：{question}\n{instruction}\n\n材料：\n'
    # A small framing/tokenizer margin, not a refusal threshold.
    margin = min(512, max(96, window // 32))
    system = system + ('\n\n' + guide_text if guide_text else '')
    room = max(0, window - output - margin - estimate_tokens(system + prefix))
    material_room=room
    if isinstance(material, dict):
        labels = ''.join(k+'：\n\n' for k in material)
        room = max(0, room-estimate_tokens(labels))
        values = list(material.values())
        costs = [estimate_tokens(v) for v in values]
        # Each component receives space; short plans return unused space to sources.
        caps = [min(c, room//max(1,len(costs))) for c in costs]
        extra = room - sum(caps)
        needs = sum(c-n for c,n in zip(costs,caps))
        caps = [n + int(extra*(c-n)/needs) if needs else n for c,n in zip(costs,caps)]
        fitted = '\n\n'.join(k+'：\n'+balanced(v,n) for (k,v),n in zip(material.items(),caps))
        original = '\n\n'.join(k+'：\n'+v for k,v in material.items())
    else:
        original = material; fitted = balanced(material, room)
    if required_text and required_text in original and required_text not in fitted:
        # A revision must see the entire passage it is replacing. Give that
        # passage space first, then share the remainder across its evidence.
        target='当前待修订正文：\n'+required_text
        heading='\n\n其他上下文与原文依据：\n'
        remaining=material_room-estimate_tokens(target+heading)-32
        if remaining>=0:
            background=original.replace(required_text,'',1)
            fitted=target+heading+balanced(background,remaining)
    return [{'role':'system','content':system},{'role':'user','content':prefix+fitted}], output, fitted == original
