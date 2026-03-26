"""Security utilities for MCP Scratchpad.

This package provides security-related utilities including:
- Credential masking for secure logging
- Path security validation
- Session isolation enforcement
- Audit logging and resource lifecycle tracking
"""

from __future__ import annotations

from .audit_logger import (
    AuditEvent,
    EventType,
    ResourceLifecycleTracker,
    create_lifecycle_tracker,
    get_default_tracker,
    reset_default_tracker,
)
from .credential_masker import (
    DEFAULT_MASKING_RULES,
    MaskingRule,
    create_secure_log_filter,
    likely_contains_credentials,
    mask_dict_sensitive_data,
    mask_exception_message,
    mask_sensitive_data,
)

__all__ = [
    "DEFAULT_MASKING_RULES",
    "MaskingRule",
    "create_secure_log_filter",
    "likely_contains_credentials",
    "mask_dict_sensitive_data",
    "mask_exception_message",
    "mask_sensitive_data",
    "AuditEvent",
    "EventType",
    "ResourceLifecycleTracker",
    "create_lifecycle_tracker",
    "get_default_tracker",
    "reset_default_tracker",
]
