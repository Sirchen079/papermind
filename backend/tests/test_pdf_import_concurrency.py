import asyncio
from io import BytesIO
import time

from fastapi import UploadFile

from app.api import papers_api


def test_pdf_analysis_does_not_block_other_requests(monkeypatch):
    """Slow synchronous provider/PDF work must yield the server event loop."""
    events = []

    def slow_persist(*args, **kwargs):
        time.sleep(0.2)
        events.append("analysis_finished")
        return object()

    monkeypatch.setattr(papers_api, "persist_fetched", slow_persist)
    monkeypatch.setattr(papers_api, "_analysis_ctx", lambda session: None)
    monkeypatch.setattr(papers_api, "_pdf_dir", lambda: "unused")
    monkeypatch.setattr(papers_api, "_public", lambda paper: {"id": 1})

    async def check():
        async def other_request():
            await asyncio.sleep(0.02)
            events.append("other_request")

        result, _ = await asyncio.gather(
            papers_api.ingest_pdf(UploadFile(BytesIO(b"pdf"), filename="test.pdf"), session=object()),
            other_request(),
        )
        assert result == {"id": 1}

    asyncio.run(check())
    assert events == ["other_request", "analysis_finished"]
