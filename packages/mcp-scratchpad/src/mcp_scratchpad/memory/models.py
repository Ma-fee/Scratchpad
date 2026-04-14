from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..utils import normalize_path

SUPPORTED_MEMORY_NAMESPACES = ("shared", "users", "agents", "teams")


class PublishMemoryRequest(BaseModel):
    """Validated publish request payload."""

    session_id: str = Field(..., min_length=1)
    source_path: str = Field(..., min_length=1)
    target_namespace: Literal["shared", "users", "agents", "teams"]
    target_key: str = Field(..., min_length=1)
    overwrite: bool = False
    content_type: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("source_path")
    @classmethod
    def _validate_source_path(cls, value: str) -> str:
        return f"/{normalize_path(value).lstrip('/')}"

    @field_validator("target_key")
    @classmethod
    def _validate_target_key(cls, value: str) -> str:
        if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
            raise ValueError("target_key must be relative")

        normalized = normalize_path(value)
        if normalized in {"", "."}:
            raise ValueError("target_key cannot be empty")

        return normalized


class PublishMemoryResult(BaseModel):
    """Structured publish result."""

    session_id: str
    source_path: str
    target_namespace: str
    target_key: str
    shared_path: str
    backend_uri: str
    content_type: str | None = None
    published: bool = True
    overwrote_existing: bool = False
