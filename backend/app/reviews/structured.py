"""Structured (card/map) model calls: full output budget, failure counting.

The same asker serves the card pool's three worker threads and the map
pipeline, so the consecutive-error counter is lock-protected.
"""
import threading

from sqlmodel import Session, select
from app.models import Model
from app.providers import capabilities
from app.providers.output_budget import response_budget


class ModelUnavailable(Exception):
    """连续多次模型调用抛异常：多半是 key、额度或网络问题，应中止并提示研究者。"""


def model_window(session: Session, provider, model) -> int:
    """Configured context window, documented capability, or the 32768 default."""
    row = session.exec(select(Model).where(
        Model.provider_id == provider.id, Model.model_id == model)).first()
    if row is not None and row.context_window:
        return row.context_window
    return capabilities.known_context_window(provider, model) or 32768


class StructuredAsker:
    """One ask per structured task with a single generous budget and no tiers.

    Budget failures (empty or truncated output) are ordinary failures: no
    budget retry, callers' parsing and validation decide usability.
    """

    MAX_CONSECUTIVE_ERRORS = 3

    def __init__(self, client, provider, model, *, ref_id, window):
        self._client = client
        self._provider = provider
        self._model = model
        self._ref_id = ref_id
        self._window = window
        self._lock = threading.Lock()
        self._consecutive = 0

    def ask(self, system: str, user: str, text_tokens: int) -> str:
        max_tokens = response_budget(self._window, text_tokens, None, self._window)
        try:
            result = self._client.complete(
                self._provider, self._model,
                [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                request_kind='library_review', ref_id=self._ref_id, max_tokens=max_tokens,
                reasoning_effort=None)
        except Exception as exc:
            with self._lock:
                self._consecutive += 1
                count = self._consecutive
            if count >= self.MAX_CONSECUTIVE_ERRORS:
                raise ModelUnavailable(
                    f'模型连续 {count} 次调用失败（{type(exc).__name__}）') from exc
            raise
        with self._lock:
            self._consecutive = 0
        return result.content or ''
