import csv
import io
import json

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
