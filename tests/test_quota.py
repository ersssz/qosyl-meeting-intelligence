from datetime import UTC, datetime

import pytest

from app.audit import AuditRepository
from app.models import AnalysisRequest, Finding, ProviderAnalysis
from app.quota import LocalQuotaBlocked, QuotaManager, limits_for_model
from app.service import AnalysisService


class MutableClock:
    def __init__(self, timestamp: float) -> None:
        self.value = timestamp

    def __call__(self) -> float:
        return self.value


class CountingGemini:
    name = "gemini"

    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, masked_text: str, language: str) -> ProviderAnalysis:
        self.calls += 1
        return ProviderAnalysis(
            summary="ok",
            severity="low",
            findings=[
                Finding(
                    title="source",
                    evidence=masked_text,
                    recommendation="continue",
                    confidence_score=0.9,
                )
            ],
        )


def test_known_model_limits_follow_quota_plan(settings) -> None:
    assert limits_for_model("gemini-3.5-flash-lite", settings).rpm == 15
    assert limits_for_model("gemini-3.5-flash-lite", settings).rpd == 500
    assert limits_for_model("gemini-3.8-flash", settings).rpm == 5
    assert limits_for_model("gemini-3.8-flash", settings).rpd == 20


def test_rpm_limit_blocks_before_network(settings) -> None:
    settings.gemini_model = "gemini-3.8-flash"
    clock = MutableClock(datetime(2026, 9, 11, 12, tzinfo=UTC).timestamp())
    manager = QuotaManager(settings.database_path, settings, clock)

    for _ in range(5):
        manager.reserve(settings.gemini_model)
    with pytest.raises(LocalQuotaBlocked, match="local_rpm_limit"):
        manager.reserve(settings.gemini_model)

    snapshot = manager.snapshot(settings.gemini_model)
    assert snapshot.rpm_used == 5
    assert snapshot.rpm_limit == 5


def test_circuit_breaker_prevents_followup_request(settings) -> None:
    clock = MutableClock(datetime(2026, 9, 11, 12, tzinfo=UTC).timestamp())
    manager = QuotaManager(settings.database_path, settings, clock)
    manager.record_failure(settings.gemini_model, "rate_limited")

    with pytest.raises(LocalQuotaBlocked, match="circuit_open_rate_limited"):
        manager.reserve(settings.gemini_model)

    clock.value += settings.quota_rate_limit_cooldown_seconds + 1
    manager.reserve(settings.gemini_model)


def test_service_falls_back_when_local_budget_is_exhausted(settings) -> None:
    settings.mock_llm = False
    settings.gemini_rpm_limit = 1
    provider = CountingGemini()
    repository = AuditRepository(settings.database_path)
    service = AnalysisService(settings, repository, provider)

    first = service.analyze(AnalysisRequest(text="first"))
    second = service.analyze(AnalysisRequest(text="second"))

    assert first.status == "ok"
    assert second.status == "fallback"
    assert second.fallback_reason == "local_rpm_limit"
    assert provider.calls == 1

