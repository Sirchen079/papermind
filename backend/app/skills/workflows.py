"""Task-facing entry points reuse the bundled writing routes and context budget."""
import hashlib
import json

from sqlmodel import select

from app.agent.context import DEFAULT_CONTEXT_WINDOW, estimate_tokens
from app.models import Skill
from app.reviews.writing import stage_guide
from app.skills import builtin


def writing_workflow(session, workflow, context_window=None):
    if workflow not in {'literature-synthesis', 'review-revision'}:
        return ''
    skill_id = 'nature/nature-writing'
    skill = session.exec(select(Skill).where(Skill.file_path == 'builtin://' + skill_id)).first()
    if skill is None or not skill.enabled:
        return '[本轮研究任务]\n所选写作指导未启用，按用户要求继续完成可做内容，不宣称已经使用该技能。'
    budget = max(256, (context_window or DEFAULT_CONTEXT_WINDOW) // 5)
    phase = 'edit' if workflow == 'review-revision' else 'related-work'
    guide = builtin.load(skill_id, axes={'paper_type': 'review'})
    revision = ''
    if workflow == 'review-revision':
        path = 'static/core/workflow.md'
        full = builtin.resource_path(skill_id, path).read_text(encoding='utf-8-sig')
        revision = '## 9.' + full.split('## 9.', 1)[1]
        budget = max(256, budget - estimate_tokens(revision) - 60)
    routed = stage_guide(guide, phase, budget)
    if revision:
        routed['text'] += '\n\n[static/core/workflow.md / step 9]\n' + revision
        routed['resources'].append({'path': path, 'sha256': hashlib.sha256(full.encode()).hexdigest(),
            'mode': 'excerpt', 'excerpt_sha256': hashlib.sha256(revision.encode()).hexdigest(),
            'excerpt_chars': len(revision)})
    # User edits remain part of explicitly selected writing guidance.
    original_body = builtin.resource_path(skill_id).read_text(encoding='utf-8-sig')
    if skill.body and skill.body != original_body:
        routed['text'] += '\n\n[用户修改的技能指令]\n' + skill.body
    routed['text'] += ('\n\n本轮按用户选择的研究任务使用上述指导，用户明确要求优先。'
                       '语言、篇幅与修改范围遵循用户要求；已有原文标识和链接沿用实际材料。'
                       '正文与已有文档通过当前工具读取、保存或局部修改。')
    routed['fingerprint'] = hashlib.sha256(routed['text'].encode()).hexdigest()
    routed['estimated_tokens'] = estimate_tokens(routed['text'])
    receipt = {key: value for key, value in routed.items() if key != 'text'}
    return ('[本轮研究任务：' + workflow + ']\n'
            + '[实际加载的技能资源]\n' + json.dumps(receipt, ensure_ascii=False)
            + '\n\n' + routed['text'])
