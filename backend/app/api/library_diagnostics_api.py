from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import get_session
from app.library_diagnostics.service import library_diagnostics, repair_library_diagnostics

router = APIRouter()


class RepairBody(BaseModel):
    action: str


@router.get("/library/diagnostics")
def diagnostics(session: Session = Depends(get_session)) -> dict:
    return library_diagnostics(session)


@router.post("/library/diagnostics/repair")
def repair_diagnostics(body: RepairBody, session: Session = Depends(get_session)) -> dict:
    try:
        return repair_library_diagnostics(session, body.action)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
