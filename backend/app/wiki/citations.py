"""Give the model short citation labels; preserve stable IDs only in storage."""
import copy
import re


def model_payload(inputs):
    payload=copy.deepcopy({k:v for k,v in inputs.items() if k!='evidence'})
    aliases={f'S{i}':entry['ref'] for i,entry in enumerate(payload['model_evidence'],1)}
    reverse={ref:alias for alias,ref in aliases.items()}
    for entry in payload['model_evidence']:
        entry['ref']=reverse[entry['ref']]
    for ref,alias in reverse.items():
        payload['prior_content']=payload.get('prior_content','').replace('['+ref+']','['+alias+']')
    return payload,aliases


def resolve_citations(content, aliases):
    """Resolve only explicit, known citations; never guess a missing source.

    Accept grouped labels as well as single labels. Bibliography metadata is
    derived from the body, so there is no second model-generated source list.
    """
    used=[]
    allowed=set(aliases.values())
    def replace(match):
        body=match.group(1).strip()
        # Ordinary Markdown links and prose in brackets are not citations.
        if not re.search(r'\bS\d+\b|\b[WAP][a-f0-9]{8,}\b',body):
            return match.group(0)
        labels=re.split(r'\s*[,，;；、]\s*|\s+',body)
        result=[]
        for label in labels:
            ref=aliases.get(label,label if label in allowed else None)
            if ref is None:
                raise ValueError('正文包含未提供或格式不完整的来源标识：'+label[:60])
            if ref not in used:
                used.append(ref)
            result.append('['+ref+']')
        return ''.join(result)
    normalized=re.sub(r'\[([^\[\]\n]+)\](?!\()',replace,content)
    if not used:
        raise ValueError('正文没有引用本轮提供的来源')
    return normalized,used
