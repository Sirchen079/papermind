from pathlib import Path

import pytest

from app.skills.research_evidence import research_skill_prompt


def test_all_research_entrypoints_load_both_skills_and_references():
    from app.api.chat_api import CHAT_SYSTEM_PROMPT
    from app.research.service import SYSTEM_PROMPT
    from app.wiki.service import SYSTEM
    bundle = research_skill_prompt()
    for prompt in (CHAT_SYSTEM_PROMPT, SYSTEM_PROMPT, SYSTEM):
        assert bundle in prompt
        assert "next_start_char" in prompt
        assert "开发集与测试集" in prompt
        assert "局部片段缺少指标" in prompt


def test_missing_bundle_dependency_is_not_silently_ignored(tmp_path):
    with pytest.raises(FileNotFoundError):
        research_skill_prompt(tmp_path)


def test_frozen_bundle_loads_from_runtime_resources(monkeypatch, tmp_path):
    import shutil
    import sys
    from app import paths
    original = paths.backend_dir() / "research_skills"
    expected = research_skill_prompt()
    shutil.copytree(original, tmp_path / "backend/research_skills")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.delenv("PAPERMIND_BACKEND_DIR", raising=False)
    assert research_skill_prompt() == expected


def test_skill_changes_invalidate_research_cache():
    from app.research.cache import cache_key
    from app.models import Provider
    provider = Provider(id=1, name="test", type="openai_chat")
    assert cache_key(provider, "test-model", "same evidence", "old") != cache_key(
        provider, "test-model", "same evidence", "old" + research_skill_prompt())
