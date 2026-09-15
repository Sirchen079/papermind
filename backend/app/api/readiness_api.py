from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_session
from app.readiness.service import get_readiness

router = APIRouter()


@router.get("/readiness")
def readiness(session: Session = Depends(get_session)) -> dict:
    return get_readiness(session)
