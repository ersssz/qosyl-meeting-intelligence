import json
from types import SimpleNamespace

import httpx
from google import genai

import app.providers as providers
from app.audit import AuditRepository
from app.config import Settings
from app.models import AnalysisRequest
from app.providers import GeminiProvider, OllamaProvider
from app.service import AnalysisService


def test_gemini_model_is_read_from_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GEMINI_MODEL", "gemini-stage-model")
    settings = Settings(_env_file=None, database_path=tmp_path / "audit.db")
    assert settings.gemini_model == "gemini-stage-model"


def test_self_hosted_timeout_can_exceed_cloud_default(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        llm_timeout_seconds=180,
        database_path=tmp_path / "audit.db",
    )
    assert settings.llm_timeout_seconds == 180


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

    class DeadlineError(Exception):
        status_code = 504

    assert GeminiProvider._classify_error(RateLimitError()) == "rate_limited"
    assert GeminiProvider._classify_error(DeadlineError()) == "timeout"
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
    assert "$defs" not in calls[0][1]["format"]
    assert calls[0][1]["options"]["num_ctx"] == settings.local_llm_num_ctx
    assert calls[0][1]["options"]["num_predict"] == settings.local_llm_num_predict
    assert calls[0][1]["think"] is False
    assert calls[0][1]["keep_alive"] == 0


def test_gemini_provider_uses_interactions_structured_output(monkeypatch, settings) -> None:
    calls = []
    response_payload = {
        "summary": "Статус проекта обсуждён.",
        "severity": "low",
        "findings": [],
        "payload": {
            "meeting_title": "Статус проекта",
            "executive_summary": ["Первое.", "Второе.", "Третье."],
            "topics": [],
            "decisions": [],
            "open_questions": [],
            "action_items": [],
            "risks": [],
            "detected_languages": ["ru"],
        },
    }

    class Interactions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text=json.dumps(response_payload, ensure_ascii=False))

    class Client:
        def __init__(self, **kwargs) -> None:
            self.interactions = Interactions()

    monkeypatch.setattr(genai, "Client", Client)
    settings.gemini_api_key = "test-key"

    result = GeminiProvider(settings).analyze("Тестовый транскрипт", "ru")

    assert result.payload["meeting_title"] == "Статус проекта"
    assert calls[0]["model"] == settings.gemini_model
    assert calls[0]["response_format"]["mime_type"] == "application/json"
    schema = calls[0]["response_format"]["schema"]
    assert schema["type"] == "object"
    assert "$defs" not in schema
    owner = schema["properties"]["payload"]["properties"]["action_items"]["items"][
        "properties"
    ]["owner"]
    assert owner["type"] == ["string", "null"]
    assert calls[0]["store"] is False


def test_windows_cuda_wheel_directories_are_prepended_to_path(
    monkeypatch, tmp_path
) -> None:
    cublas = tmp_path / "nvidia" / "cublas"
    cudnn = tmp_path / "nvidia" / "cudnn"
    (cublas / "bin").mkdir(parents=True)
    (cudnn / "bin").mkdir(parents=True)
    packages = {
        "nvidia.cublas": SimpleNamespace(__path__=[str(cublas)]),
        "nvidia.cudnn": SimpleNamespace(__path__=[str(cudnn)]),
    }
    monkeypatch.setattr(providers, "import_module", packages.__getitem__)
    monkeypatch.setenv("PATH", "existing")

    providers._configure_windows_cuda_path("nt")

    entries = providers.os.environ["PATH"].split(providers.os.pathsep)
    assert entries == [str((cublas / "bin").resolve()), str((cudnn / "bin").resolve()), "existing"]
