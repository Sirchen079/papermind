from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.ai_ops.claims import create_claim, delete_claim, list_claims
from app.api.deps import get_session

router = APIRouter()


class ClaimIn(BaseModel):
    text: str
    kind: str = "main"
    excerpt_id: int | None = None


def _run(fn, *args, **kwargs):  # noqa: ANN001
    try:
        return fn(*args, **kwargs)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/papers/{paper_id}/claims")
def get_claims(paper_id: int, session: Session = Depends(get_session)) -> list[dict]:
    return _run(list_claims, session, paper_id)


@router.post("/papers/{paper_id}/claims", status_code=201)
def add_claim(paper_id: int, body: ClaimIn, session: Session = Depends(get_session)) -> dict:
    return _run(create_claim, session, paper_id, body.model_dump())


@router.delete("/claims/{claim_id}", status_code=204)
def remove_claim(claim_id: int, session: Session = Depends(get_session)) -> None:
    _run(delete_claim, session, claim_id)
