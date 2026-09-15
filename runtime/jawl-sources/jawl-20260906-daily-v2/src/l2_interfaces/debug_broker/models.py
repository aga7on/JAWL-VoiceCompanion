"""Data models shared by the debug broker and its model-facing skills."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


def schema_digest(schema: dict[str, Any]) -> str:
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class DebugSession:
    provider: str
    target: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "created"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    provider_pid: int | None = None
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def touch(self, *, status: str | None = None, detail: str | None = None) -> None:
        if status is not None:
            self.status = status
        if detail is not None:
            self.detail = detail
        self.updated_at = time.time()

    def public(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["options"] = {
            key: value
            for key, value in self.options.items()
            if key.lower() not in {"token", "password", "secret", "authorization"}
        }
        return payload


@dataclass(frozen=True)
class OperationSpec:
    provider: str
    name: str
    description: str
    input_schema: dict[str, Any]
    session_required: bool = True
    mutating: bool = False
    minimum_access_level: int | None = None
    risk: str | None = None

    def __post_init__(self) -> None:
        """Derive one canonical policy label for every catalog operation."""

        level = self.minimum_access_level
        if level is None:
            level = 2 if self.mutating else 1
            object.__setattr__(self, "minimum_access_level", level)
        if level not in {0, 1, 2, 3}:
            raise ValueError("minimum_access_level must be between 0 and 3")
        if self.risk is None:
            object.__setattr__(self, "risk", "mutating" if self.mutating else "observe")

    @property
    def schema_sha256(self) -> str:
        return schema_digest(self.input_schema)

    def public(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "operation": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "schema_sha256": self.schema_sha256,
            "session_required": self.session_required,
            "mutating": self.mutating,
            "minimum_access_level": self.minimum_access_level,
            "risk": self.risk,
        }
