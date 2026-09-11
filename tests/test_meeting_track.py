import json

from fastapi.testclient import TestClient

from app.audit import AuditRepository
from app.main import create_app
from app.models import (
    AnalysisRequest,
    Finding,
    ProviderAnalysis,
    Transcript,
    TranscriptSegment,
)
from app.providers import ProviderError
from app.service import AnalysisService


class MeetingTranscriber:
    name = "test-asr"
    model = "test-whisper"

    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, audio, filename, mime_type, language) -> Transcript:
        self.calls += 1
        assert audio == b"RIFF-fake-audio"
        assert filename == "meeting.wav"
        assert mime_type == "audio/wav"
        return Transcript(
            text=(
                "[seg_0001 0.0-4.0] Айдана: Решили запустить пилот в пятницу.\n"
                "[seg_0002 4.0-8.0] Тимур: Я подготовлю отчёт к четвергу."
            ),
            language="ru",
            duration_seconds=8,
            segments=[
                TranscriptSegment(
                    id="seg_0001",
                    start_seconds=0,
                    end_seconds=4,
                    speaker="Айдана",
                    text="Решили запустить пилот в пятницу.",
                ),
                TranscriptSegment(
                    id="seg_0002",
                    start_seconds=4,
                    end_seconds=8,
                    speaker="Тимур",
                    text="Я подготовлю отчёт к четвергу.",
                ),
            ],
        )


reti = "Решили запустить пилот в пятницу."


class MeetingAnalyzer:
    name = "test-llm"

    def analyze(self, masked_text: str, language: str) -> ProviderAnalysis:
        assert reti in masked_text
        assert language == "ru"
        return ProviderAnalysis(
            summary="Команда согласовала запуск пилота и подготовку отчёта.",
            severity="low",
            findings=[
                Finding(
                    title="Решение о пилоте",
                    evidence=reti,
                    recommendation="Контролировать запуск.",
                    confidence_score=0.95,
                )
            ],
            payload={
                "meeting_title": "Запуск пилота",
                "executive_summary": [
                    "Согласован пилот.",
                    "Назначен отчёт.",
                    "Сроки названы.",
                ],
                "topics": [{"title": "Пилот", "key_points": ["Запуск"]}],
                "decisions": [
                    {
                        "text": "Запустить пилот",
                        "evidence": reti,
                        "confidence_score": 0.9,
                    }
                ],
                "open_questions": [],
                "action_items": [
                    {
                        "owner": "Тимур",
                        "task": "Подготовить отчёт",
                        "due_date": "к четвергу",
                        "priority": "medium",
                        "evidence": "Я подготовлю отчёт к четвергу.",
                        "confidence_score": 0.9,
                    }
                ],
                "risks": [],
                "detected_languages": ["ru"],
            },
        )


def test_audio_to_grounded_protocol_and_exports(settings) -> None:
    transcriber = MeetingTranscriber()
    with TestClient(
        create_app(settings, MeetingAnalyzer(), transcription_provider=transcriber)
    ) as client:
        response = client.post(
            "/api/v1/meetings/process",
            files={"file": ("meeting.wav", b"RIFF-fake-audio", "audio/wav")},
            data={"language": "ru"},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["grounded"] is True
        assert result["transcription_provider"] == "test-asr"
        assert result["transcript"]["segments"][1]["speaker"] == "Тимур"
        assert result["payload"]["action_items"][0]["verified_in_source"] is True

        csv_export = client.get(f"/api/v1/export/{result['trace_id']}/csv")
        json_export = client.get(f"/api/v1/export/{result['trace_id']}/json")
        assert csv_export.status_code == 200
        assert "Тимур" in csv_export.text
        assert json_export.status_code == 200
        assert json_export.json()["protocol"]["meeting_title"] == "Запуск пилота"

        audit = client.get(f"/api/v1/audit/{result['trace_id']}").json()
        assert audit["result"]["transcript"] is None
        assert "RIFF-fake-audio" not in json.dumps(audit, ensure_ascii=False)
    assert transcriber.calls == 1


def test_unsupported_audio_is_rejected_before_provider(settings) -> None:
    transcriber = MeetingTranscriber()
    with TestClient(
        create_app(settings, MeetingAnalyzer(), transcription_provider=transcriber)
    ) as client:
        response = client.post(
            "/api/v1/meetings/process",
            files={"file": ("meeting.exe", b"payload", "application/octet-stream")},
        )
    assert response.status_code == 422
    assert transcriber.calls == 0


class AirgapSpy:
    name = "gemini"

    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, masked_text: str, language: str) -> ProviderAnalysis:
        self.calls += 1
        raise AssertionError("external provider must never run in airgap mode")


def test_airgap_blocks_external_provider_before_network(settings) -> None:
    settings.mock_llm = False
    settings.airgap_mode = True
    provider = AirgapSpy()
    service = AnalysisService(settings, AuditRepository(settings.database_path), provider)

    output = service.analyze(AnalysisRequest(text="Обычный транскрипт встречи"))

    assert output.status == "fallback"
    assert output.fallback_reason == "airgap_external_provider_blocked"
    assert provider.calls == 0


class FailingTranscriber:
    name = "gemini"

    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, audio, filename, mime_type, language) -> Transcript:
        self.calls += 1
        raise ProviderError("timeout")


def test_transcription_timeout_falls_back_once(settings) -> None:
    transcriber = FailingTranscriber()
    service = AnalysisService(
        settings,
        AuditRepository(settings.database_path),
        transcription_provider=transcriber,
    )

    result = service.process_audio(
        audio=b"RIFF-fake-audio",
        filename="meeting.wav",
        mime_type="audio/wav",
        language="ru",
    )

    assert transcriber.calls == 1
    assert result.status == "fallback"
    assert result.transcription_provider == "mock"
    assert result.fallback_reason == "transcription:timeout"
