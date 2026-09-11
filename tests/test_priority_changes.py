from pathlib import Path

from fastapi.testclient import TestClient

from app.audit import AuditRepository
from app.main import create_app
from app.models import (
    AnalysisRequest,
    AnalysisResult,
    Finding,
    ProviderAnalysis,
    SecurityInfo,
    Transcript,
    TranscriptSegment,
)
from app.providers import ProviderError, SchemaValidationError
from app.reporting import build_pdf_export
from app.service import AnalysisService


def valid_analysis(evidence: str = "Первое решение.") -> ProviderAnalysis:
    return ProviderAnalysis(
        summary="Готово",
        severity="low",
        findings=[
            Finding(
                title="Решение",
                evidence=evidence,
                recommendation="Исполнить",
                confidence_score=0.9,
            )
        ],
        payload={
            "meeting_title": "Кездесу ә ө ұ ғ қ і",
            "executive_summary": ["Итог 1", "Итог 2", "Итог 3"],
            "decisions": [],
            "open_questions": [],
            "action_items": [],
            "risks": [],
        },
    )


class RepairableGemini:
    name = "gemini"

    def __init__(self) -> None:
        self.analyze_calls = 0
        self.repair_calls = 0
        self.last_egress_bytes = 0
        self.repair_input = None

    def analyze(self, masked_text: str, language: str) -> ProviderAnalysis:
        del masked_text, language
        self.analyze_calls += 1
        self.last_egress_bytes = 100
        raise SchemaValidationError('{"broken": true}', "payload: field required")

    def repair(self, text, language, raw_response, validation_error) -> ProviderAnalysis:
        del text, language
        self.repair_calls += 1
        self.last_egress_bytes = 200
        self.repair_input = (raw_response, validation_error)
        return valid_analysis()


def test_schema_validation_gets_exactly_one_repair_request(settings) -> None:
    provider = RepairableGemini()
    service = AnalysisService(settings, AuditRepository(settings.database_path), provider)

    result = service.analyze(AnalysisRequest(text="Первое решение."))

    assert provider.analyze_calls == 1
    assert provider.repair_calls == 1
    assert provider.repair_input == ('{"broken": true}', "payload: field required")
    assert result.network_egress_bytes == 300
    assert result.timings_ms["schema_repair"] == 1
    assert service.quota_manager.snapshot(settings.gemini_model).rpm_used == 2


class LongTranscriber:
    name = "test-asr"
    model = "test"

    def transcribe(self, audio, filename, mime_type, language) -> Transcript:
        del audio, filename, mime_type, language
        return Transcript(
            text=(
                "[seg_0001 0.0-5.0] Speaker: Первое решение.\n"
                "[seg_0002 500.0-505.0] Speaker: Второе решение."
            ),
            language="ru",
            duration_seconds=650,
            segments=[
                TranscriptSegment(
                    id="seg_0001",
                    start_seconds=0,
                    end_seconds=5,
                    speaker="Speaker",
                    text="Первое решение.",
                ),
                TranscriptSegment(
                    id="seg_0002",
                    start_seconds=500,
                    end_seconds=505,
                    speaker="Speaker",
                    text="Второе решение.",
                ),
            ],
        )


class CountingAnalyzer:
    name = "local-test"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def analyze(self, masked_text: str, language: str) -> ProviderAnalysis:
        del language
        self.calls.append(masked_text)
        evidence = "Первое решение." if "Первое решение." in masked_text else "Второе решение."
        return valid_analysis(evidence)


def test_long_audio_uses_two_maps_and_one_reduce(settings) -> None:
    analyzer = CountingAnalyzer()
    service = AnalysisService(
        settings,
        AuditRepository(settings.database_path),
        provider=analyzer,
        transcription_provider=LongTranscriber(),
    )

    result = service.process_audio(
        audio=b"RIFF-long",
        filename="meeting.wav",
        mime_type="audio/wav",
        language="ru",
    )

    assert len(analyzer.calls) == 3
    assert analyzer.calls[-1].startswith("MAP-REDUCE FINAL PASS")
    assert "llm_map" in result.timings_ms
    assert "llm_reduce" in result.timings_ms


class SilentTranscriber:
    name = "silent-asr"
    model = "test"

    def transcribe(self, audio, filename, mime_type, language) -> Transcript:
        del audio, filename, mime_type, language
        raise ProviderError("empty_or_silent_audio")


def test_silent_audio_returns_clear_422_without_mock_protocol(settings) -> None:
    with TestClient(create_app(settings, transcription_provider=SilentTranscriber())) as client:
        response = client.post(
            "/api/v1/meetings/process",
            files={"file": ("silent.wav", b"RIFF-silence", "audio/wav")},
            data={"language": "ru"},
        )

    assert response.status_code == 422
    assert "не обнаружена речь" in response.json()["detail"]


def test_pdf_wraps_long_action_evidence_with_review_marker() -> None:
    evidence = (
        "Дословное основание поручения с казахскими глифами ә ө ұ ғ қ і и подробным "
        "контекстом встречи. "
        * 18
    ).strip()
    result = AnalysisResult(
        trace_id="pdf-long-evidence",
        status="ok",
        summary="Протокол готов.",
        severity="medium",
        findings=[],
        security=SecurityInfo(
            input_was_masked=False,
            masked_input="[MASKED INPUT NOT PERSISTED]",
            pii_detected=0,
            injection_detected=False,
        ),
        grounded=False,
        timings_ms={"total": 1.0},
        provider="mock",
        model="test-model",
        payload={
            "meeting_title": "Проверка длинного основания",
            "executive_summary": ["Первое.", "Второе.", "Третье."],
            "decisions": [],
            "open_questions": [],
            "action_items": [
                {
                    "owner": "Ответственный",
                    "task": "Подготовить подробный отчёт",
                    "due_date": None,
                    "priority": "high",
                    "evidence": evidence,
                    "verified_in_source": False,
                    "needs_human_review": True,
                }
            ],
            "risks": [],
        },
    )
    font_path = Path(__file__).parents[1] / "assets" / "fonts" / "DejaVuSans.ttf"

    pdf = build_pdf_export(result, font_path)

    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 20_000
