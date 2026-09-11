from pathlib import Path

import requests
from streamlit.testing.v1 import AppTest

from app.task_profile import PRESETS


class FakeResponse:
    def __init__(self, payload, content: bytes = b"") -> None:
        self.payload = payload
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


def test_streamlit_page_loads_with_four_presets(monkeypatch) -> None:
    def fake_get(url: str, timeout: float):
        if url.endswith("/health"):
            return FakeResponse({"status": "ok", "mode": "mock", "model": "test-model"})
        if url.endswith("/api/v1/quota"):
            return FakeResponse(
                {
                    "rpm_limit": 15,
                    "rpm_remaining": 15,
                    "rpd_limit": 500,
                    "rpd_remaining": 500,
                    "circuit_open": False,
                }
            )
        if url.endswith("/api/v1/presets"):
            return FakeResponse(PRESETS)
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(requests, "get", fake_get)
    app_path = Path(__file__).parents[1] / "streamlit_app.py"

    page = AppTest.from_file(str(app_path)).run(timeout=10)

    assert not page.exception
    assert len(page.button) == 5
    assert page.button[-1].label == "Analyze meeting"


def test_streamlit_renders_task_specific_payload(monkeypatch) -> None:
    result = {
        "trace_id": "trace-ui-test",
        "status": "ok",
        "summary": "Проверка завершена",
        "severity": "medium",
        "findings": [],
        "security": {
            "masked_input": "Безопасный тестовый текст",
            "pii_detected": 0,
            "pii_counts": {},
            "injection_detected": False,
            "injection_reasons": [],
        },
        "grounded": True,
        "timings_ms": {"total": 12.5},
        "provider": "mock",
        "model": "test-model",
        "fallback_reason": None,
        "payload": {
            "category": "security",
            "risk_score": 55,
            "recommended_actions": ["Проверить источник", "Назначить владельца"],
            "routing": {"team": "SOC", "priority": 2},
        },
    }

    def fake_get(url: str, timeout: float):
        if url.endswith("/health"):
            return FakeResponse({"status": "ok", "mode": "mock", "model": "test-model"})
        if url.endswith("/api/v1/quota"):
            return FakeResponse(
                {
                    "rpm_limit": 15,
                    "rpm_remaining": 15,
                    "rpd_limit": 500,
                    "rpd_remaining": 500,
                    "circuit_open": False,
                }
            )
        if url.endswith("/api/v1/presets"):
            return FakeResponse(PRESETS)
        if "/api/v1/report/" in url:
            return FakeResponse({}, content=b"# report")
        if "/api/v1/export/" in url:
            return FakeResponse({}, content=b"export")
        raise AssertionError(f"Unexpected URL: {url}")

    def fake_post(url: str, json: dict, timeout: float):
        assert url.endswith("/api/v1/analyze")
        assert json["text"]
        return FakeResponse(result)

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)
    app_path = Path(__file__).parents[1] / "streamlit_app.py"

    page = AppTest.from_file(str(app_path)).run(timeout=10)
    page.button[-1].click().run(timeout=10)

    assert not page.exception
    metrics = {metric.label: metric.value for metric in page.metric}
    assert metrics["Category"] == "security"
    assert metrics["Risk Score"] == "55"
    assert any("Проверить источник" in element.value for element in page.markdown)
    assert any(element.label == "Raw task payload (JSON)" for element in page.expander)


def test_streamlit_action_items_show_evidence_and_review(monkeypatch) -> None:
    evidence = "Тимур, подготовь отчёт к четвергу."
    result = {
        "trace_id": "trace-action-evidence",
        "status": "ok",
        "summary": "Поручение извлечено.",
        "severity": "medium",
        "findings": [],
        "security": {
            "masked_input": "[MASKED INPUT NOT PERSISTED]",
            "pii_detected": 0,
            "pii_counts": {},
            "injection_detected": False,
            "injection_reasons": [],
        },
        "grounded": False,
        "timings_ms": {"total": 12.5},
        "provider": "mock",
        "model": "test-model",
        "fallback_reason": None,
        "payload": {
            "meeting_title": "Поручения",
            "executive_summary": ["Первое.", "Второе.", "Третье."],
            "decisions": [],
            "open_questions": [],
            "action_items": [
                {
                    "owner": "Тимур",
                    "task": "Подготовить отчёт",
                    "due_date": "к четвергу",
                    "priority": "high",
                    "evidence": evidence,
                    "verified_in_source": False,
                    "needs_human_review": True,
                }
            ],
            "risks": [],
        },
    }

    def fake_get(url: str, timeout: float):
        if url.endswith("/health"):
            return FakeResponse({"status": "ok", "mode": "mock", "model": "test-model"})
        if url.endswith("/api/v1/quota"):
            return FakeResponse(
                {
                    "rpm_limit": 15,
                    "rpm_remaining": 15,
                    "rpd_limit": 500,
                    "rpd_remaining": 500,
                    "circuit_open": False,
                }
            )
        if url.endswith("/api/v1/presets"):
            return FakeResponse(PRESETS)
        if "/api/v1/report/" in url or "/api/v1/export/" in url:
            return FakeResponse({}, content=b"export")
        raise AssertionError(f"Unexpected URL: {url}")

    def fake_post(url: str, json: dict, timeout: float):
        assert url.endswith("/api/v1/analyze")
        return FakeResponse(result)

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)
    app_path = Path(__file__).parents[1] / "streamlit_app.py"

    page = AppTest.from_file(str(app_path)).run(timeout=10)
    page.button[-1].click().run(timeout=10)

    assert not page.exception
    actions = page.dataframe[0].value
    assert actions.loc[0, "Основание"] == evidence
    assert bool(actions.loc[0, "Needs human review"]) is True
    assert bool(actions.loc[0, "Verified"]) is False


def test_streamlit_shows_clear_audio_error_detail(monkeypatch) -> None:
    detail = "Аудиофайл повреждён или контейнер не поддерживается."

    class ErrorResponse(FakeResponse):
        text = '{"detail":"invalid audio"}'

        def raise_for_status(self) -> None:
            raise requests.HTTPError("422", response=self)

    def fake_get(url: str, timeout: float):
        if url.endswith("/health"):
            return FakeResponse({"status": "ok", "mode": "mock", "model": "test-model"})
        if url.endswith("/api/v1/quota"):
            return FakeResponse(
                {
                    "rpm_limit": 15,
                    "rpm_remaining": 15,
                    "rpd_limit": 500,
                    "rpd_remaining": 500,
                    "circuit_open": False,
                }
            )
        if url.endswith("/api/v1/presets"):
            return FakeResponse(PRESETS)
        raise AssertionError(f"Unexpected URL: {url}")

    def fake_post(url: str, json: dict, timeout: float):
        return ErrorResponse({"detail": detail})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)
    app_path = Path(__file__).parents[1] / "streamlit_app.py"

    page = AppTest.from_file(str(app_path)).run(timeout=10)
    page.button[-1].click().run(timeout=10)

    assert not page.exception
    assert any(detail in element.value for element in page.error)


def test_ui_compose_environment_does_not_include_dotenv_or_gemini_key() -> None:
    compose = (Path(__file__).parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
    ui_service = compose.split("\n  ui:\n", maxsplit=1)[1].split("\nvolumes:\n", maxsplit=1)[0]

    assert "env_file" not in ui_service
    assert "GEMINI_API_KEY" not in ui_service
    assert "API_URL: http://api:8000" in ui_service
