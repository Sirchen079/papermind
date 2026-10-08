"""Adapt the bundled Nature preparation/auditor to existing papers and saved work.

Upstream scripts are executed unchanged. A failed content audit is a diagnostic,
not a failed agent turn; immutable input snapshots make each report reproducible.
"""
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.config import get_settings
from app.models import Paper, PaperNote
from app.skills.builtin import resource_path, entry
from app.skills.script_runner import run_bundled_script
from app.ingestion.pdf_storage import resolve_pdf

SKILL_ID = 'nature/nature-paper-card'


def _root():
    return Path(get_settings().data_dir) / 'skill_runs'


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def _new(action, paper_id):
    run_id = uuid4().hex
    directory = _root()/run_id
    directory.mkdir(parents=True)
    return directory, {'run_id': run_id, 'action': action, 'paper_id': paper_id,
        'skill_id': SKILL_ID, 'skill_version': entry(SKILL_ID)['version'],
        'created_at': datetime.now(timezone.utc).isoformat(), 'material_kind': 'workflow_diagnostic'}


def _execute(directory, script_name, args):
    script = resource_path(SKILL_ID, 'scripts/'+script_name)
    return {'script': 'scripts/'+script_name, 'script_sha256': _hash(script),
            **run_bundled_script(script, args, directory/'execution')}


def _finish(directory, receipt, markdown):
    (directory/'report.md').write_text(markdown, encoding='utf-8')
    receipt['summary_md'] = markdown[:6000]
    receipt['artifacts'] = [{'name': p.name, 'sha256': _hash(p),
        'download_url': f'/api/builtin-skills/runs/{receipt["run_id"]}/files/{p.name}'}
        for p in directory.iterdir() if p.is_file() and p.name != 'receipt.json']
    receipt['receipt_url'] = f'/api/builtin-skills/runs/{receipt["run_id"]}/files/receipt.json'
    _write(directory/'receipt.json', receipt)
    return receipt


def _paper(session, paper_id):
    paper = session.get(Paper, paper_id)
    if paper is None or paper.is_deleted:
        raise LookupError('论文不存在')
    return paper


def _prepare(session, paper_id):
    paper = _paper(session, paper_id)
    pdf = resolve_pdf(paper.pdf_path, Path(get_settings().data_dir)/'pdfs')
    if pdf is None:
        raise ValueError('该论文没有本地 PDF。可先获取全文，或继续使用已有文本并说明材料范围。')
    pdf_hash = _hash(pdf)
    script_hash = _hash(resource_path(SKILL_ID, 'scripts/prepare_paper.py'))
    key = hashlib.sha256(f'{paper_id}:{pdf_hash}:{script_hash}'.encode()).hexdigest()
    index = _root()/'prepared'/f'{key}.json'
    if index.is_file():
        try:
            previous = _json(index)
            directory = run_directory(previous['run_id'])
            receipt = _json(directory/'receipt.json')
            if all(_hash(directory/a['name']) == a['sha256'] for a in receipt['artifacts']):
                return {**receipt, 'reused': True}, directory
        except (OSError, ValueError, KeyError, LookupError):
            pass
    directory, receipt = _new('prepare', paper_id)
    execution = _execute(directory, 'prepare_paper.py', [str(pdf), '--output', str(directory/'source_bundle.json')])
    receipt.update(execution=execution, source_sha256=pdf_hash, reused=False)
    bundle = _json(directory/'source_bundle.json') if (directory/'source_bundle.json').is_file() else None
    receipt['ok'] = execution['exit_code'] == 0 and execution['process_error'] is None and bundle is not None
    if bundle and bundle.get('source_sha256') != pdf_hash:
        receipt['ok'] = False
        bundle.setdefault('validation', {}).setdefault('errors', []).append('PDF 在处理期间变化，请基于当前文件重新整理。')
    if bundle:
        inventory = bundle.get('evidence_inventory', {})
        receipt.update(page_count=bundle.get('page_count'), validation=bundle.get('validation'),
            inventory_counts={key:len(items) for key,items in inventory.items()},
            inventory={key:items[:40] for key,items in inventory.items()},
            inventory_truncated=any(len(items)>40 for items in inventory.values()))
    markdown = '# 论文来源整理\n\n' + ('已执行 Nature 原始准备脚本。' if receipt['ok'] else '本次来源整理未完成。')
    if bundle:
        markdown += f'文件共 {bundle["page_count"]} 页。\n\n自动清单：' + json.dumps(receipt['inventory_counts'], ensure_ascii=False)
        for warning in bundle.get('validation', {}).get('warnings', []):
            markdown += '\n\n- '+warning
        for error in bundle.get('validation', {}).get('errors', []):
            markdown += '\n\n来源问题：'+error
    else:
        markdown += '\n\n'+execution['stderr']
    markdown += '\n\n自动清单可能漏掉图表和公式；整理完成不代表已读全文。请结合原 PDF 核对，缺口局部注明，可继续研究。'
    receipt = _finish(directory, receipt, markdown)
    if receipt['ok']:
        index.parent.mkdir(parents=True, exist_ok=True)
        pending = index.with_suffix('.'+uuid4().hex+'.tmp')
        _write(pending, {'run_id': receipt['run_id']}); pending.replace(index)
    return receipt, directory


