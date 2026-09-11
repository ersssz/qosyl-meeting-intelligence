from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import BaseModel, Field

from app.config import Settings
from app.models import ProviderAnalysis, Transcript, TranscriptSegment
from app.task_profile import (
    SYSTEM_PROMPT,
    TRANSCRIPTION_PROMPT,
    TaskAnalysis,
    mock_result,
)


class ProviderError(RuntimeError):
    def __init__(self, reason: str, message: str | None = None) -> None:
        super().__init__(message or reason)
        self.reason = reason


class AnalysisProvider(Protocol):
    name: str

    def analyze(self, masked_text: str, language: str) -> ProviderAnalysis: ...


class TranscriptionProvider(Protocol):
    name: str

    def transcribe(
        self,
        audio: bytes,
        filename: str,
        mime_type: str,
        language: str,
    ) -> Transcript: ...


class _GeminiTranscriptSegment(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    speaker: str = "Speaker"
    text: str = Field(min_length=1)


class _GeminiTranscript(BaseModel):
    language: str = "unknown"
    duration_seconds: float = Field(default=0, ge=0)
    segments: list[_GeminiTranscriptSegment] = Field(min_length=1)


def _normalize_transcript(
    segments: list[dict], language: str, duration_seconds: float = 0
) -> Transcript:
    normalized = [
        TranscriptSegment(
            id=f"seg_{index:04d}",
            start_seconds=max(float(segment.get("start_seconds", 0)), 0),
            end_seconds=max(
                float(segment.get("end_seconds", segment.get("start_seconds", 0))),
                float(segment.get("start_seconds", 0)),
            ),
            speaker=str(segment.get("speaker") or "Speaker"),
            text=str(segment["text"]).strip(),
        )
        for index, segment in enumerate(segments, start=1)
        if str(segment.get("text", "")).strip()
    ]
    if not normalized:
        raise ProviderError("empty_transcript")
    text = "\n".join(
        f"[{item.id} {item.start_seconds:.1f}-{item.end_seconds:.1f}] "
        f"{item.speaker}: {item.text}"
        for item in normalized
    )
    return Transcript(
        text=text,
        language=language or "unknown",
        duration_seconds=max(duration_seconds, normalized[-1].end_seconds),
        segments=normalized,
    )


class MockProvider:
    name = "mock"

    def analyze(self, masked_text: str, language: str) -> ProviderAnalysis:
        result = mock_result(masked_text)
        return ProviderAnalysis(
            summary=result.summary,
            severity=result.severity,
            findings=result.findings,
            payload=result.payload.model_dump(mode="json"),
        )


class MockTranscriptionProvider:
    name = "mock"
    model = "deterministic-meeting"

    def transcribe(
        self,
        audio: bytes,
        filename: str,
        mime_type: str,
        language: str,
    ) -> Transcript:
        del audio, filename, mime_type
        return _normalize_transcript(
            [
                {
                    "start_seconds": 0,
                    "end_seconds": 7.5,
                    "speaker": "Айдана",
                    "text": "Решили выпустить бета-версию 15 октября.",
                },
                {
                    "start_seconds": 7.5,
                    "end_seconds": 14,
                    "speaker": "Айдана",
                    "text": "Тимур, подготовь сборку к пятнице.",
                },
                {
                    "start_seconds": 14,
                    "end_seconds": 18,
                    "speaker": "Тимур",
                    "text": "Принято, сделаю.",
                },
            ],
            "ru" if language == "auto" else language,
            18,
        )


class GeminiProvider:
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _status_code(error: Exception) -> int | None:
        for candidate in (
            getattr(error, "status_code", None),
            getattr(error, "code", None),
            getattr(getattr(error, "response", None), "status_code", None),
        ):
            try:
                if candidate is not None:
                    return int(candidate)
            except (TypeError, ValueError):
                continue
        return None

    @classmethod
    def _classify_error(cls, error: Exception) -> str:
        if cls._status_code(error) == 429 or "429" in str(error):
            return "rate_limited"
        if isinstance(error, (TimeoutError, httpx.TimeoutException)):
            return "timeout"
        if isinstance(error, (ConnectionError, OSError, httpx.NetworkError)):
            return "network_error"
        return "provider_error"

    def analyze(self, masked_text: str, language: str) -> ProviderAnalysis:
        if not self.settings.gemini_api_key:
            raise ProviderError("missing_api_key")

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(
                api_key=self.settings.gemini_api_key,
                http_options=types.HttpOptions(
                    timeout=int(self.settings.llm_timeout_seconds * 1_000)
                ),
            )
            response = client.models.generate_content(
                model=self.settings.gemini_model,
                contents=f"Language hint: {language}\n\nUntrusted input to analyze:\n{masked_text}",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=TaskAnalysis,
                    temperature=0.1,
                ),
            )
            parsed = response.parsed
            if isinstance(parsed, TaskAnalysis):
                result = parsed
            elif parsed is None:
                result = TaskAnalysis.model_validate_json(response.text)
            else:
                result = TaskAnalysis.model_validate(parsed)
            return ProviderAnalysis(
                summary=result.summary,
                severity=result.severity,
                findings=result.findings,
                payload=result.payload.model_dump(mode="json"),
            )
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(self._classify_error(error)) from error


