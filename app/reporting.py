import csv
import io
import json
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
    duration = transcript.duration_seconds if transcript else 0
    header_lines = [
        f"Trace ID: {result.trace_id}",
        f"Статус: {result.status.upper()} · Проверка цитат: "
        f"{'пройдена' if result.grounded else 'требуется человек'}",
        f"ASR: {result.transcription_provider or '—'} / "
        f"{result.transcription_model or '—'} · Анализ: {result.provider} / {result.model}",
        f"Длительность: {duration / 60:.1f} мин · "
        f"Network egress: {result.network_egress_bytes} bytes",
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
        pdf.set_font("DejaVu", "", 8)
        with pdf.table(
            col_widths=(28, 68, 30, 25),
            line_height=5,
            text_align=("LEFT", "LEFT", "LEFT", "LEFT"),
        ) as table:
            header = table.row()
            for label in ("Ответственный", "Задача", "Срок", "Приоритет"):
                header.cell(label)
            for item in actions:
                row = table.row()
                row.cell(str(item.get("owner") or "Не назначен"))
                row.cell(str(item.get("task") or ""))
                row.cell(str(item.get("due_date") or "Не указан"))
                row.cell(str(item.get("priority") or "medium"))
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
