import json

import httpx

from app.audit import AuditRepository
from app.config import Settings
from app.models import AnalysisRequest
from app.providers import GeminiProvider, OllamaProvider
from app.service import AnalysisService


def test_gemini_model_is_read_from_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "gemini-stage-model")
    settings = Settings(_env_file=None, database_path=tmp_path / "audit.db")
    assert settings.gemini_model == "gemini-stage-model"


def test_live_mode_without_key_falls_back_without_network(settings) -> None:
    settings.mock_llm = False
    settings.gemini_api_key = ""
    service = AnalysisService(settings, AuditRepository(settings.database_path))

    result = service.analyze(AnalysisRequest(text="Безопасный входной текст"))

    assert result.status == "fallback"
    assert result.fallback_reason == "missing_api_key"
    assert result.provider == "mock"


def test_provider_error_classification() -> None:
    class RateLimitError(Exception):
        status_code = 429

    assert GeminiProvider._classify_error(RateLimitError()) == "rate_limited"
    assert GeminiProvider._classify_error(httpx.ReadTimeout("late")) == "timeout"
    assert (
        GeminiProvider._classify_error(httpx.ConnectError("offline"))
        == "network_error"
    )


def test_ollama_provider_uses_structured_schema_and_one_local_call(
    monkeypatch, settings
) -> None:
    settings.local_llm_model = "qwen-test:4b"
    calls = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            payload = {
                "summary": "Итоги встречи сформированы.",
                "severity": "low",
                "findings": [],
                "payload": {
                    "meeting_title": "Тест",
                    "executive_summary": ["Первое.", "Второе.", "Третье."],
                    "topics": [],
                    "decisions": [],
                    "open_questions": [],
                    "action_items": [],
                    "risks": [],
                    "detected_languages": ["ru"],
                },
            }
            return {"message": {"content": json.dumps(payload, ensure_ascii=False)}}

    def fake_post(url: str, *, json: dict, timeout: float) -> Response:
        calls.append((url, json, timeout))
        return Response()

    monkeypatch.setattr(httpx, "post", fake_post)

    result = OllamaProvider(settings).analyze("Тестовый транскрипт", "ru")

    assert result.payload["meeting_title"] == "Тест"
    assert len(calls) == 1
    assert calls[0][0] == "http://127.0.0.1:11434/api/chat"
    assert calls[0][1]["model"] == "qwen-test:4b"
    assert calls[0][1]["format"]["type"] == "object"
