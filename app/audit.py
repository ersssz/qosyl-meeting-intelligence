from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.models import AnalysisResult

MASKED_EXCERPT_MAX_CHARS = 500
PERSISTED_MASKED_INPUT_PLACEHOLDER = "[MASKED INPUT NOT PERSISTED]"


class AuditRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    trace_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    input_sha256 TEXT NOT NULL,
                    masked_excerpt TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    fallback_reason TEXT,
                    pii_counts_json TEXT NOT NULL,
                    injection_detected INTEGER NOT NULL,
                    injection_reasons_json TEXT NOT NULL,
                    timings_json TEXT NOT NULL,
                    result_json TEXT
                )
                """
            )
            self._sanitize_existing_rows(connection)

    @staticmethod
    def _sanitize_result_payload(payload: Any) -> Any:
        """Remove request text from a result before storage or disclosure."""

        if not isinstance(payload, dict):
            return payload
        security = payload.get("security")
        if not isinstance(security, dict) or "masked_input" not in security:
            return payload

        sanitized_payload = dict(payload)
        sanitized_security = dict(security)
        sanitized_security["masked_input"] = PERSISTED_MASKED_INPUT_PLACEHOLDER
        sanitized_payload["security"] = sanitized_security
        # Audio transcripts can contain confidential meeting content. They are returned
        # to the current caller but never persisted in the audit database.
        if "transcript" in sanitized_payload:
            sanitized_payload["transcript"] = None
        return sanitized_payload

    @classmethod
    def _serialize_result_for_storage(cls, result: AnalysisResult) -> str:
        payload = result.model_dump(mode="json")
        sanitized_payload = cls._sanitize_result_payload(payload)
        return json.dumps(sanitized_payload, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def _sanitize_existing_rows(cls, connection: sqlite3.Connection) -> None:
        """Scrub records written by versions that persisted the complete input."""

        connection.execute(
            """
            UPDATE audit_events
            SET masked_excerpt = substr(masked_excerpt, 1, ?)
            WHERE length(masked_excerpt) > ?
            """,
            (MASKED_EXCERPT_MAX_CHARS, MASKED_EXCERPT_MAX_CHARS),
        )
        rows = connection.execute(
            """
            SELECT trace_id, result_json
            FROM audit_events
            WHERE result_json IS NOT NULL
            """
        ).fetchall()
        sanitized_rows: list[tuple[str, str]] = []
        for row in rows:
            try:
                payload = json.loads(row["result_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            sanitized_payload = cls._sanitize_result_payload(payload)
            if sanitized_payload != payload:
                serialized = json.dumps(
                    sanitized_payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                sanitized_rows.append((serialized, row["trace_id"]))
        connection.executemany(
            "UPDATE audit_events SET result_json = ? WHERE trace_id = ?",
            sanitized_rows,
        )

    def save_result(
        self,
        *,
        created_at: str,
        input_sha256: str,
        masked_excerpt: str,
        result: AnalysisResult,
    ) -> None:
        safe_excerpt = masked_excerpt[:MASKED_EXCERPT_MAX_CHARS]
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (
                    trace_id, created_at, input_sha256, masked_excerpt, status,
                    provider, model, fallback_reason, pii_counts_json,
                    injection_detected, injection_reasons_json, timings_json, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.trace_id,
                    created_at,
                    input_sha256,
                    safe_excerpt,
                    result.status,
                    result.provider,
                    result.model,
                    result.fallback_reason,
                    json.dumps(result.security.pii_counts, ensure_ascii=False),
                    int(result.security.injection_detected),
                    json.dumps(result.security.injection_reasons, ensure_ascii=False),
                    json.dumps(result.timings_ms, ensure_ascii=False),
                    self._serialize_result_for_storage(result),
                ),
            )

    def save_failure(
        self,
        *,
        trace_id: str,
        created_at: str,
        input_sha256: str,
        masked_excerpt: str,
        provider: str,
        model: str,
        reason: str,
        pii_counts: dict[str, int],
        injection_detected: bool,
        injection_reasons: list[str],
        timings_ms: dict[str, float],
    ) -> None:
        safe_excerpt = masked_excerpt[:MASKED_EXCERPT_MAX_CHARS]
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (
                    trace_id, created_at, input_sha256, masked_excerpt, status,
                    provider, model, fallback_reason, pii_counts_json,
                    injection_detected, injection_reasons_json, timings_json, result_json
                ) VALUES (?, ?, ?, ?, 'error', ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    trace_id,
                    created_at,
                    input_sha256,
                    safe_excerpt,
                    provider,
                    model,
                    reason,
                    json.dumps(pii_counts, ensure_ascii=False),
                    int(injection_detected),
                    json.dumps(injection_reasons, ensure_ascii=False),
                    json.dumps(timings_ms, ensure_ascii=False),
                ),
            )

    def get(self, trace_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM audit_events WHERE trace_id = ?", (trace_id,)
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        for field in (
            "pii_counts_json",
            "injection_reasons_json",
            "timings_json",
            "result_json",
        ):
            if item[field] is not None:
                item[field.removesuffix("_json")] = json.loads(item.pop(field))
            else:
                item[field.removesuffix("_json")] = None
                item.pop(field)
        item["result"] = self._sanitize_result_payload(item["result"])
        item["masked_excerpt"] = item["masked_excerpt"][:MASKED_EXCERPT_MAX_CHARS]
        item["injection_detected"] = bool(item["injection_detected"])
        return item