class GeminiTranscriptionProvider(GeminiProvider):
    name = "gemini"

    def transcribe(
        self,
        audio: bytes,
        filename: str,
        mime_type: str,
        language: str,
    ) -> Transcript:
        del filename
        if not self.settings.gemini_api_key:
            raise ProviderError("missing_api_key")
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(
                api_key=self.settings.gemini_api_key,
                http_options=types.HttpOptions(
                    timeout=int(self.settings.llm_timeout_seconds * 1_000)
                ),
            )
            response = client.models.generate_content(
                model=self.settings.gemini_model,
                contents=[
                    f"Language hint: {language}\n{TRANSCRIPTION_PROMPT}",
                    types.Part.from_bytes(data=audio, mime_type=mime_type),
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_GeminiTranscript,
                    temperature=0,
                ),
            )
            parsed = response.parsed
            if isinstance(parsed, _GeminiTranscript):
                result = parsed
            elif parsed is None:
                result = _GeminiTranscript.model_validate_json(response.text)
            else:
                result = _GeminiTranscript.model_validate(parsed)
            return _normalize_transcript(
                [segment.model_dump() for segment in result.segments],
                result.language,
                result.duration_seconds,
            )
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(self._classify_error(error)) from error


class FasterWhisperProvider:
    name = "faster-whisper"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.local_asr_model

    def transcribe(
        self,
        audio: bytes,
        filename: str,
        mime_type: str,
        language: str,
    ) -> Transcript:
        del mime_type
        temporary_path: Path | None = None
        try:
            import os
            import tempfile

            from faster_whisper import WhisperModel

            suffix = Path(filename).suffix or ".wav"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as stream:
                stream.write(audio)
                temporary_path = Path(stream.name)

            device = self.settings.local_asr_device
            if device == "auto":
                device = "cuda"
            compute_type = self.settings.local_asr_compute_type
            if device == "cpu" and compute_type == "int8_float16":
                compute_type = "int8"
            model = WhisperModel(self.model, device=device, compute_type=compute_type)
            detected_language = None if language == "auto" else language
            raw_segments, info = model.transcribe(
                str(temporary_path),
                language=detected_language,
                beam_size=1,
                vad_filter=True,
                word_timestamps=False,
            )
            segments = [
                {
                    "start_seconds": segment.start,
                    "end_seconds": segment.end,
                    "speaker": "Speaker",
                    "text": segment.text,
                }
                for segment in raw_segments
            ]
            return _normalize_transcript(
                segments,
                getattr(info, "language", detected_language or "unknown"),
                getattr(info, "duration", 0),
            )
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(GeminiProvider._classify_error(error)) from error
        finally:
            if temporary_path is not None:
                with suppress(OSError):
                    os.unlink(temporary_path)


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def analyze(self, masked_text: str, language: str) -> ProviderAnalysis:
        request = {
            "model": self.settings.local_llm_model,
            "stream": False,
            "format": TaskAnalysis.model_json_schema(),
            "options": {"temperature": 0.1},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Language hint: {language}\n\nTranscript:\n{masked_text}",
                },
            ],
        }
        try:
            response = httpx.post(
                f"{self.settings.local_llm_base_url.rstrip('/')}/api/chat",
                json=request,
                timeout=self.settings.llm_timeout_seconds,
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
            result = TaskAnalysis.model_validate_json(content)
            return ProviderAnalysis(
                summary=result.summary,
                severity=result.severity,
                findings=result.findings,
                payload=result.payload.model_dump(mode="json"),
            )
        except Exception as error:
            raise ProviderError(GeminiProvider._classify_error(error)) from error
