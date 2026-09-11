from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile

from app.audit import AuditRepository
from app.config import Settings, get_settings
from app.models import (
    AnalysisRequest,
    AnalysisResult,
    HealthResponse,
    Language,
    PresetPublic,
)
from app.providers import AnalysisProvider, TranscriptionProvider
from app.reporting import (
    build_csv_export,
    build_json_export,
    build_markdown_report,
    build_pdf_export,
)
from app.service import AnalysisService, AnalysisUnavailable
from app.task_profile import TASK_NAME, public_presets


def create_app(
    settings: Settings | None = None,
    provider: AnalysisProvider | None = None,
    transcription_provider: TranscriptionProvider | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    audit_repository = AuditRepository(resolved_settings.database_path)
    service = AnalysisService(
        resolved_settings,
        audit_repository,
        provider,
        transcription_provider=transcription_provider,
    )

    application = FastAPI(
        title=TASK_NAME,
        version="0.1.0",
        description="Secure, auditable AI analysis starter for team two_digits.",
    )
    application.state.settings = resolved_settings
    application.state.audit_repository = audit_repository
    application.state.analysis_service = service

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        analysis_provider = (
            "mock" if resolved_settings.mock_llm else resolved_settings.analysis_provider
        )
        model = (
            resolved_settings.local_llm_model
            if analysis_provider == "ollama"
            else resolved_settings.gemini_model
        )
        return HealthResponse(
            mode="mock" if resolved_settings.mock_llm else "live",
            model=model,
            analysis_provider=analysis_provider,
            transcription_provider=(
                "mock"
                if resolved_settings.mock_llm
                else resolved_settings.transcription_provider
            ),
            airgap_mode=resolved_settings.airgap_mode,
        )

    @application.get("/api/v1/presets", response_model=list[PresetPublic])
    def presets() -> list[PresetPublic]:
        return [PresetPublic.model_validate(item) for item in public_presets()]

    @application.get("/api/v1/quota")
    def quota() -> dict:
        return service.quota_manager.snapshot(
            resolved_settings.gemini_model
        ).as_dict()

    @application.post("/api/v1/analyze", response_model=AnalysisResult)
    def analyze(request: AnalysisRequest) -> AnalysisResult:
        try:
            return service.analyze(request)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except AnalysisUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail={"trace_id": error.trace_id, "reason": error.reason},
            ) from error

    @application.post("/api/v1/meetings/process", response_model=AnalysisResult)
    async def process_meeting(
        file: Annotated[UploadFile, File()],
        language: Annotated[Language, Form()] = "auto",
        asr_model: Annotated[str, Form(pattern="^(small|medium)$")] = "small",
    ) -> AnalysisResult:
        try:
            audio = await file.read(resolved_settings.audio_max_bytes + 1)
            return service.process_audio(
                audio=audio,
                filename=file.filename or "meeting.wav",
                mime_type=file.content_type or "",
                language=language,
                asr_model=asr_model,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except AnalysisUnavailable as error:
            raise HTTPException(
                status_code=503,
                detail={"trace_id": error.trace_id, "reason": error.reason},
            ) from error

    @application.get("/api/v1/audit/{trace_id}")
    def audit(trace_id: str) -> dict:
        event = audit_repository.get(trace_id)
        if event is None:
            raise HTTPException(status_code=404, detail="trace_id not found")
        return event

    @application.get("/api/v1/report/{trace_id}")
    def report(trace_id: str) -> Response:
        event = audit_repository.get(trace_id)
        if event is None or event.get("result") is None:
            raise HTTPException(status_code=404, detail="report not found")
        result = AnalysisResult.model_validate(event["result"])
        markdown = build_markdown_report(result)
        return Response(
            content=markdown,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="report-{trace_id}.md"'
            },
        )

    @application.get("/api/v1/export/{trace_id}/json")
    def export_json(trace_id: str) -> Response:
        result = _stored_result(trace_id)
        return Response(
            content=build_json_export(result),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="meeting-{trace_id}.json"'},
        )

    @application.get("/api/v1/export/{trace_id}/csv")
    def export_csv(trace_id: str) -> Response:
        result = _stored_result(trace_id)
        return Response(
            content=build_csv_export(result),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="actions-{trace_id}.csv"'},
        )

    @application.get("/api/v1/export/{trace_id}/pdf")
    def export_pdf(trace_id: str) -> Response:
        result = _stored_result(trace_id)
        font_path = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "DejaVuSans.ttf"
        return Response(
            content=build_pdf_export(result, font_path),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="meeting-{trace_id}.pdf"'},
        )

    def _stored_result(trace_id: str) -> AnalysisResult:
        event = audit_repository.get(trace_id)
        if event is None or event.get("result") is None:
            raise HTTPException(status_code=404, detail="export not found")
        return AnalysisResult.model_validate(event["result"])

    return application


app = create_app()
