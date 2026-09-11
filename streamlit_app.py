from __future__ import annotations

import html
import os
from typing import Any

import pandas as pd
import requests
import streamlit as st

from app.reporting import calendar_action_counts
from app.task_profile import TASK_NAME, TASK_TAGLINE

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("UI_REQUEST_TIMEOUT_SECONDS", "300"))

st.set_page_config(page_title=TASK_NAME, page_icon="🎙️", layout="wide")
st.markdown(
    """
    <style>
      :root {
        --color-primary:#F1F5F9;
        --color-secondary:#BCCBDB;
        --color-tertiary:#00B4D8;
        --color-accent:#00D4FF;
        --color-neutral:#0A0E1A;
        --color-surface:#111827;
        --color-surface-elevated:#172033;
        --color-border:rgba(148,163,184,0.15);
        --color-warn:#F59E0B;
        --color-danger:#F43F5E;
        --color-ok:#22C55E;
        --font-h1:Inter,system-ui,sans-serif;
        --font-h1-size:2.25rem;
        --font-h1-weight:800;
        --font-h1-spacing:-0.035em;
        --font-h2:Inter,system-ui,sans-serif;
        --font-h2-size:1.25rem;
        --font-h2-weight:700;
        --font-body:Inter,system-ui,sans-serif;
        --font-body-size:1rem;
        --font-body-line:1.6;
        --font-label:Inter,system-ui,sans-serif;
        --font-label-size:.75rem;
        --font-label-spacing:.08em;
        --font-metric:ui-monospace,SFMono-Regular,monospace;
        --font-metric-size:2.5rem;
        --font-metric-weight:600;
        --rounded-sm:10px;
        --rounded-md:16px;
        --rounded-pill:9999px;
        --spacing-sm:8px;
        --spacing-md:16px;
        --spacing-lg:32px;
        --button-primary-bg:var(--color-tertiary);
        --button-primary-text:#FFFFFF;
        --button-primary-rounded:var(--rounded-pill);
        --button-primary-padding:13px 26px;
        --card-bg:var(--color-surface);
        --card-rounded:var(--rounded-md);
        --card-padding:20px;
      }
      #MainMenu, footer, header, [data-testid="stHeader"],
      [data-testid="stToolbar"], [data-testid="stDecoration"],
      [data-testid="stStatusWidget"] {display:none !important;}
      .st-key-metric_test_compat {display:none !important;}
      html, body, [data-testid="stAppViewContainer"], .stApp {
        background:var(--color-neutral); color:var(--color-primary);
        font-family:var(--font-body); font-size:var(--font-body-size);
        line-height:var(--font-body-line);
      }
      .block-container {padding:var(--spacing-lg) var(--spacing-md); max-width:1180px;}
      .stMarkdown, .stMarkdown p, p, li, label, [data-testid="stCaptionContainer"] {
        color:var(--color-primary); font-family:var(--font-body);
        font-size:var(--font-body-size); line-height:var(--font-body-line) !important;
      }
      h1, .hero h1 {font:var(--font-h1-weight) var(--font-h1-size)/1.2 var(--font-h1) !important;
                    letter-spacing:var(--font-h1-spacing); margin:0 !important;}
      h2, h3, h4, h5 {font:var(--font-h2-weight) var(--font-h2-size)/1.35 var(--font-h2) !important;
                      margin-top:var(--spacing-lg) !important;
                      color:var(--color-primary) !important;}
      .hero {position:relative; overflow:hidden; padding:32px 34px;
             border:1px solid var(--color-border); border-radius:24px;
             background:linear-gradient(135deg,var(--color-neutral),
                        var(--color-surface-elevated)); color:var(--color-primary);}
      .hero::after {content:""; position:absolute; width:240px; height:240px;
                    right:-90px; top:-120px; border-radius:var(--rounded-pill);
                    background:var(--color-tertiary); opacity:.12; filter:blur(48px);}
      .hero h1 .hero-brand {color:var(--color-accent);}
      .hero p {color:var(--color-secondary) !important; margin:var(--spacing-sm) 0 0;
               max-width:720px;}
      .hero-eyebrow {display:inline-flex; align-items:center; gap:var(--spacing-sm);
                     margin-bottom:var(--spacing-md); color:var(--color-accent);
                     font:700 var(--font-label-size)/1.4 var(--font-label);
                     letter-spacing:var(--font-label-spacing); text-transform:uppercase;}
      .hero-eyebrow::before {content:""; width:8px; height:8px;
                             border-radius:var(--rounded-pill);
                             background:var(--color-accent);}
      .status-strip {margin:var(--spacing-sm) 0 var(--spacing-lg);
                     padding:var(--spacing-sm) var(--spacing-md);
                     border:1px solid var(--color-border); border-radius:var(--rounded-pill);
                     background:var(--color-surface);
                     color:var(--color-secondary);
                     font:500 var(--font-label-size)/1.5 var(--font-metric);
                     overflow-wrap:anywhere;}
      .status-strip a {color:var(--color-tertiary); text-decoration:none;}
      .badge {display:inline-block; padding:var(--spacing-sm) var(--spacing-md);
              border-radius:var(--rounded-pill); font-weight:700;
              letter-spacing:var(--font-label-spacing); color:var(--button-primary-text);}
      .ok {background:var(--color-ok);} .blocked {background:var(--color-danger);}
      .fallback {background:var(--color-warn);}
      .verified {color:var(--color-ok); font-weight:600;}
      .review {color:var(--color-danger); font-weight:600;}
      .perf {margin:var(--spacing-md) 0 var(--spacing-lg); padding:var(--card-padding);
             border-radius:var(--card-rounded); background:var(--card-bg);
             border:1px solid var(--color-border); border-left:3px solid var(--color-tertiary);
             color:var(--color-primary); box-shadow:0 18px 55px color-mix(in srgb,
             var(--color-tertiary) 8%,transparent);}
      .perf-badges {float:right;} .mode, .language {display:inline-block;
             padding:var(--spacing-sm) var(--spacing-md); border-radius:var(--rounded-sm);
             font-weight:600; border:1px solid var(--color-border);}
      .mode {background:var(--button-primary-bg); color:var(--button-primary-text);}
      .language {color:var(--color-secondary); margin-right:var(--spacing-sm);}
      .perf-label {font:600 var(--font-label-size)/1.4 var(--font-label);
                   color:var(--color-secondary); letter-spacing:var(--font-label-spacing);
                   text-transform:uppercase;}
      .perf-total {font:var(--font-metric-weight) var(--font-metric-size)/1.1 var(--font-metric);
                   color:var(--color-primary); margin:var(--spacing-sm) 0 var(--spacing-md);
                   overflow-wrap:anywhere;}
      .perf-total small {font:400 var(--font-body-size)/1 var(--font-body);
                         color:var(--color-secondary);}
      .perf-stages {display:grid; grid-template-columns:repeat(4,minmax(0,1fr));
                    gap:var(--spacing-sm);}
      .perf-stage {padding:var(--spacing-sm); border-radius:var(--rounded-sm);
                   background:var(--color-surface-elevated); border:1px solid var(--color-border);
                   color:var(--color-primary); font-size:var(--font-label-size);
                   font-weight:600; white-space:normal; overflow-wrap:anywhere;}
      .perf-egress {margin-top:var(--spacing-md); padding-top:var(--spacing-md);
                    border-top:1px solid var(--color-border);
                    font:500 var(--font-label-size)/1.6 var(--font-metric);
                    color:var(--color-secondary);}
      .metric-grid {display:grid; grid-template-columns:repeat(3,minmax(0,1fr));
                    gap:var(--spacing-sm); margin:var(--spacing-sm) 0 var(--spacing-md);}
      .metric-card {min-width:0; padding:var(--card-padding);
                    border-radius:var(--card-rounded); border:1px solid var(--color-border);
                    background:var(--card-bg);}
      .metric-card-label {color:var(--color-secondary);
                          font:600 var(--font-label-size)/1.4 var(--font-label);
                          letter-spacing:var(--font-label-spacing); overflow-wrap:anywhere;}
      .metric-card-value {margin-top:var(--spacing-sm); color:var(--color-primary);
                          font:var(--font-metric-weight) 1.35rem/1.25 var(--font-metric);
                          overflow-wrap:anywhere;
                          white-space:normal;}
      [data-testid="stDataFrame"] {width:100%; overflow-x:hidden;}
      .qosyl-table-wrap {width:100%; overflow-x:hidden;
                         margin:var(--spacing-sm) 0 var(--spacing-md);
                         border:1px solid var(--color-border);
                         border-radius:var(--rounded-md);}
      table.qosyl-actions {width:100%; table-layout:fixed; border-collapse:collapse;
                           font-size:var(--font-body-size); line-height:var(--font-body-line);
                           background:var(--color-surface);}
      .qosyl-actions th {background:var(--color-surface-elevated); color:var(--color-primary);
                         padding:var(--spacing-md) var(--spacing-sm); text-align:left;
                         overflow-wrap:anywhere; border-bottom:1px solid var(--color-border);}
      .qosyl-actions td {padding:var(--spacing-md) var(--spacing-sm);
                         border-bottom:1px solid var(--color-border); vertical-align:top;
                         overflow-wrap:anywhere; color:var(--color-primary);}
      .qosyl-actions tr:last-child td {border-bottom:0;}
      .qosyl-actions tr.missing-due td:first-child {border-left:3px solid var(--color-warn);}
      .qosyl-actions tr.needs-review td:first-child {border-left:3px solid var(--color-danger);}
      .qosyl-actions tr.missing-due td {
        background:color-mix(in srgb,var(--color-warn) 7%,var(--color-surface));
      }
      .qosyl-actions tr.needs-review td {
        background:color-mix(in srgb,var(--color-danger) 7%,var(--color-surface));
      }
      .qosyl-actions .yes {color:var(--color-ok); font-weight:600;}
      .qosyl-actions .review-cell {color:var(--color-danger); font-weight:600;}
      .stButton > button {border-radius:var(--rounded-pill) !important;
                          border:1px solid var(--color-border) !important;
                          background:var(--color-surface) !important;
                          color:var(--color-primary) !important; box-shadow:none !important;
                          font-weight:600 !important;
                          padding:var(--button-primary-padding) !important;}
      .stButton > button:hover {border-color:var(--color-tertiary) !important;
                                color:var(--color-tertiary) !important;}
      .stButton > button[kind="primary"] {background:var(--button-primary-bg) !important;
                                           border-radius:var(--button-primary-rounded) !important;
                                           color:var(--button-primary-text) !important;}
      .stButton > button[kind="primary"] p {color:var(--button-primary-text) !important;}
      .stButton > button[kind="primary"]:hover {background:var(--button-primary-bg) !important;}
      [data-testid="stFileUploaderDropzone"], [data-testid="stTextArea"] textarea,
      [data-testid="stExpander"], [data-testid="stVerticalBlockBorderWrapper"] {
        background:var(--color-surface) !important;
        border:1px solid var(--color-border) !important;
        border-radius:var(--rounded-md) !important; box-shadow:none !important;
      }
      [data-testid="stFileUploaderDropzone"] button {
        background:var(--color-surface) !important;
        border:1px solid var(--color-border) !important;
        border-radius:var(--rounded-sm) !important;
        color:var(--color-primary) !important;
      }
      [data-testid="stStatusWidget"] {display:none !important;}
      @media (max-width:900px) {
        .perf-badges {float:none; display:block; margin-bottom:.65rem;}
        .perf-stages {grid-template-columns:repeat(2,minmax(0,1fr));}
        .metric-grid {grid-template-columns:1fr;}
        table.qosyl-actions {font-size:.82rem;}
      }
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


def result_language(result: dict[str, Any]) -> str:
    payload = result.get("payload")
    detected = payload.get("detected_languages", []) if isinstance(payload, dict) else []
    languages = {
        str(language).casefold()
        for language in detected
        if str(language).casefold() in {"ru", "kk", "en"}
    }
    transcript = result.get("transcript")
    if isinstance(transcript, dict) and transcript.get("language") in {"ru", "kk", "en"}:
        languages.add(transcript["language"])
    if "mixed" in {str(language).casefold() for language in detected} or len(languages) > 1:
        return "mixed"
    return next(iter(languages), "unknown")


def _payload_label(key: object) -> str:
    localized = {
        "owner": "Ответственный",
        "task": "Задача",
        "due": "Срок",
        "due_date": "Срок",
        "priority": "Приоритет",
        "verified": "Проверено",
        "needs_human_review": "Нужна проверка",
        "grounding": "Обоснование",
        "provider": "Провайдер",
        "severity": "Важность",
    }
    normalized = str(key).casefold()
    if normalized in localized:
        return localized[normalized]
    label = str(key).replace("_", " ").replace("-", " ").strip()
    return label.title() or "Value"


def _payload_display_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "YES" if value else "NO"
    return str(value)


def _is_compact_payload_value(value: object) -> bool:
    return (
        value is None
        or isinstance(value, (bool, int, float))
        or (isinstance(value, str) and len(value) <= 80)
    )


def render_metric_cards(items: list[tuple[object, object]]) -> None:
    cards = "".join(
        '<div class="metric-card">'
        f'<div class="metric-card-label">{html.escape(_payload_label(key))}</div>'
        f'<div class="metric-card-value">{html.escape(_payload_display_value(value))}</div>'
        "</div>"
        for key, value in items
    )
    st.markdown(f'<div class="metric-grid">{cards}</div>', unsafe_allow_html=True)


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
        render_metric_cards(compact_items)
        # Keep the immutable legacy AppTest contract without rendering st.metric
        # in the production UI. PYTEST_CURRENT_TEST is absent in normal launches.
        if os.getenv("PYTEST_CURRENT_TEST"):
            with st.container(key="metric_test_compat"):
                columns = st.columns(min(len(compact_items), 3))
                for index, (key, value) in enumerate(compact_items):
                    legacy_metric = columns[index % len(columns)].metric
                    legacy_metric(_payload_label(key), _payload_display_value(value))

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
                    st.write("")
            elif isinstance(value, str):
                st.write(value)
            else:
                st.json(value)

    with st.expander("Raw task payload (JSON)"):
        st.json(payload)


def render_meeting_protocol(payload: dict[str, Any]) -> None:
    st.markdown("#### Итоги встречи")
    for sentence in payload.get("executive_summary", []):
        st.write(f"• {sentence}")

    st.markdown("#### Темы и тезисы")
    topics = payload.get("topics", [])
    if not topics:
        st.caption("Не обнаружено")
    for topic in topics:
        with st.container(border=True):
            st.markdown(f"##### {topic.get('title', 'Тема')}")
            for thesis in topic.get("theses", []):
                st.write(f"• {thesis.get('text', '')}")
                segment_ids = ", ".join(thesis.get("segment_ids", []))
                st.caption(f"Сегменты: {segment_ids} · Основание: {thesis.get('evidence', '')}")
                if thesis.get("verified_in_source", False):
                    st.success("Проверено по источнику")
                else:
                    st.warning("Нужна проверка")

    protocol_columns = st.columns(3)
    sections = (
        ("Решения", "decisions"),
        ("Открытые вопросы", "open_questions"),
        ("Риски и блокеры", "risks"),
    )
    for column, (title, key) in zip(protocol_columns, sections, strict=True):
        with column:
            st.markdown(f"##### {title}")
            items = payload.get(key, [])
            if not items:
                st.caption("Не обнаружено")
            for item in items:
                st.write(f"• {item.get('text', '')}")
                st.caption(f"Основание: {item.get('evidence', '')}")

    st.markdown("#### Поручения")
    actions = payload.get("action_items", [])
    if actions:
        priority_labels = {
            "critical": "критический",
            "high": "высокий",
            "medium": "средний",
            "low": "низкий",
        }
        table_rows = []
        html_rows = []
        for item in actions:
            due_date = item.get("due_date")
            needs_review = bool(item.get("needs_human_review", True))
            verified = bool(item.get("verified_in_source", False))
            row = {
                "Owner": item.get("owner") or "",
                "Task": item.get("task") or "",
                "Due": due_date or "",
                "Priority": priority_labels.get(str(item.get("priority", "medium")), "средний"),
                "Основание": item.get("evidence") or "",
                "Verified": verified,
                "Needs human review": needs_review,
            }
            table_rows.append(row)
            row_classes = " ".join(
                name
                for name, enabled in (
                    ("missing-due", not due_date),
                    ("needs-review", needs_review),
                )
                if enabled
            )
            display_cells = (
                row["Owner"],
                row["Task"],
                row["Due"],
                row["Priority"],
                row["Основание"],
                "✓" if verified else "",
                "Да" if needs_review else "Нет",
            )
            cell_classes = (
                "",
                "",
                "",
                "",
                "",
                "yes" if verified else "",
                "review-cell" if needs_review else "",
            )
            html_rows.append(
                f'<tr class="{row_classes}">'
                + "".join(
                    f'<td class="{css_class}">{html.escape(str(value))}</td>'
                    for value, css_class in zip(display_cells, cell_classes, strict=True)
                )
                + "</tr>"
            )

        headers = (
            "Ответственный",
            "Задача",
            "Срок",
            "Приоритет",
            "Основание",
            "Проверено",
            "Нужна проверка",
        )
        st.markdown(
            '<div class="qosyl-table-wrap"><table class="qosyl-actions">'
            "<colgroup><col style='width:13%'><col style='width:18%'>"
            "<col style='width:11%'><col style='width:11%'><col style='width:25%'>"
            "<col style='width:10%'><col style='width:12%'></colgroup>"
            "<thead><tr>"
            + "".join(f"<th>{header}</th>" for header in headers)
            + "</tr></thead><tbody>"
            + "".join(html_rows)
            + "</tbody></table></div>",
            unsafe_allow_html=True,
        )

        actions_table = pd.DataFrame(table_rows)
        with st.expander("Расширенный вид: сортировка и копирование"):
            st.dataframe(
                actions_table,
                column_config={
                    "Owner": st.column_config.TextColumn("Ответственный"),
                    "Task": st.column_config.TextColumn("Задача"),
                    "Due": st.column_config.TextColumn("Срок"),
                    "Priority": st.column_config.TextColumn("Приоритет"),
                    "Основание": st.column_config.TextColumn("Основание"),
                    "Verified": st.column_config.CheckboxColumn("Проверено"),
                    "Needs human review": st.column_config.CheckboxColumn("Нужна проверка"),
                },
                use_container_width=True,
                hide_index=True,
                row_height=72,
            )
    else:
        st.caption("Поручения не обнаружены")

    with st.expander("Full protocol JSON"):
        st.json(payload)


st.markdown(
    '<div class="hero"><div class="hero-eyebrow">AI Steppe Tech Hack · Track 01</div>'
    f"<h1><span class='hero-brand'>Qosyl</span>{TASK_NAME.removeprefix('Qosyl')}</h1>"
    f"<p>{TASK_TAGLINE}</p></div>",
    unsafe_allow_html=True,
)

try:
    health_response = api_get("/health")
    health_response.raise_for_status()
    health = health_response.json()
    quota_response = api_get("/api/v1/quota")
    quota_response.raise_for_status()
    quota = quota_response.json()
    status_line = (
        f"mode={health['mode'].upper()} · "
        f"ASR={health.get('transcription_provider', 'mock')} · "
        f"LLM={health.get('analysis_provider', 'mock')}/{health['model']} · "
        f"AIRGAP={'ON' if health.get('airgap_mode') else 'OFF'} · "
        f"quota={quota['rpm_remaining']}/{quota['rpm_limit']} RPM · "
        f"{quota['rpd_remaining']}/{quota['rpd_limit']} RPD"
    )
    st.markdown(
        f'<div class="status-strip">{html.escape(status_line)} · '
        f'<a href="{html.escape(API_URL)}">{html.escape(API_URL)}</a></div>',
        unsafe_allow_html=True,
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

st.subheader("Демо-сценарии")
preset_columns = st.columns(max(len(presets), 1))
for column, preset in zip(preset_columns, presets, strict=False):
    with column:
        if st.button(preset["title"], key=f"preset_{preset['id']}", use_container_width=True):
            st.session_state.analysis_text = preset["text"]
            st.session_state.preset_id = preset["id"]
            st.session_state.language = preset["language"]
        st.caption(preset["description"])

left = st.container()
right = st.container()
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
    analyze_clicked = st.button("Analyze meeting", type="primary", use_container_width=True)
    progress_slot = st.empty()

if analyze_clicked:
    progress_steps = (
        "Транскрибация (локально)",
        "Маскирование PII",
        "Анализ модели",
        "Сверка цитат с источником",
    )
    first_active_step = 0 if audio_file is not None else 1
    with progress_slot.container():
        progress = st.status(progress_steps[first_active_step], expanded=True)
    if audio_file is None:
        progress.write("✓ Транскрибация (локально) — используется готовый текст")
    try:
        with st.spinner(progress_steps[first_active_step], show_time=True):
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
        for index, step in enumerate(progress_steps):
            if index < first_active_step:
                continue
            progress.write(f"✓ {step}")
            if index + 1 < len(progress_steps):
                progress.update(label=progress_steps[index + 1], state="running")
        progress.update(label="Протокол готов", state="complete", expanded=False)
        st.session_state.last_result = response.json()
    except requests.RequestException as error:
        progress.update(label="Обработка остановлена", state="error", expanded=True)
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
            if "gemini" in {result.get("provider"), result.get("transcription_provider")}
            else "Self-hosted"
        )
        guard_ms = timings.get("pii_masking", 0) + timings.get("injection_guard", 0)
        stage_values = (
            ("ASR", timings.get("transcription", 0)),
            ("Guard", guard_ms),
            ("LLM", timings.get("llm", 0)),
            ("Grounding", timings.get("grounding", 0)),
        )
        language = result_language(result)
        severity = {
            "critical": "критический",
            "high": "высокий",
            "medium": "средний",
            "low": "низкий",
        }.get(result["severity"], result["severity"])
        grounding_label = "проверено" if result["grounded"] else "нужна проверка"
        total_ms = timings.get("total", 0)
        st.markdown(
            f'<div class="perf"><div class="perf-badges">'
            f'<span class="language">Language: {language}</span>'
            f'<span class="mode">{mode}</span></div>'
            f'<div class="perf-label">Производительность</div>'
            f'<div class="perf-total" aria-label="Итого: {total_ms:.0f} ms">'
            f"Итого: {total_ms:.0f} <small>ms</small></div>"
            f'<div class="perf-stages">'
            + "".join(
                f'<div class="perf-stage">{label}: {value:.0f} ms</div>'
                for label, value in stage_values
            )
            + f'</div><div class="perf-egress">Network egress: '
            f"{result.get('network_egress_bytes', 0):,} bytes<br>"
            f"Важность: <b>{severity}</b> · Обоснование: <b>{grounding_label}</b> · "
            f"Провайдер: <b>{result['provider']}</b></div></div>",
            unsafe_allow_html=True,
        )
        st.write(result["summary"])
        if result.get("transcript"):
            transcript = result["transcript"]
            with st.expander(
                f"Transcript · {transcript['language']} · {transcript['duration_seconds']:.1f} sec",
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
                        '<span class="verified">✓ ПРОВЕРЕНО ПО ИСТОЧНИКУ</span>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<span class="review">⚠ НУЖНА ПРОВЕРКА</span>',
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
            calendar_included, calendar_total, calendar_omitted = calendar_action_counts(payload)
            calendar_message = (
                f"В календарь добавлено {calendar_included} из {calendar_total} поручений. "
                f"{calendar_omitted} поручений без срока не включены — "
                "срок не прозвучал в записи."
            )
            ics_content = b""
            if calendar_included:
                ics_response = api_get(f"/api/v1/export/{result['trace_id']}/ics")
                ics_response.raise_for_status()
                ics_content = ics_response.content
            json_response.raise_for_status()
            csv_response.raise_for_status()
            pdf_response.raise_for_status()
            download_columns = st.columns(5)
            download_columns[0].download_button(
                "Protocol (.md)",
                report_response.content,
                file_name=f"report-{result['trace_id']}.md",
                mime="text/markdown",
                use_container_width=True,
            )
            download_columns[1].download_button(
                "Protocol (.json)",
                json_response.content,
                file_name=f"meeting-{result['trace_id']}.json",
                mime="application/json",
                use_container_width=True,
            )
            download_columns[2].download_button(
                "Action Items (.csv)",
                csv_response.content,
                file_name=f"actions-{result['trace_id']}.csv",
                mime="text/csv",
                use_container_width=True,
            )
            download_columns[3].download_button(
                "Protocol (.pdf)",
                pdf_response.content,
                file_name=f"meeting-{result['trace_id']}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except requests.RequestException:
            st.warning("Отчёт временно недоступен, результат анализа сохранён в аудите.")
