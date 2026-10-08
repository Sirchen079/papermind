"""Complete upstream resources, loaded progressively rather than as one giant prompt."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import yaml
from sqlmodel import select
from app.paths import backend_dir
from app.models import Skill

ADAPTER = '''PaperMind 技能运行约定（优先于技能的默认操作习惯）：
遵循用户本次任务和语言；中文请求默认中文，不自动转为英文或强制投稿格式。
已有授权直接执行，不增加逐阶段批准、固定问卷或严格格式审核。缺项局部说明并完成可做内容。
保留证据边界但不堆叠免责声明。不得把工具缺失、某种格式不合格或无法全面核验当作拒绝整篇输出的理由。
以当前实际提供的工具为准。用 read_builtin_skill_resource 读取技能引用文件；相对路径从对应技能目录解析。
脚本、模板和资源已随应用提供，但读取脚本不代表已经执行；未提供的外部服务或执行器不得假装调用成功。
Nature 精读卡的 PDF 来源准备使用 prepare_paper_card_sources，草稿检查使用 audit_paper_card；这两个工具实际执行对应原始脚本，返回执行记录与文件。read_skill_run 可回读。审计只定位局部问题，不替代科学核查，不阻断其他回答。
综述可依据选定论文形成研究判断，不编造原始实验。普通文字综述无需强制插图、LaTeX、投稿声明或外部检索。
正文写成有论证的自然段，写作计划、核对记录与草稿分开。信息不完整时继续生成有用草稿。'''


def root():
    return backend_dir() / 'builtin_skills'


@lru_cache(maxsize=4)
def _catalog(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def catalog():
    return _catalog(str(root() / 'catalog.json'))


def public_catalog():
    return [{**{k:v for k,v in f.items() if k != 'files'}, 'file_count':len(f['files'])}
            for f in catalog()['families']]


def entry(skill_id):
    for family in catalog()['families']:
        for skill in family['skills']:
            if skill['id'] == skill_id:
                return skill
    raise LookupError('内置技能不存在')


def resource_path(skill_id, relative='SKILL.md'):
    skill=entry(skill_id)
    path=(root()/skill['entry']).parent/relative
    path=path.resolve()
    family_root=(root()/skill_id.split('/')[0]).resolve()
    if not path.is_relative_to(family_root) or not path.is_file():
        raise LookupError('技能资源不存在')
    return path


def resources(skill_id):
    skill=entry(skill_id);family=next(f for f in catalog()['families'] if f['id']==skill_id.split('/')[0])
    # Include shared files so a router's ../nature-shared links are also browsable.
    base=(root()/skill['entry']).parent
    import os
    return [os.path.relpath(root()/family['id']/p,base).replace('\\','/') for p in family['files']]


def read_resource(skill_id, relative='SKILL.md', start=0, limit=16000):
    path=resource_path(skill_id,relative)
    from urllib.parse import urlencode
    url='/api/builtin-skills/resource/download?'+urlencode({'skill_id':skill_id,'path':relative})
    try:text=path.read_text(encoding='utf-8-sig')
    except UnicodeError:return {'path':relative,'binary':True,'download_url':url,'bytes':path.stat().st_size}
    start=max(0,start);end=min(len(text),start+max(1,min(limit,50000)))
    return {'path':relative,'text':text[start:end],'total_chars':len(text),
            'start_char':start,'end_char':end,
            'text_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'excerpt_sha256':hashlib.sha256(text[start:end].encode()).hexdigest(),
            'next_start':end if end<len(text) else None,'download_url':url}


def load(skill_id, axes=None, extra=(), body_override=None):
    """Return the actual router + required core + chosen fragments with provenance."""
    skill=entry(skill_id);selected=['SKILL.md'];manifest={}
    manifest_path=resource_path(skill_id).parent/'manifest.yaml'
    if manifest_path.exists():
        manifest=yaml.safe_load(manifest_path.read_text(encoding='utf-8')) or {}
        selected+=['manifest.yaml']+manifest.get('always_load',[])
        for axis,value in (axes or {}).items():
            values=manifest.get('axes',{}).get(axis,{}).get('values',{})
            for item in value if isinstance(value,list) else [value]:
                if item in values:selected.append(values[item])
    selected+=list(extra)
    blocks=[];used=[]
    for relative in dict.fromkeys(selected):
        content=resource_path(skill_id,relative).read_text(encoding='utf-8-sig')
        if relative=='SKILL.md' and body_override is not None:content=body_override
        used.append({'path':relative,'sha256':hashlib.sha256(content.encode()).hexdigest()})
        blocks.append(f'[{skill_id} / {relative}]\n{content}')
    text='\n\n'.join(blocks)+'\n\n'+ADAPTER
    return {'id':skill_id,'version':skill['version'],'text':text,'resources':used,
            'fingerprint':hashlib.sha256(text.encode()).hexdigest()}


def sync(session):
    count=0
    for family in catalog()['families']:
        for e in family['skills']:
            uri='builtin://'+e['id']
            existing=session.exec(select(Skill).where(Skill.file_path==uri)).first()
            if existing:continue  # Preserve user edits and enabled state.
            name=e['slug']
            if session.exec(select(Skill).where(Skill.name==name)).first():name=e['id']
            session.add(Skill(name=name,description=e['description'],source='builtin',
                type='instruction',trigger='manual',file_path=uri,
                body=resource_path(e['id']).read_text(encoding='utf-8-sig')))
            count+=1
    session.commit()
    return count


def chat_prompt(skill):
    if not (skill.file_path or '').startswith('builtin://'):
        return skill.body or ''
    return load(skill.file_path.removeprefix('builtin://'),body_override=skill.body)['text']


def discovery_prompt(session):
    """Expose enabled skill metadata; the agent loads relevant resources on demand."""
    available = []
    for skill in session.exec(select(Skill).where(Skill.enabled == True).order_by(Skill.id)):
        if skill.type != 'instruction' or not (skill.file_path or '').startswith('builtin://'):
            continue
        available.append({'id': skill.file_path.removeprefix('builtin://'),
                          'description': skill.description})
    if not available:
        return ''
    return ('[可用内置技能目录：仅描述，尚未加载技能正文]\n'
            '开始任务时先查看现成技能是否适用。按用户意图选择，使用 load_builtin_skill '
            '加载匹配技能的实际内容后执行，不以宣布使用代替加载。'
            '根据 manifest 按需选择 axes，并用 read_builtin_skill_resource 读取所需引用资源；'
            '已在当前上下文加载的内容直接复用，不重复加载所有技能。'
            '目录本身不改变用户任务：普通研究笔记不自动升级为投稿或正式审稿；'
            '没有适用技能时正常完成任务。遵循用户要求，不增加逐阶段审批。\n'
            + json.dumps(available, ensure_ascii=False))


def list_builtin_skills(session,query=''):
    q=query.lower()
    return json.dumps([{'id':s['id'],'description':s['description'],'version':s['version']}
        for f in catalog()['families'] for s in f['skills']
        if not q or q in (s['id']+' '+s['description']).lower()],ensure_ascii=False)


def load_builtin_skill(session,skill_id,axes=None):
    result=load(skill_id,axes)
    return json.dumps(result,ensure_ascii=False)


def read_builtin_skill_resource(session,skill_id,path='SKILL.md',start_char=0,max_chars=16000):
    return json.dumps(read_resource(skill_id,path,start_char,max_chars),ensure_ascii=False)
