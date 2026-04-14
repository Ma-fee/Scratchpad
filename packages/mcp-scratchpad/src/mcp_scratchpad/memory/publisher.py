from __future__ import annotations

from collections.abc import Mapping

from ..fs.unified_adapter import UnifiedSessionFSAdapter
from .backends import SharedMemoryBackend
from .models import PublishMemoryRequest, PublishMemoryResult


class PublishMemoryService:
    """Promote a session-visible file into shared memory."""

    def __init__(
        self,
        *,
        adapter: UnifiedSessionFSAdapter,
        backend_by_namespace: Mapping[str, SharedMemoryBackend],
    ) -> None:
        self._adapter = adapter
        self._backend_by_namespace = dict(backend_by_namespace)

    def publish(self, request: PublishMemoryRequest) -> PublishMemoryResult:
        backend = self._backend_by_namespace.get(request.target_namespace)
        if backend is None:
            raise ValueError(
                "No shared memory backend configured for namespace: "
                f"{request.target_namespace}"
            )

        read_result = self._adapter.read_text(request.session_id, request.source_path)
        backend_result = backend.publish_text(
            namespace=request.target_namespace,
            target_key=request.target_key,
            content=read_result.content,
            overwrite=request.overwrite,
            metadata=request.metadata,
            content_type=request.content_type,
        )
        return PublishMemoryResult(
            session_id=request.session_id,
            source_path=request.source_path,
            target_namespace=request.target_namespace,
            target_key=request.target_key,
            shared_path=backend_result.shared_path,
            backend_uri=backend_result.backend_uri,
            content_type=request.content_type,
            published=True,
            overwrote_existing=backend_result.overwrote_existing,
        )
