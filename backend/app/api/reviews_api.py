from uuid import UUID
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from app.api.deps import get_session
from app.models.review import LibraryReview, ReviewPaper, ReviewRevision, ReviewSection
from app.reviews import service
from app.providers.client import EmptyResponseError

router=APIRouter(prefix='/reviews',tags=['reviews'])

class CreateBody(BaseModel):
    request_id: UUID
    question: str = Field(min_length=1,max_length=2000)
    paper_ids: list[int] = Field(default_factory=list,max_length=1000)
    whole_library: bool = False

class AddBody(BaseModel):
    paper_ids: list[int] = Field(min_length=1,max_length=1000)

class EditBody(BaseModel):
    content: str = Field(min_length=1,max_length=500000)
    expected_version: int = Field(ge=0)

class ParagraphBody(BaseModel):
    expected_version: int = Field(ge=0)
    block_id: str

class ProposalBody(ParagraphBody):
    instruction: str = Field(min_length=1,max_length=2000)

class ApplyBody(ParagraphBody):
    replacement: str = Field(max_length=100000)

class RestoreBody(BaseModel):
    expected_version: int = Field(ge=0)

def invoke(fn,*args):
    try:return fn(*args)
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    except EmptyResponseError as exc:raise HTTPException(502,'模型未返回正文，原文与手动草稿保留，可重试。') from exc
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc

@router.get('')
def list_reviews(session:Session=Depends(get_session)):
    return [r.model_dump(exclude={'content','outline_json','run_token'}) for r in session.exec(select(LibraryReview).order_by(LibraryReview.updated_at.desc()).limit(100))]

@router.post('',status_code=201)
def create(body:CreateBody,session:Session=Depends(get_session)):
    return invoke(service.create,session,str(body.request_id),body.question,body.paper_ids,body.whole_library)

@router.get('/{review_id}')
def get(review_id:str,session:Session=Depends(get_session)):
    return invoke(service.detail,session,review_id)

@router.post('/{review_id}/run',status_code=202)
def run(review_id:str,background:BackgroundTasks,session:Session=Depends(get_session)):
    token=invoke(service.start,session,review_id)
    background.add_task(service.run,session.get_bind(),review_id,token)
    return invoke(service.detail,session,review_id)

@router.post('/{review_id}/map/run',status_code=202)
def map_run(review_id:str,background:BackgroundTasks,session:Session=Depends(get_session)):
    from app.reviews import map as review_map
    token=invoke(review_map.start_map,session,review_id)
    background.add_task(review_map.run_map,session.get_bind(),review_id,token)
    return invoke(review_map.detail_map,session,review_id)

@router.post('/{review_id}/map/stop')
def map_stop(review_id:str,session:Session=Depends(get_session)):
    from app.reviews import map as review_map
    return invoke(review_map.stop_map,session,review_id)

@router.get('/{review_id}/map')
def map_get(review_id:str,session:Session=Depends(get_session)):
    from app.reviews import map as review_map
    return invoke(review_map.detail_map,session,review_id)

class MapThemesBody(BaseModel):
    themes: list[dict]
    expected_version: int = Field(ge=0)

@router.put('/{review_id}/map/themes')
def map_themes(review_id:str,body:MapThemesBody,session:Session=Depends(get_session)):
    from app.reviews import map as review_map
    return invoke(review_map.update_themes,session,review_id,body.themes,body.expected_version)

@router.post('/{review_id}/stop')
def stop(review_id:str,session:Session=Depends(get_session)):
    return invoke(service.stop,session,review_id)

@router.post('/{review_id}/papers')
def add(review_id:str,body:AddBody,session:Session=Depends(get_session)):
    return invoke(service.append_papers,session,review_id,body.paper_ids)

@router.post('/{review_id}/content')
def edit(review_id:str,body:EditBody,session:Session=Depends(get_session)):
    return invoke(service.save_content,session,review_id,body.content,body.expected_version)

@router.get('/{review_id}/cards')
def review_cards(review_id:str,session:Session=Depends(get_session)):
    invoke(service.get,session,review_id)
    import json
    from app.models.card import PaperCard
    entries=service.papers(session,review_id)
    rows={r.paper_id:r for r in session.exec(select(PaperCard).where(PaperCard.paper_id.in_([e.paper_id for e in entries])))}
    return [{'paper_id':e.paper_id,'title':e.title,
             'status':rows[e.paper_id].status if e.paper_id in rows else 'pending',
             'card':json.loads(rows[e.paper_id].card_json) if e.paper_id in rows else None,
             'warning':rows[e.paper_id].warning if e.paper_id in rows else '',
             'updated_at':rows[e.paper_id].updated_at if e.paper_id in rows else None} for e in entries]

@router.get('/{review_id}/papers/{paper_id}')
def source(review_id:str,paper_id:int,session:Session=Depends(get_session)):
    row=session.exec(select(ReviewPaper).where(ReviewPaper.review_id==review_id,ReviewPaper.paper_id==paper_id)).first()
    if row is None:raise HTTPException(404,'论文不在本次综述中')
    import json
    evidence=json.loads(row.evidence_json)
    seen={e['quote'] for e in evidence}
    for section in session.exec(select(ReviewSection).where(ReviewSection.review_id==review_id)):
        for e in json.loads(section.evidence_json):
            if e.get('paper_id')==paper_id and e['quote'] not in seen:
                evidence.append(e);seen.add(e['quote'])
    return {**row.model_dump(exclude={'fingerprint','evidence_json'}),'evidence':evidence}

@router.get('/{review_id}/paragraphs')
def paragraphs(review_id:str,session:Session=Depends(get_session)):
    from app.reviews import editing
    return invoke(editing.paragraphs,session,review_id)

@router.post('/{review_id}/paragraphs/propose')
def propose(review_id:str,body:ProposalBody,session:Session=Depends(get_session)):
    from app.reviews import editing
    try:return invoke(editing.propose,session,review_id,body.expected_version,body.block_id,body.instruction)
    except HTTPException:raise
    except Exception as exc:raise HTTPException(502,'模型修改未完成，原文与手动草稿保留，可重试。') from exc

@router.post('/{review_id}/paragraphs/apply')
def apply_paragraph(review_id:str,body:ApplyBody,session:Session=Depends(get_session)):
    from app.reviews import editing
    return invoke(editing.apply,session,review_id,body.expected_version,body.block_id,body.replacement)

@router.post('/{review_id}/revisions/{version}/restore')
def restore_revision(review_id:str,version:int,body:RestoreBody,session:Session=Depends(get_session)):
    from app.reviews import editing
    return invoke(editing.restore,session,review_id,version,body.expected_version)

@router.get('/{review_id}/revisions/{version}')
def revision(review_id:str,version:int,session:Session=Depends(get_session)):
    row=session.exec(select(ReviewRevision).where(ReviewRevision.review_id==review_id,ReviewRevision.version==version)).first()
    if row is None:raise HTTPException(404,'历史版本不存在')
    return row.model_dump()


@router.get('/{review_id}/revisions/{version}/changes')
def revision_changes(review_id:str,version:int,session:Session=Depends(get_session)):
    from app.reviews import changes
    return invoke(changes.read,session,review_id,version)

@router.get('/{review_id}/export')
def export(review_id:str,kind:str='markdown',session:Session=Depends(get_session)):
    row=invoke(service.get,session,review_id)
    if kind=='coverage':return PlainTextResponse(service.coverage(session,review_id),media_type='application/x-ndjson')
    return PlainTextResponse(row.content,media_type='text/markdown')
