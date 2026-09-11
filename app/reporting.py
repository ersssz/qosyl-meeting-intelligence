import csv
import io
import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fpdf import FPDF

from app.models import AnalysisResult
from app.task_profile import TASK_NAME


def build_markdown_report(result: AnalysisResult) -> str:
    verified = sum(finding.verified_in_source for finding in result.findings)
    lines = [
        f"# Executive Report — {TASK_NAME}",
        "",
        f"- Trace ID: `{result.trace_id}`",
        f"- Status: **{result.status.upper()}**",
        f"- Severity: **{result.severity.upper()}**",
        f"- Provider: `{result.provider}` / `{result.model}`",
        f"- Grounded: **{'YES' if result.grounded else 'NO — HUMAN REVIEW REQUIRED'}**",
        f"- Verified findings: **{verified}/{len(result.findings)}**",
    ]
    if result.fallback_reason:
        lines.append(f"- Fallback reason: `{result.fallback_reason}`")
    lines.extend(["", "## Summary", "", result.summary, "", "## Findings", ""])
    if not result.findings:
        lines.append("No findings were emitted.")
    for index, finding in enumerate(result.findings, start=1):
        review = (
            "VERIFIED IN SOURCE"
            if finding.verified_in_source
            else "NEEDS HUMAN REVIEW"
        )
        lines.extend(
            [
                f"### {index}. {finding.title}",
                "",
                f"> {finding.evidence}",
                "",
                f"- Verification: **{review}**",
                f"- Confidence: **{finding.confidence_score:.2f}**",
                f"- Recommendation: {finding.recommendation}",
                "",
            ]
        )
    payload = result.payload
    lines.extend(["## Meeting protocol", ""])
    for sentence in payload.get("executive_summary", []):
        lines.append(f"- {sentence}")
    lines.extend(["", "### Decisions", ""])
    for item in payload.get("decisions", []):
        lines.append(f"- {item.get('text', '')} — “{item.get('evidence', '')}”")
    lines.extend(["", "### Open questions", ""])
    for item in payload.get("open_questions", []):
        lines.append(f"- {item.get('text', '')} — “{item.get('evidence', '')}”")
    lines.extend(["", "### Action items", ""])
    for item in payload.get("action_items", []):
        lines.append(
            f"- {item.get('owner') or 'Unassigned'}: {item.get('task', '')} "
            f"(due: {item.get('due_date') or 'not stated'}, priority: "
            f"{item.get('priority', 'medium')})"
        )
    lines.extend(
        [
            "",
            "## Security controls",
            "",
            f"- PII items masked: **{result.security.pii_detected}**",
            f"- Prompt injection detected: **{result.security.injection_detected}**",
            f"- Injection reasons: {', '.join(result.security.injection_reasons) or 'none'}",
            "",
            "### Masked input used for analysis",
            "",
            "```text",
            result.security.masked_input,
            "```",
            "",
            "## Timings",
            "",
        ]
    )
    lines.extend(f"- {name}: {value:.2f} ms" for name, value in result.timings_ms.items())
    return "\n".join(lines) + "\n"


def build_json_export(result: AnalysisResult) -> str:
    export = {
        "trace_id": result.trace_id,
        "status": result.status,
        "provider": result.provider,
        "model": result.model,
        "grounded": result.grounded,
        "summary": result.summary,
        "protocol": result.payload,
    }
    return json.dumps(export, ensure_ascii=False, indent=2)


def build_csv_export(result: AnalysisResult) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=[
            "owner",
            "task",
            "due_date",
            "priority",
            "evidence",
            "verified_in_source",
            "needs_human_review",
        ],
    )
    writer.writeheader()
    for item in result.payload.get("action_items", []):
        writer.writerow({name: item.get(name) for name in writer.fieldnames})
    return "\ufeff" + stream.getvalue()


def _calendar_date(value: object) -> date | None:
    text = str(value or "").strip()
    formats = []
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        formats.append("%Y-%m-%d")
    if re.fullmatch(r"\d{2}[./]\d{2}[./]\d{4}", text):
        formats.append("%d.%m.%Y" if "." in text else "%d/%m/%Y")
    for date_format in formats:
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T.+", text):
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def calendar_action_counts(payload: dict) -> tuple[int, int, int]:
    actions = payload.get("action_items", [])
    total = len(actions) if isinstance(actions, list) else 0
    included = sum(
        _calendar_date(item.get("due_date")) is not None
        for item in actions
        if isinstance(item, dict)
    )
    return included, total, total - included


def _ics_escape(value: object) -> str:
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _ics_fold(line: str) -> str:
    chunks = []
    current = ""
    limit = 75
    for character in line:
        if current and len((current + character).encode("utf-8")) > limit:
            chunks.append(current)
            current = character
            limit = 74
        else:
            current += character
    chunks.append(current)
    return "\r\n ".join(chunks)


