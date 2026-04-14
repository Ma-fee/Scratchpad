from __future__ import annotations

import pytest

from mcp_scratchpad.memory.models import PublishMemoryRequest


def test_publish_request_accepts_valid_namespace_and_key() -> None:
    request = PublishMemoryRequest(
        session_id="session-1",
        source_path="/workspace/summary.md",
        target_namespace="users",
        target_key="user-42/summary.md",
    )

    assert request.target_namespace == "users"
    assert request.target_key == "user-42/summary.md"


@pytest.mark.parametrize(
    ("namespace", "target_key"),
    [
        ("invalid", "x.md"),
        ("users", "../escape.md"),
        ("users", "/absolute.md"),
        ("users", ""),
    ],
)
def test_publish_request_rejects_invalid_target_inputs(
    namespace: str,
    target_key: str,
) -> None:
    with pytest.raises(ValueError):
        PublishMemoryRequest(
            session_id="session-1",
            source_path="/workspace/summary.md",
            target_namespace=namespace,
            target_key=target_key,
        )
