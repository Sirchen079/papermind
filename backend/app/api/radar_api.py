from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.api.deps import get_session
from app.radar import service as radar_service

router = APIRouter()


class SubscriptionIn(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    query_type: str  # keyword | category | author
    query_value: str
    max_results: int = 20
    lookback_days: int = 7
    enabled: bool = True


class SubscriptionPatchIn(BaseModel):
    model_config = {"extra": "forbid"}

    name: str | None = None
    query_type: str | None = None
    query_value: str | None = None
    max_results: int | None = None
    lookback_days: int | None = None
    enabled: bool | None = None


@router.get("/subscriptions")
def api_list_subscriptions(session: Session = Depends(get_session)) -> list[dict]:
    return radar_service.list_subscriptions(session)


@router.post("/subscriptions", status_code=201)
def api_create_subscription(body: SubscriptionIn, session: Session = Depends(get_session)) -> dict:
    try:
        return radar_service.create_subscription(session, body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.patch("/subscriptions/{subscription_id}")
def api_patch_subscription(
    subscription_id: int,
    body: SubscriptionPatchIn,
    session: Session = Depends(get_session),
) -> dict:
    try:
        return radar_service.patch_subscription(
            session, subscription_id, body.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.delete("/subscriptions/{subscription_id}", status_code=204)
def api_delete_subscription(subscription_id: int, session: Session = Depends(get_session)) -> None:
    try:
        radar_service.delete_subscription(session, subscription_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/radar/status")
def api_radar_status(session: Session = Depends(get_session)) -> dict:
    return radar_service.radar_status(session)


@router.post("/radar/refresh")
def api_radar_refresh(session: Session = Depends(get_session)) -> dict:
    """Force-refresh all enabled subscriptions now (设置页「立即刷新」)."""
    return radar_service.refresh_all(session, force=True)