def prepare_paper_card_sources(session, paper_id):
    receipt, _ = _prepare(session, paper_id)
    return json.dumps(receipt, ensure_ascii=False)


def audit_paper_card(session, paper_id, note_id=None, message_id=None, filename=None, content=None):
    _paper(session, paper_id)
    if sum([note_id is not None, message_id is not None or filename is not None, content is not None]) != 1:
        raise ValueError('请选择一份精确输入：论文笔记 note_id、已保存文档 message_id+filename，或尚未保存的 content。')
    if note_id is not None:
        note = session.get(PaperNote, note_id)
        if note is None or note.paper_id != paper_id:
            raise LookupError('当前论文中没有这条笔记')
        body, identity = note.content, {'note_id': note_id, 'updated_at': str(note.updated_at)}
    elif message_id is not None or filename is not None:
        if message_id is None or not filename:
            raise ValueError('已保存文档需要 message_id 和 filename')
        from app.agent.saved_documents import get_document
        document = get_document(session, message_id, filename)
        body, identity = document['content'], {'message_id': message_id, 'filename': filename}
    else:
        body, identity = content, {'kind': 'draft'}
    if not isinstance(body, str) or not body.strip():
        raise ValueError('精读卡正文为空')
    prepared, source_directory = _prepare(session, paper_id)
    if not prepared['ok']:
        return json.dumps({**prepared, 'audit_not_run': True}, ensure_ascii=False)
    directory, receipt = _new('audit', paper_id)
    shutil.copyfile(source_directory/'source_bundle.json', directory/'source_bundle.json')
    (directory/'paper-card.md').write_text(body, encoding='utf-8')
    mode = prepared['validation']['recommended_locator_mode']
    execution = _execute(directory, 'audit_paper_card.py', ['--card', str(directory/'paper-card.md'),
        '--bundle', str(directory/'source_bundle.json'), '--locator-mode', mode,
        '--report', str(directory/'audit-report.json')])
    report = _json(directory/'audit-report.json') if (directory/'audit-report.json').is_file() else None
    receipt.update(execution=execution, input=identity, input_sha256=_hash(directory/'paper-card.md'),
        source_sha256=prepared['source_sha256'], prepared_run_id=prepared['run_id'],
        source_validation=prepared['validation'], inventory_counts=prepared['inventory_counts'],
        ok=report is not None and execution['exit_code'] in (0,1) and execution['process_error'] is None,
        audit_pass=report is not None and report['summary']['errors']==0)
    markdown = '# 精读卡检查\n\n'
    if report:
        receipt.update(summary=report['summary'], findings=report['findings'])
        markdown += f'结构检查：{report["summary"]["errors"]} 项错误，{report["summary"]["warnings"]} 项提示。原稿保持不变。\n'
        for finding in report['findings']:
            if finding['level'] == 'pass': continue
            markdown += '\n- '+finding['message']
            if finding.get('details'): markdown += ' '+json.dumps(finding['details'], ensure_ascii=False)
    else:
        markdown += '本次脚本未完成：'+execution['stderr']
    for warning in prepared['validation'].get('warnings', []): markdown += '\n\n来源提示：'+warning
    markdown += '\n\n检查主要覆盖结构和标注约定，不证明科学结论正确；自动图式清单为空或有遗漏时仍需看原页。只修订相关内容，不阻断其他回答。'
    return json.dumps(_finish(directory, receipt, markdown), ensure_ascii=False)


def run_directory(run_id):
    if not isinstance(run_id, str) or not re.fullmatch('[a-f0-9]{32}', run_id):
        raise LookupError('执行记录不存在')
    directory = (_root()/run_id).resolve()
    if directory.parent != _root().resolve() or not (directory/'receipt.json').is_file():
        raise LookupError('执行记录不存在')
    return directory


def artifact_path(run_id, artifact):
    directory = run_directory(run_id)
    receipt = _json(directory/'receipt.json')
    if artifact not in {'receipt.json', *(a['name'] for a in receipt['artifacts'])}:
        raise LookupError('执行文件不存在')
    path = (directory/artifact).resolve()
    if path.parent != directory or not path.is_file():
        raise LookupError('执行文件不存在')
    return path


def read_skill_run(session, run_id, artifact='receipt.json', start_char=0, max_chars=12000):
    path = artifact_path(run_id, artifact)
    text = path.read_text(encoding='utf-8')
    start = max(0, int(start_char)); end = min(len(text), start+max(1,min(int(max_chars),20000)))
    return json.dumps({'run_id': run_id, 'artifact': artifact, 'material_kind': 'workflow_diagnostic',
        'text': text[start:end], 'start_char': start, 'total_chars': len(text),
        'next_start_char': end if end<len(text) else None}, ensure_ascii=False)
