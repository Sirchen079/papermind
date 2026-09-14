from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.api.deps import get_session
from app.knowledge.graph import PAPER_EDGE_TYPES, claims_graph, concept_graph, paper_graph
from app.models.claim import CLAIM_RELATION_TYPES

router = APIRouter()


@router.get("/graph/{kind}")
def get_graph(
    kind: str,
    min_papers: int = Query(1, ge=1),
    edge_types: str | None = Query(None, description="comma-separated: concept,citation"),
    types: str | None = Query(None, description="comma-separated: supports,contradicts,extends"),
    session: Session = Depends(get_session),
) -> dict:
    if kind == "paper":
        requested = None
        if edge_types is not None:
            requested = [part.strip() for part in edge_types.split(",") if part.strip()]
            invalid = set(requested) - PAPER_EDGE_TYPES
            if invalid or not requested:
                raise HTTPException(400, f"edge_types must be a subset of {sorted(PAPER_EDGE_TYPES)}")
        return paper_graph(session, edge_types=requested)
    if kind == "concept":
        return concept_graph(session, min_papers=min_papers)
    if kind == "claims":
        requested = None
        if types is not None:
            requested = [part.strip() for part in types.split(",") if part.strip()]
            invalid = set(requested) - set(CLAIM_RELATION_TYPES)
            if invalid or not requested:
                raise HTTPException(400, f"types must be a subset of {sorted(CLAIM_RELATION_TYPES)}")
        return claims_graph(session, types=requested)
    raise HTTPException(400, "kind must be 'paper', 'concept' or 'claims'")
