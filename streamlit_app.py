from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st

from app.task_profile import TASK_NAME, TASK_TAGLINE

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("UI_REQUEST_TIMEOUT_SECONDS", "20"))

st.set_page_config(page_title=TASK_NAME, page_icon="🎙️", layout="wide")
st.markdown(
    """
    <style>
      .block-container {padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1280px;}
      .hero {padding: 1.1rem 1.3rem; border: 1px solid #233554; border-radius: 16px;
             background: linear-gradient(120deg, #0f172a, #172554); color: white;}
      .badge {display: inline-block; padding: .28rem .68rem; border-radius: 999px;
              font-weight: 800; letter-spacing: .04em; color: white;}
      .ok {background: #15803d;} .blocked {background: #b91c1c;} .fallback {background: #d97706;}
      .verified {color: #15803d; font-weight: 700;} .review {color: #b45309; font-weight: 700;}
      .perf {margin:.7rem 0 1rem; padding:1rem 1.15rem; border-radius:14px;
             background:#eef2ff; border:2px solid #6366f1; color:#172554;}
      .perf strong {font-size:1.35rem;} .mode {float:right; background:#172554; color:white;
             padding:.28rem .65rem; border-radius:999px; font-weight:800;}
    </style>
    """,
    unsafe_allow_html=True,
)


def api_get(path: str) -> requests.Response:
    return requests.get(f"{API_URL}{path}", timeout=REQUEST_TIMEOUT_SECONDS)


def request_error_detail(error: requests.RequestException) -> str:
    response = error.response
    if response is None:
        return str(error)
    try:
        detail = response.json().get("detail")
    except (AttributeError, ValueError):
        detail = None
    if isinstance(detail, dict):
        detail = detail.get("reason") or detail.get("message")
    return str(detail or response.text or error)


def load_presets() -> list[dict[str, Any]]:
    response = api_get("/api/v1/presets")
    response.raise_for_status()
    return response.json()


def status_badge(status: str) -> None:
    safe_status = status if status in {"ok", "blocked", "fallback"} else "blocked"
    st.markdown(
        f'<span class="badge {safe_status}">{safe_status.upper()}</span>',
        unsafe_allow_html=True,
    )


def _payload_label(key: object) -> str:
    label = str(key).replace("_", " ").replace("-", " ").strip()
    return label.title() or "Value"