def build_ics_export(result: AnalysisResult) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Qosyl Meeting Intelligence//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for index, item in enumerate(result.payload.get("action_items", []), start=1):
        due = _calendar_date(item.get("due_date")) if isinstance(item, dict) else None
        if due is None:
            continue
        review = "Требуется проверка" if item.get("needs_human_review", True) else "Подтверждено"
        description = (
            f"Ответственный: {item.get('owner') or 'Не назначен'}\n"
            f"Основание: {item.get('evidence') or '—'}\nПроверка: {review}"
        )
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{result.trace_id}-{index}@qosyl.local",
                f"DTSTAMP:{timestamp}",
                f"DTSTART;VALUE=DATE:{due.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(due + timedelta(days=1)).strftime('%Y%m%d')}",
                f"SUMMARY:{_ics_escape(item.get('task'))}",
                f"DESCRIPTION:{_ics_escape(description)}",
                f"CATEGORIES:{_ics_escape(item.get('priority') or 'medium')}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(_ics_fold(line) for line in lines) + "\r\n"


def build_pdf_export(result: AnalysisResult, font_path: Path) -> bytes:
    """Build the mandatory Unicode meeting protocol PDF without persisting input."""

    if not font_path.is_file():
        raise FileNotFoundError(f"PDF font not found: {font_path}")
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_font("DejaVu", style="", fname=str(font_path))
    pdf.add_font("DejaVu", style="B", fname=str(font_path))
    pdf.set_title(str(result.payload.get("meeting_title") or "Meeting protocol"))
    pdf.set_author("Qosyl Meeting Intelligence")
    pdf.add_page()

    def heading(text: str, size: int = 15) -> None:
        pdf.set_font("DejaVu", "B", size)
        pdf.set_text_color(20, 45, 85)
        pdf.multi_cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        pdf.set_text_color(20, 20, 20)

    def bullets(items: list[str], empty: str = "Не обнаружено") -> None:
        pdf.set_font("DejaVu", "", 10)
        if not items:
            pdf.multi_cell(0, 6, empty, new_x="LMARGIN", new_y="NEXT")
        for item in items:
            pdf.multi_cell(0, 6, f"• {item}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    payload = result.payload
    heading(str(payload.get("meeting_title") or "Протокол встречи"), 18)
    pdf.set_font("DejaVu", "", 9)
    transcript = result.transcript
    duration = f"{transcript.duration_seconds / 60:.1f} мин" if transcript else "не сохранена"
    header_lines = [
        f"Trace ID: {result.trace_id}",
        f"Статус: {result.status.upper()} · Проверка цитат: "
        f"{'пройдена' if result.grounded else 'требуется человек'}",
        f"ASR: {result.transcription_provider or '—'} / "
        f"{result.transcription_model or '—'} · Анализ: {result.provider} / {result.model}",
        f"Длительность: {duration} · Network egress: {result.network_egress_bytes} bytes",
    ]
    for line in header_lines:
        pdf.multi_cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    heading("Executive Summary")
    bullets([str(item) for item in payload.get("executive_summary", [])])

    heading("Решения")
    bullets(
        [
            f"{item.get('text', '')} — «{item.get('evidence', '')}»"
            for item in payload.get("decisions", [])
        ]
    )

    heading("Поручения")
    actions = payload.get("action_items", [])
    if actions:
        pdf.set_font("DejaVu", "", 7)
        with pdf.table(
            col_widths=(18, 34, 17, 15, 48),
            line_height=4,
            text_align=("LEFT", "LEFT", "LEFT", "LEFT", "LEFT"),
        ) as table:
            header = table.row()
            for label in ("Ответственный", "Задача", "Срок", "Приоритет", "Основание"):
                header.cell(label)
            for item in actions:
                row = table.row()
                row.cell(str(item.get("owner") or "Не назначен"))
                row.cell(str(item.get("task") or ""))
                row.cell(str(item.get("due_date") or "Не указан"))
                row.cell(str(item.get("priority") or "medium"))
                review = (
                    "ТРЕБУЕТСЯ ПРОВЕРКА"
                    if item.get("needs_human_review", True)
                    else "ПОДТВЕРЖДЕНО"
                )
                row.cell(f"«{item.get('evidence', '')}»\n{review}")
        pdf.ln(3)
    else:
        bullets([])

    heading("Открытые вопросы")
    bullets(
        [
            f"{item.get('text', '')} — «{item.get('evidence', '')}»"
            for item in payload.get("open_questions", [])
        ]
    )

    heading("Риски")
    bullets(
        [
            f"{item.get('text', '')} — «{item.get('evidence', '')}»"
            for item in payload.get("risks", [])
        ]
    )
    return bytes(pdf.output())
