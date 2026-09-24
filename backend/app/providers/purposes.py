"""Explicit per-project models for document transcription and retrieval ranking."""
from fastapi import HTTPException
from sqlmodel import Session
from app.models import Model, Provider, Setting
from app.providers.client import ProviderClient
from app.providers.shared import resolve


def configured_id(session, purpose):
    row = session.get(Setting, f'{purpose}_model_config_id')
    try:
        return int(row.value) if row and row.value else None
    except (TypeError, ValueError):
        return None


def is_reranker(session, model):
    return model.role_default == 'rerank' or model.id == configured_id(session, 'rerank')


def rerank_mode(session):
    row = session.get(Setting, 'rerank_mode')
    if row is None or not row.value:
        return 'dedicated' if configured_id(session, 'rerank') else 'off'
    return row.value if row.value in {'off', 'dedicated', 'llm'} else 'off'


def purpose_model(session, purpose, config_id=None):
    mid = config_id if config_id is not None else configured_id(session, purpose)
    if mid is None:
        if purpose == 'rerank_llm':
            from app.providers.selection import pick_llm
            return pick_llm(session, 'chat')
        return None
    model = session.get(Model, mid)
    provider = session.get(Provider, model.provider_id) if model else None
    if not model or not provider or provider.is_deleted or not provider.enabled:
        raise HTTPException(422, '所选模型不可用，请到设置重新选择。')
    if purpose == 'ocr':
        if model.role_default == 'embedding' or is_reranker(session, model) or model.supports_images is False:
            raise HTTPException(422, 'OCR 需要支持图片输入的文本模型。')
    elif purpose == 'rerank':
        if model.role_default in {'chat', 'embedding'} or mid in {configured_id(session, 'ocr'), configured_id(session, 'translation'), configured_id(session, 'rerank_llm')}:
            raise HTTPException(422, '重排序需要专用模型，请先解除该模型的文本、向量、翻译或 OCR 用途。')
    elif purpose == 'rerank_llm':
        if model.role_default == 'embedding' or is_reranker(session, model):
            raise HTTPException(422, '大模型重排序需要文本模型，可与对话、翻译和 OCR 共用。')
    try:
        actual, crypto = resolve(provider)
    except LookupError as exc:
        raise HTTPException(422, '模型连接不可用，请检查设置。') from exc
    if not actual.enabled:
        raise HTTPException(422, '模型连接已停用。')
    if purpose == 'rerank' and (actual.type == 'anthropic' or not actual.base_url):
        raise HTTPException(422, '重排序需要配置提供 /rerank 接口的连接地址。')
    engine = session.get_bind()
    return ProviderClient(lambda: Session(engine), crypto), actual, model.model_id
