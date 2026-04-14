"""Publish memory tool registration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastmcp import Context, FastMCP
from fastmcp.tools.tool import ToolResult
from pydantic import Field

from ..fs.unified_adapter import UnifiedSessionFSAdapter
from ..memory.backends import FileSharedMemoryBackend
from ..memory.models import PublishMemoryRequest
from ..memory.publisher import PublishMemoryService
from ..storage import get_store
from ..utils import build_error_xml, build_file_operation_xml, create_tool_result_xml

if TYPE_CHECKING:
    from ..fs import SessionFileSystemManager


def _build_backend_by_namespace(
    session_manager: SessionFileSystemManager,
) -> dict[str, FileSharedMemoryBackend]:
    backends: dict[str, FileSharedMemoryBackend] = {}
    namespaces = session_manager.config.memory.publish.namespaces

    for namespace, namespace_config in namespaces.items():
        if namespace_config.backend != "file":
            raise ValueError(
                f"Unsupported shared memory backend for namespace '{namespace}': "
                f"{namespace_config.backend}"
            )

        backends[namespace] = FileSharedMemoryBackend(
            root_dir=Path(namespace_config.root),
            namespace_roots={namespace: ""},
        )

    return backends


def register_publish_memory(
    mcp: FastMCP,
    session_manager: SessionFileSystemManager | None = None,
) -> None:
    """Register the publish_memory tool."""

    @mcp.tool(
        name="publish_memory",
        description="Publish a session-visible file into shared memory storage.",
    )
    async def publish_memory(
        ctx: Context,
        session_id: Annotated[str, Field(description="Session ID")],
        source_path: Annotated[
            str,
            Field(description="Session-visible source file path"),
        ],
        target_namespace: Annotated[str, Field(description="Shared namespace")],
        target_key: Annotated[
            str,
            Field(description="Relative key inside namespace"),
        ],
        overwrite: Annotated[bool, Field(description="Allow overwrite")] = False,
    ) -> ToolResult:
        try:
            if session_manager is None:
                raise ValueError("session_manager is required")

            await ctx.report_progress(25, 100, "Preparing shared publish")
            adapter = UnifiedSessionFSAdapter(
                session_manager=session_manager,
                store=get_store(),
                unified_enabled=True,
            )
            service = PublishMemoryService(
                adapter=adapter,
                backend_by_namespace=_build_backend_by_namespace(session_manager),
            )
            result = service.publish(
                PublishMemoryRequest(
                    session_id=session_id,
                    source_path=source_path,
                    target_namespace=target_namespace,
                    target_key=target_key,
                    overwrite=overwrite,
                )
            )
            await ctx.report_progress(100, 100, "Publish completed")
            payload = build_file_operation_xml(result.model_dump(), "publish_memory")
            return create_tool_result_xml(payload, result.model_dump())
        except Exception as exc:
            return create_tool_result_xml(
                build_error_xml(str(exc), "publish_memory"),
                {"error": str(exc)},
            )
