import json
import sqlite3

from fastapi.testclient import TestClient

from app.audit import (
    MASKED_EXCERPT_MAX_CHARS,
    PERSISTED_MASKED_INPUT_PLACEHOLDER,
    AuditRepository,
)
from app.main import create_app
from app.models import AnalysisResult, SecurityInfo


def test_full_masked_input_is_only_returned_in_immediate_response(settings) -> None:
    private_tail = "PRIVATE_TAIL_MUST_NOT_BE_PERSISTED"
    source = "Безопасное начало. " + ("x" * 650) + private_tail

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/analyze",
            json={"text": source, "language": "ru"},
        )
        assert response.status_code == 200
        immediate_result = response.json()
        assert immediate_result["security"]["masked_input"] == source

        trace_id = immediate_result["trace_id"]
        audit_response = client.get(f"/api/v1/audit/{trace_id}")
        report_response = client.get(f"/api/v1/report/{trace_id}")

    assert audit_response.status_code == 200
    audit = audit_response.json()
    assert audit["masked_excerpt"] == source[:MASKED_EXCERPT_MAX_CHARS]
    assert audit["result"]["security"]["masked_input"] == (
        PERSISTED_MASKED_INPUT_PLACEHOLDER
    )
    assert private_tail not in audit_response.text

    assert report_response.status_code == 200
    assert PERSISTED_MASKED_INPUT_PLACEHOLDER in report_response.text
    assert private_tail not in report_response.text

    with sqlite3.connect(settings.database_path) as connection:
        row = connection.execute(
            "SELECT masked_excerpt, result_json FROM audit_events WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
    assert row is not None
    masked_excerpt, result_json = row
    assert masked_excerpt == source[:MASKED_EXCERPT_MAX_CHARS]
    assert json.loads(result_json)["security"]["masked_input"] == (
        PERSISTED_MASKED_INPUT_PLACEHOLDER
    )
    assert private_tail not in result_json


def test_repository_scrubs_legacy_result_before_returning_it(tmp_path) -> None:
    database_path = tmp_path / "legacy-audit.db"
    repository = AuditRepository(database_path)
    legacy_input = "legacy complete request that must disappear"
    result = AnalysisResult(
        trace_id="legacy-trace",
        status="ok",
        summary="Готово",
        severity="low",
        findings=[],
        security=SecurityInfo(
            input_was_masked=False,
            masked_input=legacy_input,
            pii_detected=0,
            injection_detected=False,
        ),
        grounded=True,
        timings_ms={"total": 1.0},
        provider="mock",
        model="test-model",
    )
    repository.save_result(
        created_at="2026-09-11T00:00:00+00:00",
        input_sha256="hash",
        masked_excerpt="legacy excerpt",
        result=result,
    )

    leaked_payload = result.model_dump_json()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE audit_events SET result_json = ? WHERE trace_id = ?",
            (leaked_payload, result.trace_id),
        )

    migrated_repository = AuditRepository(database_path)
    event = migrated_repository.get(result.trace_id)
    assert event is not None
    assert event["result"]["security"]["masked_input"] == (
        PERSISTED_MASKED_INPUT_PLACEHOLDER
    )

    with sqlite3.connect(database_path) as connection:
        stored_result = connection.execute(
            "SELECT result_json FROM audit_events WHERE trace_id = ?",
            (result.trace_id,),
        ).fetchone()[0]
    assert legacy_input not in stored_result
