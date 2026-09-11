from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings


@dataclass(frozen=True)
class QuotaLimits:
    rpm: int
    rpd: int


@dataclass(frozen=True)
class QuotaSnapshot:
    model: str
    rpm_limit: int
    rpm_used: int
    rpd_limit: int
    rpd_used: int
    circuit_open: bool
    circuit_reason: str | None
    circuit_seconds_remaining: int

    def as_dict(self) -> dict[str, str | int | bool | None]:
        return {
            "model": self.model,
            "rpm_limit": self.rpm_limit,
            "rpm_used": self.rpm_used,
            "rpm_remaining": max(self.rpm_limit - self.rpm_used, 0),
            "rpd_limit": self.rpd_limit,
            "rpd_used": self.rpd_used,
            "rpd_remaining": max(self.rpd_limit - self.rpd_used, 0),
            "circuit_open": self.circuit_open,
            "circuit_reason": self.circuit_reason,
            "circuit_seconds_remaining": self.circuit_seconds_remaining,
        }


class LocalQuotaBlocked(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def limits_for_model(model: str, settings: Settings) -> QuotaLimits:
    normalized = model.removeprefix("models/").casefold()
    known = {
        "gemini-3.5-flash-lite": QuotaLimits(rpm=15, rpd=500),
        "gemini-3.8-flash": QuotaLimits(rpm=5, rpd=20),
    }
    defaults = known.get(normalized, QuotaLimits(rpm=5, rpd=20))
    return QuotaLimits(
        rpm=settings.gemini_rpm_limit or defaults.rpm,
        rpd=settings.gemini_rpd_limit or defaults.rpd,
    )


class QuotaManager:
    """Persistent, process-safe local guard in front of paid Gemini requests."""

    def __init__(
        self,
        database_path: Path,
        settings: Settings,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.database_path = database_path
        self.settings = settings
        self.clock = clock
        self._thread_lock = threading.Lock()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model TEXT NOT NULL,
                    attempted_at REAL NOT NULL,
                    attempted_day_utc TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_llm_attempts_model_time
                ON llm_attempts(model, attempted_at)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_circuit_state (
                    model TEXT PRIMARY KEY,
                    open_until REAL NOT NULL,
                    reason TEXT
                )
                """
            )

    @staticmethod
    def _utc_day(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, UTC).date().isoformat()

    def reserve(self, model: str) -> None:
        """Atomically reserve exactly one outbound request, or block before the network."""

        now = self.clock()
        limits = limits_for_model(model, self.settings)
        with self._thread_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            circuit = connection.execute(
                "SELECT open_until, reason FROM llm_circuit_state WHERE model = ?",
                (model,),
            ).fetchone()
            if circuit is not None and circuit["open_until"] > now:
                raise LocalQuotaBlocked(f"circuit_open_{circuit['reason'] or 'provider'}")

            rpm_used = connection.execute(
                "SELECT COUNT(*) FROM llm_attempts WHERE model = ? AND attempted_at > ?",
                (model, now - 60),
            ).fetchone()[0]
            if rpm_used >= limits.rpm:
                raise LocalQuotaBlocked("local_rpm_limit")

            day = self._utc_day(now)
            rpd_used = connection.execute(
                "SELECT COUNT(*) FROM llm_attempts WHERE model = ? AND attempted_day_utc = ?",
                (model, day),
            ).fetchone()[0]
            if rpd_used >= limits.rpd:
                raise LocalQuotaBlocked("local_rpd_limit")

            connection.execute(
                "INSERT INTO llm_attempts(model, attempted_at, attempted_day_utc) VALUES (?, ?, ?)",
                (model, now, day),
            )

    def record_success(self, model: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM llm_circuit_state WHERE model = ?", (model,))

    def record_failure(self, model: str, reason: str) -> None:
        if reason == "rate_limited":
            cooldown = self.settings.quota_rate_limit_cooldown_seconds
        elif reason in {"timeout", "network_error"}:
            cooldown = self.settings.quota_network_cooldown_seconds
        else:
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO llm_circuit_state(model, open_until, reason)
                VALUES (?, ?, ?)
                ON CONFLICT(model) DO UPDATE SET
                    open_until = excluded.open_until,
                    reason = excluded.reason
                """,
                (model, self.clock() + cooldown, reason),
            )

    def snapshot(self, model: str) -> QuotaSnapshot:
        now = self.clock()
        limits = limits_for_model(model, self.settings)
        with self._connect() as connection:
            rpm_used = connection.execute(
                "SELECT COUNT(*) FROM llm_attempts WHERE model = ? AND attempted_at > ?",
                (model, now - 60),
            ).fetchone()[0]
            rpd_used = connection.execute(
                "SELECT COUNT(*) FROM llm_attempts WHERE model = ? AND attempted_day_utc = ?",
                (model, self._utc_day(now)),
            ).fetchone()[0]
            circuit = connection.execute(
                "SELECT open_until, reason FROM llm_circuit_state WHERE model = ?",
                (model,),
            ).fetchone()
        open_until = float(circuit["open_until"]) if circuit is not None else 0.0
        is_open = open_until > now
        return QuotaSnapshot(
            model=model,
            rpm_limit=limits.rpm,
            rpm_used=rpm_used,
            rpd_limit=limits.rpd,
            rpd_used=rpd_used,
            circuit_open=is_open,
            circuit_reason=circuit["reason"] if is_open else None,
            circuit_seconds_remaining=max(int(open_until - now + 0.999), 0) if is_open else 0,
        )

