from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Language = Literal["auto", "ru", "kk", "en"]
Severity = Literal["low", "medium", "high", "critical"]
AnalysisStatus = Literal["ok", "blocked", "fallback"]


class AnalysisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    language: Language = "auto"
    preset_id: str | None = None

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must contain non-whitespace characters")
        return value


class TranscriptSegment(BaseModel):
    id: str = Field(pattern=r"^seg_\d{4}$")
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    speaker: str = Field(default="Speaker 1", min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=5_000)

    @field_validator("end_seconds")
    @classmethod
    def end_must_follow_start(cls, value: float, info) -> float:
        start = info.data.get("start_seconds")
        if start is not None and value < start:
            raise ValueError("end_seconds must be greater than or equal to start_seconds")
        return value


class Transcript(BaseModel):
    text: str = Field(min_length=1, max_length=250_000)
    language: str = Field(default="unknown", min_length=1, max_length=20)
    duration_seconds: float = Field(default=0, ge=0)
    segments: list[TranscriptSegment] = Field(min_length=1, max_length=10_000)


class Finding(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1, max_length=2_000)
    recommendation: str = Field(min_length=1, max_length=2_000)
    confidence_score: float = Field(ge=0, le=1)
    verified_in_source: bool = False
    needs_human_review: bool = True


class ProviderAnalysis(BaseModel):
    summary: str = Field(min_length=1, max_length=4_000)
    severity: Severity
    findings: list[Finding] = Field(default_factory=list, max_length=25)
    payload: dict[str, Any] = Field(default_factory=dict)


class SecurityInfo(BaseModel):
    input_was_masked: bool
    masked_input: str
    pii_detected: int = Field(ge=0)
    pii_counts: dict[str, int] = Field(default_factory=dict)
    injection_detected: bool
    injection_reasons: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    status: AnalysisStatus
    summary: str
    severity: Severity
    findings: list[Finding]
    security: SecurityInfo
    grounded: bool
    timings_ms: dict[str, float]
    network_egress_bytes: int = Field(default=0, ge=0)
    provider: str
    model: str
    transcription_provider: str | None = None
    transcription_model: str | None = None
    fallback_reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    transcript: Transcript | None = None


class PresetPublic(BaseModel):
    id: str
    title: str
    description: str
    language: Language
    text: str


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    mode: Literal["mock", "live"]
    model: str
    analysis_provider: str = "mock"
    transcription_provider: str = "mock"
    airgap_mode: bool = False
