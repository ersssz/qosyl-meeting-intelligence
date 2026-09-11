from pathlib import Path

import pytest

from app.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """All tests are hermetic and can never make a real Gemini request."""

    return Settings(
        _env_file=None,
        mock_llm=True,
        allow_mock_fallback=True,
        gemini_model="test-model",
        gemini_api_key="",
        database_path=tmp_path / "audit.db",
    )

