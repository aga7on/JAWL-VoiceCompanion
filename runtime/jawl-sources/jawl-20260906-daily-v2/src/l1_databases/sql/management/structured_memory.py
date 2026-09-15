"""Small append-only controller for durable shared Companion memory."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any, TYPE_CHECKING

from sqlalchemy import select, text

from src.l1_databases.sql.tables import StructuredMemoryTable
from src.l3_agent.skills.registry import skill, SkillResult
from src.l3_agent.subconscious.schema import Pattern
from src.utils._tools import truncate_text

if TYPE_CHECKING:
    from src.l1_databases.sql.db import SQLDB


class SQLStructuredMemory:
    """Versioned facts/traits; active rows are the only prompt projection."""

    _KINDS = {"fact", "trait", "preference", "summary"}
    _STATUSES = {"active", "forgotten", "archived"}
    _RETENTION_TIERS = {"short", "standard", "long", "permanent"}

    def __init__(self, db: "SQLDB", max_active: int = 200, context_limit: int = 12) -> None:
        self.db = db
        self.max_active = max(1, min(int(max_active), 5000))
        self.context_limit = max(1, min(int(context_limit), 100))

    async def bootstrap_migrations(self) -> None:
        """Add temporal columns to databases created before this contract.

        ``create_all`` deliberately does not alter an existing SQLite table.
        The migration is therefore tiny, idempotent and limited to columns
        owned by structured memory.  Existing rows become valid from their
        original creation time and keep the long retention tier.
        """

        async with self.db.engine.begin() as connection:
            result = await connection.execute(text("PRAGMA table_info(structured_memories)"))
            columns = {str(row[1]) for row in result.fetchall() if len(row) > 1}
            for name, definition in (
                ("valid_from", "DATETIME"),
                ("valid_until", "DATETIME"),
                ("retention_tier", "VARCHAR(32) DEFAULT 'long'"),
            ):
                if name not in columns:
                    await connection.execute(text(f"ALTER TABLE structured_memories ADD COLUMN {name} {definition}"))
            await connection.execute(
                text(
                    "UPDATE structured_memories "
                    "SET valid_from = created_at WHERE valid_from IS NULL"
                )
            )
            await connection.execute(
                text(
                    "UPDATE structured_memories "
                    "SET retention_tier = 'long' "
                    "WHERE retention_tier IS NULL OR retention_tier = ''"
                )
            )

    @staticmethod
    def _text(value: Any, limit: int, name: str, required: bool = True) -> str:
        result = str(value or "").strip()
        if required and not result:
            raise ValueError(f"{name} cannot be empty.")
        if len(result) > limit:
            raise ValueError(f"{name} exceeds {limit} characters.")
        return result

    @staticmethod
    def _timestamp(value: Any, name: str, *, default_now: bool = False) -> datetime | None:
        if value is None:
            return datetime.now(timezone.utc) if default_now else None
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
        else:
            raise ValueError(f"{name} must be an ISO-8601 timestamp")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _normalized(self, kind: str, subject: str, predicate: str, value: str,
                    source: str | None, confidence: float, provenance: dict[str, Any] | None,
                    valid_from: Any = None, valid_until: Any = None,
                    retention_tier: str = "long") -> dict[str, Any]:
        kind = self._text(kind, 32, "kind")
        if kind not in self._KINDS:
            raise ValueError(f"kind must be one of {sorted(self._KINDS)}.")
        confidence = float(confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1.")
        if provenance is not None and not isinstance(provenance, dict):
            raise ValueError("provenance must be an object.")
        retention_tier = self._text(retention_tier, 32, "retention_tier")
        if retention_tier not in self._RETENTION_TIERS:
            raise ValueError(f"retention_tier must be one of {sorted(self._RETENTION_TIERS)}.")
        valid_from = self._timestamp(valid_from, "valid_from", default_now=True)
        valid_until = self._timestamp(valid_until, "valid_until")
        if valid_from is None:
            raise ValueError("valid_from cannot be empty")
        if valid_until is not None and valid_until <= valid_from:
            raise ValueError("valid_until must be later than valid_from")
        return {
            "kind": kind,
            "subject": self._text(subject, 256, "subject"),
            "predicate": self._text(predicate, 256, "predicate"),
            "value": self._text(value, 4000, "value"),
            "source": self._text(source, 256, "source", required=False) or None,
            "confidence": confidence,
            "provenance": provenance or {},
            "valid_from": valid_from,
            "valid_until": valid_until,
            "retention_tier": retention_tier,
        }

    @staticmethod
    async def _current(session, memory_key: str) -> StructuredMemoryTable | None:
        result = await session.execute(
            select(StructuredMemoryTable)
            .where(StructuredMemoryTable.memory_key == memory_key)
            .order_by(StructuredMemoryTable.revision.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _latest(session) -> list[StructuredMemoryTable]:
        result = await session.execute(
            select(StructuredMemoryTable).order_by(
                StructuredMemoryTable.memory_key.asc(), StructuredMemoryTable.revision.desc()
            )
        )
        latest: dict[str, StructuredMemoryTable] = {}
        for row in result.scalars().all():
            latest.setdefault(row.memory_key, row)
        return list(latest.values())

    @staticmethod
    def _public(row: StructuredMemoryTable) -> dict[str, Any]:
        def iso(value: datetime | None) -> str | None:
            if value is None:
                return None
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat()

        return {
            "id": row.id,
            "memory_key": row.memory_key,
            "revision": row.revision,
            "kind": row.kind,
            "subject": row.subject,
            "predicate": row.predicate,
            "value": row.value,
            "source": row.source,
            "confidence": row.confidence,
            "status": row.status,
            "supersedes_id": row.supersedes_id,
            "created_at": iso(row.created_at),
            "valid_from": iso(row.valid_from),
            "valid_until": iso(row.valid_until),
            "retention_tier": row.retention_tier or "long",
            "provenance": row.provenance or {},
        }

    @staticmethod
    def _is_valid(row: StructuredMemoryTable, now: datetime) -> bool:
        valid_from = row.valid_from or row.created_at
        if valid_from is not None:
            if valid_from.tzinfo is None:
                valid_from = valid_from.replace(tzinfo=timezone.utc)
            if valid_from.astimezone(timezone.utc) > now:
                return False
        if row.valid_until is None:
            return True
        valid_until = row.valid_until
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=timezone.utc)
        return valid_until.astimezone(timezone.utc) > now

    async def read_active(self, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        if kind and kind not in self._KINDS:
            raise ValueError("Unknown memory kind.")
        async with self.db.session_factory() as session:
            now = datetime.now(timezone.utc)
            rows = [
                row for row in await self._latest(session)
                if row.status == "active" and self._is_valid(row, now)
            ]
            if kind:
                rows = [row for row in rows if row.kind == kind]
            rows.sort(key=lambda row: (row.confidence, row.created_at), reverse=True)
            return [self._public(row) for row in rows[:limit]]

    async def _append(self, session, memory_key: str, data: dict[str, Any],
                      status: str = "active", current: StructuredMemoryTable | None = None) -> dict[str, Any]:
        if status not in self._STATUSES:
            raise ValueError("Unknown memory status.")
        if current is None:
            now = datetime.now(timezone.utc)
            active = [
                row for row in await self._latest(session)
                if row.status == "active" and self._is_valid(row, now)
            ]
            if len(active) >= self.max_active:
                raise ValueError(f"Active structured memory limit reached ({self.max_active}).")
        row = StructuredMemoryTable(
            id=uuid.uuid4().hex,
            memory_key=memory_key,
            revision=(current.revision + 1) if current else 1,
            status=status,
            supersedes_id=current.id if current else None,
            **data,
        )
        session.add(row)
        return self._public(row)

    @skill()
    async def remember(self, kind: str, subject: str, predicate: str, value: str,
                       source: str | None = None, confidence: float = 0.8,
                       memory_key: str | None = None, provenance: dict[str, Any] | None = None,
                       valid_from: str | None = None, valid_until: str | None = None,
                       retention_tier: str = "long") -> SkillResult:
        """Create one durable fact/trait; use revise_memory for corrections."""
        try:
            data = self._normalized(
                kind, subject, predicate, value, source, confidence, provenance,
                valid_from, valid_until, retention_tier,
            )
            key = self._text(memory_key, 128, "memory_key", required=False) or uuid.uuid4().hex
            async with self.db.session_factory() as session:
                if await self._current(session, key):
                    return SkillResult.fail(f"Memory key '{key}' already exists; use revise_memory.")
                result = await self._append(session, key, data)
                await session.commit()
            return SkillResult.ok(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        except (TypeError, ValueError) as exc:
            return SkillResult.fail(str(exc))

    @skill()
    async def revise_memory(self, memory_key: str, kind: str | None = None, subject: str | None = None,
                            predicate: str | None = None, value: str | None = None,
                            source: str | None = None, confidence: float | None = None,
                            provenance: dict[str, Any] | None = None,
                            valid_from: str | None = None, valid_until: str | None = None,
                            retention_tier: str | None = None) -> SkillResult:
        """Append a corrected revision while preserving the previous row."""
        try:
            key = self._text(memory_key, 128, "memory_key")
            async with self.db.session_factory() as session:
                current = await self._current(session, key)
                if current is None or current.status != "active":
                    return SkillResult.fail(f"Memory key '{key}' not found.")
                data = self._normalized(
                    kind or current.kind, subject or current.subject, predicate or current.predicate,
                    value or current.value, source if source is not None else current.source,
                    confidence if confidence is not None else current.confidence,
                    provenance if provenance is not None else current.provenance,
                    valid_from if valid_from is not None else current.valid_from,
                    valid_until if valid_until is not None else current.valid_until,
                    retention_tier if retention_tier is not None else (current.retention_tier or "long"),
                )
                result = await self._append(session, key, data, current=current)
                await session.commit()
            return SkillResult.ok(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        except (TypeError, ValueError) as exc:
            return SkillResult.fail(str(exc))

    async def _close(self, memory_key: str, status: str, reason: str = "") -> SkillResult:
        try:
            key = self._text(memory_key, 128, "memory_key")
            reason = self._text(reason, 1000, "reason", required=False)
            async with self.db.session_factory() as session:
                current = await self._current(session, key)
                if current is None:
                    return SkillResult.fail(f"Active memory key '{key}' not found.")
                data = self._normalized(current.kind, current.subject, current.predicate, current.value,
                                        current.source, current.confidence,
                                        {**(current.provenance or {}), **({"close_reason": reason} if reason else {})},
                                        current.valid_from, current.valid_until,
                                        current.retention_tier or "long")
                result = await self._append(session, key, data, status=status, current=current)
                await session.commit()
            return SkillResult.ok(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        except (TypeError, ValueError) as exc:
            return SkillResult.fail(str(exc))

    @skill()
    async def forget_memory(self, memory_key: str, reason: str = "") -> SkillResult:
        """Append a forgotten revision; history remains auditable."""
        return await self._close(memory_key, "forgotten", reason)

    @skill()
    async def archive_memory(self, memory_key: str, reason: str = "") -> SkillResult:
        """Append an archived revision; archived rows are excluded from prompt context."""
        return await self._close(memory_key, "archived", reason)

    @skill()
    async def list_memories(self, kind: str | None = None, limit: int = 50) -> SkillResult:
        """Return bounded active structured memories as JSON."""
        try:
            rows = await self.read_active(kind, limit)
            return SkillResult.ok(json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
        except (TypeError, ValueError) as exc:
            return SkillResult.fail(str(exc))

    @staticmethod
    def _journal_day(value: Any) -> str:
        """Validate the canonical UTC calendar key used by daily journals."""

        day = str(value or "").strip()
        try:
            parsed = date.fromisoformat(day)
        except ValueError as exc:
            raise ValueError("day must use YYYY-MM-DD format") from exc
        if parsed.isoformat() != day:
            raise ValueError("day must use YYYY-MM-DD format")
        return day

    @staticmethod
    def _journal_commitments(value: Any) -> list[str]:
        """Keep task references bounded; task state remains canonical in TaskTable."""

        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("commitment_ids must be an array")
        result: list[str] = []
        for item in value[:20]:
            commitment_id = str(item).strip()
            if not commitment_id or len(commitment_id) > 64:
                raise ValueError("commitment_ids must contain bounded non-empty IDs")
            if commitment_id not in result:
                result.append(commitment_id)
        if len(value) > 20:
            raise ValueError("commitment_ids cannot contain more than 20 IDs")
        return result

    async def read_daily_journal(
        self, day: str | None = None, limit: int = 7
    ) -> list[dict[str, Any]]:
        """Read active canonical daily summaries without creating a second store."""

        requested_day = self._journal_day(day) if day is not None else None
        limit = max(1, min(int(limit), 31))
        async with self.db.session_factory() as session:
            now = datetime.now(timezone.utc)
            rows = [
                row
                for row in await self._latest(session)
                if row.kind == "summary"
                and row.subject == "daily_journal"
                and row.status == "active"
                and self._is_valid(row, now)
            ]
            if requested_day is not None:
                rows = [
                    row
                    for row in rows
                    if (row.provenance or {}).get("day") == requested_day
                ]
            rows.sort(
                key=lambda row: (row.valid_from or row.created_at, row.created_at),
                reverse=True,
            )
            return [self._public(row) for row in rows[:limit]]

    @skill(subconscious=[Pattern.CONSOLIDATION])
    async def record_daily_journal(
        self,
        day: str,
        summary: str,
        commitment_ids: list[str] | None = None,
        source: str = "subconscious.consolidation",
    ) -> SkillResult:
        """Upsert one bounded daily summary as an append-only memory revision.

        The summary is stored in JAWL's canonical structured-memory table.  It
        may reference task IDs, but task status and lifecycle remain owned by
        ``TaskTable`` rather than being copied into the journal.
        """

        try:
            journal_day = self._journal_day(day)
            summary_text = self._text(summary, 4000, "summary")
            commitments = self._journal_commitments(commitment_ids)
            source_text = self._text(source, 256, "source")
            data = self._normalized(
                "summary",
                "daily_journal",
                "day",
                summary_text,
                source_text,
                0.75,
                {"day": journal_day, "commitment_ids": commitments},
                valid_from=f"{journal_day}T00:00:00+00:00",
                retention_tier="standard",
            )
            memory_key = f"journal:{journal_day}"
            async with self.db.session_factory() as session:
                current = await self._current(session, memory_key)
                result = await self._append(
                    session, memory_key, data, current=current
                )
                await session.commit()
            return SkillResult.ok(
                json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            )
        except (TypeError, ValueError) as exc:
            return SkillResult.fail(str(exc))

    @skill()
    async def list_daily_journal(
        self, day: str | None = None, limit: int = 7
    ) -> SkillResult:
        """Return bounded daily summaries from canonical JAWL memory."""

        try:
            rows = await self.read_daily_journal(day=day, limit=limit)
            return SkillResult.ok(
                json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
            )
        except (TypeError, ValueError) as exc:
            return SkillResult.fail(str(exc))

    @skill(subconscious=[Pattern.FORGETTING])
    async def archive_expired_memories(self, limit: int = 100) -> SkillResult:
        """Archive expired active revisions while preserving their history."""

        try:
            limit = max(1, min(int(limit), 100))
            async with self.db.session_factory() as session:
                now = datetime.now(timezone.utc)
                expired = [
                    row
                    for row in await self._latest(session)
                    if row.status == "active"
                    and row.valid_until is not None
                    and not self._is_valid(row, now)
                ][:limit]
                archived = []
                for current in expired:
                    valid_from = current.valid_from or current.created_at or now
                    data = self._normalized(
                        current.kind,
                        current.subject,
                        current.predicate,
                        current.value,
                        current.source,
                        current.confidence,
                        {
                            **(current.provenance or {}),
                            "close_reason": "validity_expired",
                        },
                        valid_from,
                        current.valid_until,
                        current.retention_tier or "long",
                    )
                    archived.append(
                        await self._append(
                            session,
                            current.memory_key,
                            data,
                            status="archived",
                            current=current,
                        )
                    )
                await session.commit()
            return SkillResult.ok(
                json.dumps(
                    {"archived": archived, "count": len(archived)},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        except (TypeError, ValueError) as exc:
            return SkillResult.fail(str(exc))

    async def get_context_block(self, **kwargs: Any) -> str:
        rows = await self.read_active(limit=self.context_limit)
        if not rows:
            return ""
        lines = ["STRUCTURED MEMORY (JAWL canonical; active revisions only)"]
        for row in rows:
            text = f"[{row['memory_key']}] {row['kind']}: {row['subject']} — {row['predicate']} = {row['value']}"
            lines.append(truncate_text(text, max_chars=460, suffix="...[Truncated]"))
        return "\n".join(lines)
