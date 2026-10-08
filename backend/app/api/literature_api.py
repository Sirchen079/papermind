from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import get_session
from app.literature import survey

router = APIRouter()


class SurveyIn(BaseModel):
    model_config = {"extra": "forbid"}

    query: str
    years: int = 2
    max_results: int = 20
    screen: bool = True


class ImportIn(BaseModel):
    model_config = {"extra": "forbid"}

    candidate_ids: list[int]


@router.post('/literature/surveys', status_code=201)
def create_survey(body: SurveyIn, session: Session = Depends(get_session)) -> dict:
    years = min(max(body.years, 1), 10)
    max_results = min(max(body.max_results, 5), 50)
    return survey.start_survey(session, body.query, years, max_results, body.screen)


@router.get('/literature/surveys')
def list_surveys(session: Session = Depends(get_session)) -> dict:
    return {'items': survey.list_surveys(session)}


@router.get('/literature/surveys/{survey_id}')
def survey_detail(survey_id: int, session: Session = Depends(get_session)) -> dict:
    return survey.detail(session, survey_id)


@router.post('/literature/surveys/{survey_id}/import', status_code=202)
def import_selected(survey_id: int, body: ImportIn, session: Session = Depends(get_session)) -> dict:
    return survey.start_import(session, survey_id, body.candidate_ids)


@router.delete('/literature/surveys/{survey_id}', status_code=204)
def remove_survey(survey_id: int, session: Session = Depends(get_session)) -> None:
    survey.delete_survey(session, survey_id)