def _payload_display_value(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "YES" if value else "NO"
    return str(value)


def _is_compact_payload_value(value: object) -> bool:
    return value is None or isinstance(value, (bool, int, float)) or (
        isinstance(value, str) and len(value) <= 80
    )


def render_payload(payload: object) -> None:
    """Render any JSON-compatible task payload without knowing its schema."""

    st.markdown("#### Task-specific payload")
    if not isinstance(payload, dict):
        st.json(payload)
        return
    if not payload:
        st.caption("Профиль кейса не вернул дополнительных полей.")
        return

    compact_items = [
        (key, value) for key, value in payload.items() if _is_compact_payload_value(value)
    ]
    if compact_items:
        columns = st.columns(min(len(compact_items), 3))
        for index, (key, value) in enumerate(compact_items):
            columns[index % len(columns)].metric(
                _payload_label(key),
                _payload_display_value(value),
            )

    for key, value in payload.items():
        if _is_compact_payload_value(value):
            continue
        with st.container(border=True):
            st.caption(_payload_label(key))
            if isinstance(value, list) and all(
                item is None or isinstance(item, (str, bool, int, float)) for item in value
            ):
                if value:
                    for item in value:
                        st.write(f"• {_payload_display_value(item)}")
                else:
                    st.write("—")
            elif isinstance(value, str):
                st.write(value)
            else:
                st.json(value)

    with st.expander("Raw task payload (JSON)"):
        st.json(payload)


def render_meeting_protocol(payload: dict[str, Any]) -> None:
    st.markdown("#### Executive Summary")
    for sentence in payload.get("executive_summary", []):
        st.write(f"• {sentence}")

    protocol_columns = st.columns(3)
    sections = (
        ("Decisions", "decisions"),
        ("Open questions", "open_questions"),
        ("Risks & blockers", "risks"),
    )
    for column, (title, key) in zip(protocol_columns, sections, strict=True):
        with column:
            st.markdown(f"##### {title}")
            items = payload.get(key, [])
            if not items:
                st.caption("Не обнаружено")
            for item in items:
                st.write(f"• {item.get('text', '')}")
                st.caption(f"Evidence: {item.get('evidence', '')}")

    st.markdown("#### Action Items")
    actions = payload.get("action_items", [])
    if actions:
        st.dataframe(
            [
                {
                    "Owner": item.get("owner") or "Unassigned",
                    "Task": item.get("task"),
                    "Due": item.get("due_date") or "Not stated",
                    "Priority": item.get("priority"),
                    "Основание": item.get("evidence", ""),
                    "Verified": item.get("verified_in_source", False),
                    "Needs human review": item.get("needs_human_review", True),
                }
                for item in actions
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("Поручения не обнаружены")

    with st.expander("Full protocol JSON"):
        st.json(payload)


st.markdown(
    f'<div class="hero"><h1 style="margin:0">{TASK_NAME}</h1>'
    f'<p style="margin:.45rem 0 0">{TASK_TAGLINE}</p></div>',
    unsafe_allow_html=True,
)

try:
    health_response = api_get("/health")
    health_response.raise_for_status()
    health = health_response.json()
    quota_response = api_get("/api/v1/quota")
    quota_response.raise_for_status()
    quota = quota_response.json()
    st.caption(
        f"API connected · mode={health['mode'].upper()} · "
        f"ASR={health.get('transcription_provider', 'mock')} · "
        f"LLM={health.get('analysis_provider', 'mock')} / {health['model']} · "
        f"AIRGAP={'ON' if health.get('airgap_mode') else 'OFF'} · "
        f"local quota: {quota['rpm_remaining']}/{quota['rpm_limit']} RPM, "
        f"{quota['rpd_remaining']}/{quota['rpd_limit']} RPD · {API_URL}"
    )
    if quota["circuit_open"]:
        st.warning(
            f"Gemini circuit open: {quota['circuit_reason']} "
            f"({quota['circuit_seconds_remaining']} sec). Requests use fallback."
        )
    presets = load_presets()
except requests.RequestException as error:
    st.error(
        "FastAPI недоступен. Запустите проект командой: "
        "powershell -ExecutionPolicy Bypass -File .\\run.ps1"
    )
    st.code(str(error))
    st.stop()

if "analysis_text" not in st.session_state:
    st.session_state.analysis_text = presets[0]["text"] if presets else ""
if "preset_id" not in st.session_state:
    st.session_state.preset_id = presets[0]["id"] if presets else None
if "language" not in st.session_state:
    st.session_state.language = presets[0]["language"] if presets else "auto"

st.subheader("1-click demo presets")
preset_columns = st.columns(max(len(presets), 1))
for column, preset in zip(preset_columns, presets, strict=False):
    with column:
        if st.button(preset["title"], key=f"preset_{preset['id']}", use_container_width=True):
            st.session_state.analysis_text = preset["text"]
            st.session_state.preset_id = preset["id"]
            st.session_state.language = preset["language"]
        st.caption(preset["description"])

left, right = st.columns([1.05, 0.95], gap="large")
with left:
    st.subheader("Входные данные")
    audio_file = st.file_uploader(
        "Загрузите запись встречи",
        type=["mp3", "wav", "m4a"],
        help="MP3, WAV или M4A. Аудио не сохраняется в audit DB.",
    )
    quality_mode = st.toggle(
        "Качество для казахской речи (medium)",
        value=False,
        help="По умолчанию faster-whisper small; medium точнее, но медленнее.",
    )
    st.caption("или вставьте готовый транскрипт")
    text = st.text_area(
        "Транскрипт встречи",
        key="analysis_text",
        height=245,
        label_visibility="collapsed",
    )
    analyze_clicked = st.button(
        "Analyze meeting", type="primary", use_container_width=True
    )

if analyze_clicked:
    try:
        if audio_file is not None:
            response = requests.post(
                f"{API_URL}/api/v1/meetings/process",
                files={
                    "file": (
                        audio_file.name,
                        audio_file.getvalue(),
                        audio_file.type or "application/octet-stream",
                    )
                },
                data={
                    "language": st.session_state.language,
                    "asr_model": "medium" if quality_mode else "small",
                },
                timeout=max(REQUEST_TIMEOUT_SECONDS, 120),
            )
        else:
            response = requests.post(
                f"{API_URL}/api/v1/analyze",
                json={
                    "text": text,
                    "language": st.session_state.language,
                    "preset_id": st.session_state.preset_id,
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        response.raise_for_status()
        st.session_state.last_result = response.json()
    except requests.RequestException as error:
        st.error(f"Анализ не выполнен: {request_error_detail(error)}")

with right:
    st.subheader("Результат")
    result = st.session_state.get("last_result")
    if not result:
        st.info("Выберите пресет или вставьте текст и нажмите Analyze.")
    else:
        status_badge(result["status"])
        if result["status"] == "fallback":
            st.warning(
                f"FALLBACK: провайдер недоступен ({result.get('fallback_reason')}). "
                "Показан детерминированный офлайн-результат."
            )
        timings = result.get("timings_ms", {})
        mode = (
            "Cloud"
            if "gemini"
            in {result.get("provider"), result.get("transcription_provider")}
            else "Self-hosted"
        )
        guard_ms = timings.get("pii_masking", 0) + timings.get("injection_guard", 0)
        stage_text = " · ".join(
            (
                f"ASR: {timings.get('transcription', 0):.0f} ms",
                f"Guard: {guard_ms:.0f} ms",
                f"LLM: {timings.get('llm', 0):.0f} ms",
                f"Grounding: {timings.get('grounding', 0):.0f} ms",
            )
        )
        st.markdown(
            f'<div class="perf"><span class="mode">{mode}</span>'
            f'<strong>Итого: {timings.get("total", 0):.0f} ms</strong><br>'
            f'<b>{stage_text}</b><br><b>Network egress:</b> '
            f'{result.get("network_egress_bytes", 0):,} bytes</div>',
            unsafe_allow_html=True,
        )
        metric_columns = st.columns(4)
        metric_columns[0].metric("Severity", result["severity"].upper())
        metric_columns[1].metric("Grounded", "YES" if result["grounded"] else "REVIEW")
        metric_columns[2].metric("Provider", result["provider"].upper())
        metric_columns[3].metric("Mode", mode)
        st.write(result["summary"])
        if result.get("transcript"):
            transcript = result["transcript"]
            with st.expander(
                f"Transcript · {transcript['language']} · "
                f"{transcript['duration_seconds']:.1f} sec",
                expanded=True,
            ):
                for segment in transcript["segments"]:
                    st.markdown(
                        f"`{segment['start_seconds']:.1f}–{segment['end_seconds']:.1f}` "
                        f"**{segment['speaker']}**: {segment['text']}"
                    )
        payload = result.get("payload", {})
        if isinstance(payload, dict) and "executive_summary" in payload:
            render_meeting_protocol(payload)
        else:
            render_payload(payload)

        if result["findings"]:
            st.markdown("#### Findings")
        for finding in result["findings"]:
            with st.container(border=True):
                st.markdown(f"**{finding['title']}**")
                st.code(finding["evidence"], language=None)
                if finding["verified_in_source"]:
                    st.markdown(
                        '<span class="verified">✓ VERIFIED IN SOURCE</span>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<span class="review">⚠ NEEDS HUMAN REVIEW</span>',
                        unsafe_allow_html=True,
                    )
                st.caption(f"Confidence: {finding['confidence_score']:.2f}")
                st.write(finding["recommendation"])

        with st.expander("Security proof & audit", expanded=True):
            security = result["security"]
            st.json(
                {
                    "trace_id": result["trace_id"],
                    "pii_detected": security["pii_detected"],
                    "pii_counts": security["pii_counts"],
                    "injection_detected": security["injection_detected"],
                    "injection_reasons": security["injection_reasons"],
                    "timings_ms": result["timings_ms"],
                }
            )
            st.code(security["masked_input"], language=None)

        try:
            report_response = api_get(f"/api/v1/report/{result['trace_id']}")
            report_response.raise_for_status()
            json_response = api_get(f"/api/v1/export/{result['trace_id']}/json")
            csv_response = api_get(f"/api/v1/export/{result['trace_id']}/csv")
            pdf_response = api_get(f"/api/v1/export/{result['trace_id']}/pdf")
            json_response.raise_for_status()
            csv_response.raise_for_status()
            pdf_response.raise_for_status()
            download_columns = st.columns(4)
            download_columns[0].download_button(
                "Protocol (.md)", report_response.content,
                file_name=f"report-{result['trace_id']}.md", mime="text/markdown",
                use_container_width=True,
            )
            download_columns[1].download_button(
                "Protocol (.json)", json_response.content,
                file_name=f"meeting-{result['trace_id']}.json", mime="application/json",
                use_container_width=True,
            )
            download_columns[2].download_button(
                "Action Items (.csv)", csv_response.content,
                file_name=f"actions-{result['trace_id']}.csv", mime="text/csv",
                use_container_width=True,
            )
            download_columns[3].download_button(
                "Protocol (.pdf)", pdf_response.content,
                file_name=f"meeting-{result['trace_id']}.pdf", mime="application/pdf",
                use_container_width=True,
            )
        except requests.RequestException:
            st.warning("Отчёт временно недоступен, результат анализа сохранён в аудите.")
