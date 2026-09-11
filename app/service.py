from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from app.audit import AuditRepository
from app.config import Settings
from app.models import AnalysisRequest, AnalysisResult, ProviderAnalysis, SecurityInfo, Transcript
from app.providers import (
    AnalysisProvider,
    FasterWhisperProvider,
    GeminiProvider,
    GeminiTranscriptionProvider,
    MockProvider,
    MockTranscriptionProvider,
    OllamaProvider,
    ProviderError,
    SchemaValidationError,
    TranscriptionProvider,
)
from app.quota import LocalQuotaBlocked, QuotaManager
from app.security import (
    detect_prompt_injection,
    mask_pii,
    verify_findings,
    verify_payload_evidence,
)
from app.task_profile import PRESETS, blocked_result

T = TypeVar("T")
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a"}
ALLOWED_AUDIO_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/x-m4a",
}
LONG_MEETING_SECONDS = 10 * 60
ANALYSIS_CHUNK_SECONDS = 8 * 60


class AnalysisUnavailable(RuntimeError):
    def __init__(self, trace_id: str, reason: str) -> None:
        super().__init__(reason)
        self.trace_id = trace_id
        self.reason = reason


class AnalysisService:
    def __init__(
        self,
        settings: Settings,
        audit_repository: AuditRepository,
        provider: AnalysisProvider | None = None,
        quota_manager: QuotaManager | None = None,
        transcription_provider: TranscriptionProvider | None = None,
    ) -> None:
        self.settings = settings
        self.audit_repository = audit_repository
        self.provider_override = provider
        self.transcription_provider_override = transcription_provider
        self.quota_manager = quota_manager or QuotaManager(settings.database_path, settings)

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1_000, 3)

    @staticmethod
    def _append_reason(current: str | None, stage: str, reason: str) -> str:
        addition = f"{stage}:{reason}"
        return f"{current}; {addition}" if current else addition

    def _select_provider(self) -> AnalysisProvider:
        if self.provider_override is not None:
            return self.provider_override
        if self.settings.mock_llm or self.settings.analysis_provider == "mock":
            return MockProvider()
        if self.settings.analysis_provider == "ollama":
            return OllamaProvider(self.settings)
        return GeminiProvider(self.settings)

    def _select_transcription_provider(self) -> TranscriptionProvider:
        if self.transcription_provider_override is not None:
            return self.transcription_provider_override
        if self.settings.mock_llm or self.settings.transcription_provider == "mock":
            return MockTranscriptionProvider()
        if self.settings.transcription_provider == "faster-whisper":
            return FasterWhisperProvider(self.settings)
        return GeminiTranscriptionProvider(self.settings)

    def _provider_model(self, provider: object) -> str:
        name = getattr(provider, "name", "unknown")
        if name == "gemini":
            return self.settings.gemini_model
        if name == "ollama":
            return self.settings.local_llm_model
        if name == "faster-whisper":
            return self.settings.local_asr_model
        return str(getattr(provider, "model", "deterministic-mock"))

    def _call_provider(self, provider: object, callback: Callable[[], T]) -> T:
        name = getattr(provider, "name", "unknown")
        if self.settings.airgap_mode and name == "gemini":
            raise ProviderError("airgap_external_provider_blocked")

        quota_reserved = False
        try:
            if name == "gemini":
                self.quota_manager.reserve(self.settings.gemini_model)
                quota_reserved = True
            result = callback()
            if quota_reserved:
                self.quota_manager.record_success(self.settings.gemini_model)
            return result
        except (ProviderError, LocalQuotaBlocked) as error:
            if quota_reserved and isinstance(error, ProviderError):
                self.quota_manager.record_failure(self.settings.gemini_model, error.reason)
            raise

    def _validate_request(self, request: AnalysisRequest) -> None:
        if len(request.text) > self.settings.input_max_chars:
            raise ValueError(f"text exceeds {self.settings.input_max_chars} characters")
        if request.preset_id is not None and request.preset_id not in {
            preset["id"] for preset in PRESETS
        }:
            raise ValueError("unknown preset_id")

    def _validate_audio(self, audio: bytes, filename: str, mime_type: str) -> None:
        if not audio:
            raise ValueError("audio file is empty")
        if len(audio) > self.settings.audio_max_bytes:
            raise ValueError(f"audio exceeds {self.settings.audio_max_bytes} bytes")
        if Path(filename).suffix.casefold() not in ALLOWED_AUDIO_EXTENSIONS:
            raise ValueError("supported audio formats: MP3, WAV, M4A")
        if mime_type and mime_type.casefold() not in ALLOWED_AUDIO_TYPES:
            raise ValueError("unsupported audio content type")

    def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        self._validate_request(request)
        return self._analyze_text(
            request=request,
            input_sha256=hashlib.sha256(request.text.encode("utf-8")).hexdigest(),
            trace_id=str(uuid.uuid4()),
            created_at=datetime.now(UTC).isoformat(),
            timings={},
        )

    def process_audio(
        self,
        *,
        audio: bytes,
        filename: str,
        mime_type: str,
        language: str,
        asr_model: str | None = None,
    ) -> AnalysisResult:
        total_started = time.perf_counter()
        trace_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat()
        input_sha256 = hashlib.sha256(audio).hexdigest()
        self._validate_audio(audio, filename, mime_type)
        timings: dict[str, float] = {}

        transcriber = self._select_transcription_provider()
        requested_transcription_model = (
            asr_model
            if getattr(transcriber, "name", "") == "faster-whisper" and asr_model
            else self._provider_model(transcriber)
        )
        network_egress_bytes = 0
        fallback_reason: str | None = None
        status = "ok"
        stage_started = time.perf_counter()
        try:
            def transcribe() -> Transcript:
                if getattr(transcriber, "name", "") == "faster-whisper":
                    return transcriber.transcribe(
                        audio, filename, mime_type, language, asr_model
                    )
                return transcriber.transcribe(audio, filename, mime_type, language)

            transcript = self._call_provider(
                transcriber,
                transcribe,
            )
        except (ProviderError, LocalQuotaBlocked) as error:
            network_egress_bytes += int(getattr(transcriber, "last_egress_bytes", 0))
            if isinstance(error, ProviderError) and error.reason == "empty_or_silent_audio":
                raise ValueError(
                    "В записи не обнаружена речь: проверьте файл и уровень громкости."
                ) from error
            if not self.settings.allow_mock_fallback:
                timings["transcription"] = self._elapsed_ms(stage_started)
                timings["total"] = self._elapsed_ms(total_started)
                self.audit_repository.save_failure(
                    trace_id=trace_id,
                    created_at=created_at,
                    input_sha256=input_sha256,
                    masked_excerpt="[AUDIO NOT PERSISTED]",
                    provider=getattr(transcriber, "name", "unknown"),
                    model=requested_transcription_model,
                    reason=f"transcription:{error.reason}",
                    pii_counts={},
                    injection_detected=False,
                    injection_reasons=[],
                    timings_ms=timings,
                )
                raise AnalysisUnavailable(
                    trace_id, f"transcription:{error.reason}"
                ) from error
            fallback_reason = self._append_reason(
                None, "transcription", error.reason
            )
            status = "fallback"
            transcriber = MockTranscriptionProvider()
            transcript = transcriber.transcribe(audio, filename, mime_type, language, None)
        else:
            network_egress_bytes += int(getattr(transcriber, "last_egress_bytes", 0))
        timings["transcription"] = self._elapsed_ms(stage_started)

        request = AnalysisRequest(text=transcript.text, language=language)
        return self._analyze_text(
            request=request,
            input_sha256=input_sha256,
            trace_id=trace_id,
            created_at=created_at,
            timings=timings,
            total_started=total_started,
            initial_status=status,
            initial_fallback_reason=fallback_reason,
            transcript=transcript,
            transcription_provider=getattr(transcriber, "name", "unknown"),
            transcription_model=requested_transcription_model,
            network_egress_bytes=network_egress_bytes,
        )

    @staticmethod
    def _transcript_chunks(transcript: Transcript) -> list[str]:
        buckets: dict[int, list[str]] = {}
        for segment in transcript.segments:
            bucket = int(segment.start_seconds // ANALYSIS_CHUNK_SECONDS)
            buckets.setdefault(bucket, []).append(
                f"[{segment.id} {segment.start_seconds:.1f}-{segment.end_seconds:.1f}] "
                f"{segment.speaker}: {segment.text}"
            )
        return ["\n".join(buckets[index]) for index in sorted(buckets)]

    def _analyze_once(
        self, provider: AnalysisProvider, text: str, language: str
    ) -> tuple[ProviderAnalysis, int, bool]:
        """Call once, with one additional request only for Pydantic schema repair."""

        try:
            analysis = self._call_provider(provider, lambda: provider.analyze(text, language))
        except SchemaValidationError as error:
            egress = int(getattr(provider, "last_egress_bytes", 0))
            repair = getattr(provider, "repair", None)
            if repair is None:
                raise
            raw_response = error.raw_response
            validation_error = error.validation_error
            analysis = self._call_provider(
                provider,
                lambda: repair(
                    text, language, raw_response, validation_error
                ),
            )
            egress += int(getattr(provider, "last_egress_bytes", 0))
            return analysis, egress, True
        return analysis, int(getattr(provider, "last_egress_bytes", 0)), False

    def _run_analysis(
        self,
        provider: AnalysisProvider,
        masked_text: str,
        language: str,
        transcript: Transcript | None,
        timings: dict[str, float],
    ) -> tuple[ProviderAnalysis, int]:
        if transcript is None or transcript.duration_seconds <= LONG_MEETING_SECONDS:
            analysis, egress, repaired = self._analyze_once(provider, masked_text, language)
            if repaired:
                timings["schema_repair"] = 1.0
            return analysis, egress

        map_started = time.perf_counter()
        map_results: list[ProviderAnalysis] = []
        egress = 0
        repair_count = 0
        for chunk in self._transcript_chunks(transcript):
            masked_chunk = mask_pii(chunk).masked_text
            mapped, outbound, repaired = self._analyze_once(provider, masked_chunk, language)
            map_results.append(mapped)
            egress += outbound
            repair_count += int(repaired)
        timings["llm_map"] = self._elapsed_ms(map_started)

        reduce_input = (
            "MAP-REDUCE FINAL PASS. Merge the chunk analyses below into one protocol. "
            "Keep evidence quotes verbatim; do not invent facts.\n\n"
            + "\n\n".join(
                f"Chunk {index}:\n{item.model_dump_json()}"
                for index, item in enumerate(map_results, start=1)
            )
        )
        reduce_started = time.perf_counter()
        analysis, outbound, repaired = self._analyze_once(
            provider, reduce_input, language
        )
        timings["llm_reduce"] = self._elapsed_ms(reduce_started)
        egress += outbound
        repair_count += int(repaired)
        if repair_count:
            timings["schema_repair"] = float(repair_count)
        return analysis, egress

    def _analyze_text(
        self,
        *,
        request: AnalysisRequest,
        input_sha256: str,
        trace_id: str,
        created_at: str,
        timings: dict[str, float],
        total_started: float | None = None,
        initial_status: str = "ok",
        initial_fallback_reason: str | None = None,
        transcript: Transcript | None = None,
        transcription_provider: str | None = None,
        transcription_model: str | None = None,
        network_egress_bytes: int = 0,
    ) -> AnalysisResult:
        total_started = total_started or time.perf_counter()

        stage_started = time.perf_counter()
        self._validate_request(request)
        timings["validation"] = self._elapsed_ms(stage_started)

        stage_started = time.perf_counter()
        masking = mask_pii(request.text)
        timings["pii_masking"] = self._elapsed_ms(stage_started)

        stage_started = time.perf_counter()
        injection = detect_prompt_injection(masking.masked_text)
        timings["injection_guard"] = self._elapsed_ms(stage_started)

        security = SecurityInfo(
            input_was_masked=masking.total > 0,
            masked_input=masking.masked_text,
            pii_detected=masking.total,
            pii_counts=masking.counts,
            injection_detected=injection.detected,
            injection_reasons=injection.reasons,
        )

        if injection.detected:
            analysis = blocked_result()
            timings["llm"] = 0.0
            timings["grounding"] = 0.0
            timings["total"] = self._elapsed_ms(total_started)
            result = AnalysisResult(
                trace_id=trace_id,
                status="blocked",
                summary=analysis.summary,
                severity=analysis.severity,
                findings=analysis.findings,
                security=security,
                grounded=False,
                timings_ms=timings,
                network_egress_bytes=network_egress_bytes,
                provider="none",
                model=self.settings.gemini_model,
                transcription_provider=transcription_provider,
                transcription_model=transcription_model,
                fallback_reason=initial_fallback_reason,
                payload=analysis.payload,
                transcript=transcript,
            )
            self._save(created_at, input_sha256, result)
            return result

        provider = self._select_provider()
        requested_analysis_model = self._provider_model(provider)
        fallback_reason = initial_fallback_reason
        status = initial_status
        stage_started = time.perf_counter()
        try:
            analysis, analysis_egress = self._run_analysis(
                provider,
                masking.masked_text,
                request.language,
                transcript,
                timings,
            )
            network_egress_bytes += analysis_egress
        except (ProviderError, LocalQuotaBlocked) as error:
            network_egress_bytes += int(getattr(provider, "last_egress_bytes", 0))
            timings["llm"] = self._elapsed_ms(stage_started)
            if not self.settings.allow_mock_fallback:
                timings["total"] = self._elapsed_ms(total_started)
                self.audit_repository.save_failure(
                    trace_id=trace_id,
                    created_at=created_at,
                    input_sha256=input_sha256,
                    masked_excerpt=masking.masked_text[:500],
                    provider=getattr(provider, "name", "unknown"),
                    model=requested_analysis_model,
                    reason=(
                        f"analysis:{error.reason}" if transcript is not None else error.reason
                    ),
                    pii_counts=masking.counts,
                    injection_detected=False,
                    injection_reasons=[],
                    timings_ms=timings,
                )
                unavailable_reason = (
                    f"analysis:{error.reason}" if transcript is not None else error.reason
                )
                raise AnalysisUnavailable(trace_id, unavailable_reason) from error
            fallback_reason = (
                error.reason
                if transcript is None and fallback_reason is None
                else self._append_reason(fallback_reason, "analysis", error.reason)
            )
            status = "fallback"
            provider = MockProvider()
            analysis = provider.analyze(masking.masked_text, request.language)
        else:
            timings["llm"] = self._elapsed_ms(stage_started)

        stage_started = time.perf_counter()
        findings, findings_grounded = verify_findings(
            analysis.findings, masking.masked_text
        )
        payload, payload_grounded = verify_payload_evidence(
            analysis.payload, masking.masked_text
        )
        timings["grounding"] = self._elapsed_ms(stage_started)
        timings["total"] = self._elapsed_ms(total_started)

        result = AnalysisResult(
            trace_id=trace_id,
            status=status,
            summary=analysis.summary,
            severity=analysis.severity,
            findings=findings,
            security=security,
            grounded=findings_grounded and payload_grounded,
            timings_ms=timings,
            network_egress_bytes=network_egress_bytes,
            provider=getattr(provider, "name", "unknown"),
            model=requested_analysis_model,
            transcription_provider=transcription_provider,
            transcription_model=transcription_model,
            fallback_reason=fallback_reason,
            payload=payload,
            transcript=transcript,
        )
        self._save(created_at, input_sha256, result)
        return result

    def _save(self, created_at: str, input_sha256: str, result: AnalysisResult) -> None:
        self.audit_repository.save_result(
            created_at=created_at,
            input_sha256=input_sha256,
            masked_excerpt=result.security.masked_input[:500],
            result=result,
        )
