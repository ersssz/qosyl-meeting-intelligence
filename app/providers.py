from __future__ import annotations

import gc
import os
from contextlib import suppress
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

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


class SchemaValidationError(ProviderError):
    """A model response that can be repaired exactly once by the caller."""

    def __init__(self, raw_response: str, validation_error: str) -> None:
        super().__init__("schema_validation")
        self.raw_response = raw_response
        self.validation_error = validation_error


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
        asr_model: str | None = None,
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
        raise ProviderError("empty_or_silent_audio")
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
        asr_model: str | None = None,
    ) -> Transcript:
        del audio, filename, mime_type, asr_model
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
        self.last_egress_bytes = 0

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

        contents = f"Language hint: {language}\n\nUntrusted input to analyze:\n{masked_text}"
        self.last_egress_bytes = len(contents.encode("utf-8"))
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
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=TaskAnalysis,
                    temperature=0.1,
                ),
            )
            return self._parse_response(response)
        except ValidationError as error:
            raw = str(getattr(locals().get("response"), "text", ""))
            raise SchemaValidationError(raw, str(error)) from error
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(self._classify_error(error)) from error

    @staticmethod
    def _parse_response(response: object) -> ProviderAnalysis:
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, TaskAnalysis):
            result = parsed
        elif parsed is None:
            result = TaskAnalysis.model_validate_json(str(getattr(response, "text", "")))
        else:
            result = TaskAnalysis.model_validate(parsed)
        return ProviderAnalysis(
            summary=result.summary,
            severity=result.severity,
            findings=result.findings,
            payload=result.payload.model_dump(mode="json"),
        )

    def repair(
        self,
        masked_text: str,
        language: str,
        raw_response: str,
        validation_error: str,
    ) -> ProviderAnalysis:
        """Make the sole schema-repair request; callers must never loop this method."""

        if not self.settings.gemini_api_key:
            raise ProviderError("missing_api_key")
        repair_payload = (
            f"Language hint: {language}\n\nOriginal transcript:\n{masked_text}\n\n"
            f"Your invalid JSON response:\n{raw_response}\n\n"
            f"Pydantic validation error:\n{validation_error}\n\n"
            "Repair only the JSON shape. Preserve facts and evidence; invent nothing."
        )
        self.last_egress_bytes = len(repair_payload.encode("utf-8"))
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
                contents=repair_payload,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=TaskAnalysis,
                    temperature=0,
                ),
            )
            return self._parse_response(response)
        except ProviderError:
            raise
        except ValidationError as error:
            raise ProviderError("schema_validation_failed") from error
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
        asr_model: str | None = None,
    ) -> Transcript:
        del filename, asr_model
        if not self.settings.gemini_api_key:
            raise ProviderError("missing_api_key")
        prompt = f"Language hint: {language}\n{TRANSCRIPTION_PROMPT}"
        self.last_egress_bytes = len(audio) + len(prompt.encode("utf-8"))
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
                    prompt,
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
        asr_model: str | None = None,
    ) -> Transcript:
        del mime_type
        temporary_path: Path | None = None
        model = None
        try:
            import tempfile

            from faster_whisper import WhisperModel
            from faster_whisper.audio import decode_audio

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
            model_name = asr_model or self.model
            model = WhisperModel(model_name, device=device, compute_type=compute_type)
            detected_language = None if language == "auto" else language
            sampling_rate = 16_000
            waveform = decode_audio(str(temporary_path), sampling_rate=sampling_rate)
            duration_seconds = len(waveform) / sampling_rate
            chunk_seconds = 8 * 60
            chunk_samples = chunk_seconds * sampling_rate
            audio_chunks = (
                [
                    (offset, waveform[offset : offset + chunk_samples])
                    for offset in range(0, len(waveform), chunk_samples)
                ]
                if duration_seconds > 10 * 60
                else [(0, waveform)]
            )
            segments: list[dict] = []
            detected_result_language = detected_language or "unknown"
            for offset_samples, chunk in audio_chunks:
                raw_segments, info = model.transcribe(
                    chunk,
                    language=detected_language,
                    beam_size=self.settings.local_asr_beam_size,
                    vad_filter=True,
                    word_timestamps=False,
                )
                offset_seconds = offset_samples / sampling_rate
                detected_result_language = getattr(
                    info, "language", detected_result_language
                )
                segments.extend(
                    {
                        "start_seconds": segment.start + offset_seconds,
                        "end_seconds": segment.end + offset_seconds,
                        "speaker": "Speaker",
                        "text": segment.text,
                    }
                    for segment in raw_segments
                )
            return _normalize_transcript(
                segments,
                detected_result_language,
                duration_seconds,
            )
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(GeminiProvider._classify_error(error)) from error
        finally:
            if temporary_path is not None:
                with suppress(OSError):
                    os.unlink(temporary_path)
            if self.settings.sequential_model_loading:
                del model
                gc.collect()
                with suppress(ImportError, RuntimeError):
                    import torch

                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _request(self, messages: list[dict[str, str]]) -> str:
        request = {
            "model": self.settings.local_llm_model,
            "stream": False,
            "think": False,
            "keep_alive": 0 if self.settings.sequential_model_loading else "5m",
            "format": TaskAnalysis.model_json_schema(),
            "options": {"temperature": 0.1},
            "messages": messages,
        }
        response = httpx.post(
            f"{self.settings.local_llm_base_url.rstrip('/')}/api/chat",
            json=request,
            timeout=self.settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        return str(response.json()["message"]["content"])

    @staticmethod
    def _to_analysis(content: str) -> ProviderAnalysis:
        result = TaskAnalysis.model_validate_json(content)
        return ProviderAnalysis(
            summary=result.summary,
            severity=result.severity,
            findings=result.findings,
            payload=result.payload.model_dump(mode="json"),
        )

    def analyze(self, masked_text: str, language: str) -> ProviderAnalysis:
        try:
            content = self._request(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Language hint: {language}\n\nTranscript:\n{masked_text}",
                    },
                ]
            )
            return self._to_analysis(content)
        except ValidationError as error:
            raise SchemaValidationError(content, str(error)) from error
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(GeminiProvider._classify_error(error)) from error

    def repair(
        self,
        masked_text: str,
        language: str,
        raw_response: str,
        validation_error: str,
    ) -> ProviderAnalysis:
        try:
            content = self._request(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Language hint: {language}\nOriginal transcript:\n{masked_text}\n\n"
                            f"Invalid response:\n{raw_response}\n\nValidation error:\n"
                            f"{validation_error}\nRepair the JSON schema exactly once."
                        ),
                    },
                ]
            )
            return self._to_analysis(content)
        except ValidationError as error:
            raise ProviderError("schema_validation_failed") from error
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError(GeminiProvider._classify_error(error)) from error
