from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.api.deps import get_session
from app.knowledge.graph import concept_graph, paper_graph

router = APIRouter()


@router.get("/graph/{kind}")
def get_graph(
    kind: str,
    min_papers: int = Query(1, ge=1),
    session: Session = Depends(get_session),
) -> dict:
    if kind == "paper":
        return paper_graph(session)
    if kind == "concept":
        return concept_graph(session, min_papers=min_papers)
    raise HTTPException(400, "kind must be 'paper' or 'concept'")
