import datetime
import json
import threading
from pathlib import Path
from typing import Any

from .exceptions import (
    FileTooLargeError,
    PermissionDeniedError,
    ScratchpadFileNotFoundError,
    StorageError,
)
from .models import FileRecord
from .utils import normalize_path


def _now() -> datetime.datetime:
    """统一的时间获取，方便测试和替换。"""
    return datetime.datetime.now(tz=datetime.timezone.utc)


def _iso(dt: datetime.datetime) -> str:
    """把时间转换为 ISO 字符串（附带 Z 结尾）。"""
    return dt.isoformat() + "Z"


def _from_iso(value: str | None) -> datetime.datetime:
    """容错地解析 ISO 字符串，失败时回退为当前时间。"""
    if not value:
        return _now()
    text = value[:-1] if value.endswith("Z") else value
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        return _now()


class FileSystemStore:
    """简单的文件系统后端，负责在 base_dir/{session_id} 下落盘存储。"""

    def __init__(
        self, base_dir: Path | None = None, size_limit_bytes: int = 10 * 1024 * 1024
    ) -> None:
        self.base_dir = base_dir or Path(__file__).resolve().parent.parent / "files"
        self.base_dir = Path(self.base_dir)  # 确保是Path对象
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.size_limit_bytes = size_limit_bytes
        self.lock = threading.Lock()
        self._session_id: str = "default"
        self.metadata: dict[str, dict[str, dict[str, Any]]] = {}

    @property
    def session_id(self) -> str:
        """获取当前 session_id，如果没有设置则返回默认值。"""
        return self._session_id

    @session_id.setter
    def session_id(self, value: str) -> None:
        """设置当前 session_id。"""
        self._session_id = value or "default"

    def _session_dir(self) -> Path:
        """获取当前 session 的目录。"""
        return self.base_dir / self._session_id

    def _meta_path(self) -> Path:
        return self._session_dir() / ".metadata.json"

    def _load_metadata(self) -> dict[str, dict[str, Any]]:
        """缓存并读取 metadata，避免重复 IO。"""
        if self._session_id in self.metadata:
            return self.metadata[self._session_id]
        meta_path = self._meta_path()
        if meta_path.exists():
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                raise StorageError(
                    "Failed to load metadata",
                    details={"error": str(e)},
                ) from e
        else:
            data = {}
        self.metadata[self._session_id] = data
        return data

    def _save_metadata(self) -> None:
        try:
            session_dir = self._session_dir()
            session_dir.mkdir(parents=True, exist_ok=True)
            meta_path = self._meta_path()
            data = self.metadata.get(self._session_id, {})
            meta_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as e:
            raise StorageError(
                "Failed to save metadata",
                details={"error": str(e)},
            ) from e

    def _build_record(
        self,
        rel_path: str,
        content: str,
        meta: dict[str, Any],
        size_override: int | None = None,
    ) -> FileRecord:
        """把 metadata + 文件内容组装为 FileRecord。"""
        created = _from_iso(meta.get("created_at"))
        updated = _from_iso(meta.get("updated_at"))
        size = (
            size_override if size_override is not None else len(content.encode("utf-8"))
        )
        permission = meta.get("permission", "read_write")
        version = meta.get("version") or meta.get("revision", 1)
        return FileRecord(
            file_path=rel_path,
            name=rel_path.split("/")[-1],
            content=content,
            persistent=meta.get("persistent", False),
            permission=permission,
            created_at=created,
            updated_at=updated,
            size=size,
            version=version,
        )

    def list_files(
        self,
        persistent: bool | None,
        keyword: str | None,
        namespace: str | None,
        agent_name: str | None,
    ) -> list[FileRecord]:
        """扫描目录并返回符合筛选条件的 FileRecord 列表。"""
        with self.lock:
            session_dir = self._session_dir()
            session_dir.mkdir(parents=True, exist_ok=True)
            metadata = self._load_metadata()
            records: list[FileRecord] = []
            changed = False
            for path in session_dir.rglob("*"):
                if not path.is_file() or path.name == ".metadata.json":
                    continue
                rel = path.relative_to(session_dir).as_posix()
                try:
                    content = path.read_text(encoding="utf-8")
                except OSError:
                    # 跳过无法读取的文件，但记录错误
                    continue
                meta = metadata.get(rel)
                if not meta:
                    now = _now()
                    meta = {
                        "persistent": False,
                        "permission": "read_write",
                        "version": 1,
                        "created_at": _iso(now),
                        "updated_at": _iso(now),
                    }
                    metadata[rel] = meta
                    changed = True
                records.append(self._build_record(rel, content, meta))

            if changed:
                self._save_metadata()

            if persistent is not None:
                records = [r for r in records if r.persistent == persistent]
            if keyword:
                records = [r for r in records if keyword in r.name]
            if namespace:
                records = [
                    r for r in records if r.file_path.startswith(f"{namespace}/")
                ]
            if agent_name:
                prefix = f"session/{agent_name}/"
                records = [r for r in records if r.file_path.startswith(prefix)]
            return sorted(records, key=lambda r: r.updated_at, reverse=True)

    def read_files(self, paths: list[str]) -> tuple[list[FileRecord], list[str]]:
        """批量读取文件，返回成功的记录及失败的路径。"""
        ok: list[FileRecord] = []
        failed: list[str] = []
        with self.lock:
            session_dir = self._session_dir()
            session_dir.mkdir(parents=True, exist_ok=True)
            metadata = self._load_metadata()
            for raw in paths:
                try:
                    rel = normalize_path(raw)
                except ValueError:
                    failed.append(raw)
                    continue
                file_path = session_dir / rel
                if not file_path.exists():
                    failed.append(rel)
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8")
                except OSError:
                    failed.append(rel)
                    continue
                size = len(content.encode("utf-8"))
                meta = metadata.get(rel)
                if not meta:
                    now = _now()
                    meta = {
                        "persistent": False,
                        "permission": "read_write",
                        "version": 1,
                        "created_at": _iso(now),
                        "updated_at": _iso(now),
                    }
                    metadata[rel] = meta
                    self._save_metadata()
                ok.append(self._build_record(rel, content, meta, size_override=size))
        return ok, failed

    def write_file(
        self,
        file_path: str,
        content: str,
        overwrite: bool,
        persistent: bool,
        expected_version: int | None,
        permission: str | None,
    ) -> FileRecord:
        """写入文件并同步 metadata，支持 size 限制与乐观锁。"""
        rel_path = normalize_path(file_path)
        encoded_size = len(content.encode("utf-8"))
        if encoded_size > self.size_limit_bytes:
            raise FileTooLargeError(
                f"File size {encoded_size} bytes exceeds limit of {self.size_limit_bytes} bytes",
                details={
                    "file_path": rel_path,
                    "actual_size": encoded_size,
                    "size_limit": self.size_limit_bytes,
                },
            )

        with self.lock:
            session_dir = self._session_dir()
            session_dir.mkdir(parents=True, exist_ok=True)
            metadata = self._load_metadata()
            full_file_path = session_dir / rel_path
            meta = metadata.get(rel_path)
            exists = full_file_path.exists()
            if exists and not overwrite:
                raise StorageError(
                    f"File already exists: {rel_path}",
                    details={"file_path": rel_path, "operation": "write"},
                )
            current_version = (
                (meta.get("version") or meta.get("revision") or 1) if meta else None
            )
            if (
                expected_version
                and current_version
                and expected_version != current_version
            ):
                raise StorageError(
                    f"Version conflict for file {rel_path}: expected {expected_version}, got {current_version}",
                    details={
                        "file_path": rel_path,
                        "expected_version": expected_version,
                        "current_version": current_version,
                    },
                )

            full_file_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                full_file_path.write_text(content, encoding="utf-8")
            except OSError as e:
                raise StorageError(
                    f"Failed to write file {rel_path}",
                    details={"file_path": rel_path, "error": str(e)},
                ) from e
            now = _now()
            if not meta:
                meta = {
                    "persistent": persistent,
                    "permission": permission or "read_write",
                    "version": 1,
                    "created_at": _iso(now),
                    "updated_at": _iso(now),
                }
            else:
                meta["persistent"] = persistent
                meta["permission"] = permission or meta.get("permission", "read_write")
                meta["version"] = (meta.get("version") or meta.get("revision") or 1) + 1
                meta.setdefault("created_at", _iso(now))
                meta["updated_at"] = _iso(now)
            metadata[rel_path] = meta
            self._save_metadata()

            return self._build_record(
                rel_path, content, meta, size_override=encoded_size
            )

    def remove_file(
        self,
        path: str,
        expected_version: int | None,
        force: bool,
    ) -> FileRecord:
        """删除文件并返回删除前的记录，供审计或回显使用。"""
        rel_path = normalize_path(path)
        with self.lock:
            session_dir = self._session_dir()
            session_dir.mkdir(parents=True, exist_ok=True)
            metadata = self._load_metadata()
            file_path = session_dir / rel_path
            if not file_path.exists():
                raise ScratchpadFileNotFoundError(
                    f"File not found: {rel_path}", details={"file_path": rel_path}
                )
            meta = metadata.get(rel_path)
            current_version = (
                (meta.get("version") or meta.get("revision") or 1) if meta else None
            )
            if (
                expected_version
                and current_version
                and expected_version != current_version
            ):
                raise StorageError(
                    f"Version conflict for file {rel_path}: expected {expected_version}, got {current_version}",
                    details={
                        "file_path": rel_path,
                        "expected_version": expected_version,
                        "current_version": current_version,
                    },
                )
            if meta and meta.get("persistent") and not force:
                raise PermissionDeniedError(
                    f"Cannot remove persistent file {rel_path} without force flag",
                    details={"file_path": rel_path, "persistent": True},
                )
            try:
                content = file_path.read_text(encoding="utf-8")
            except OSError as e:
                raise StorageError(
                    f"Failed to read file {rel_path} before removal",
                    details={"file_path": rel_path, "error": str(e)},
                ) from e
            record = self._build_record(rel_path, content, meta or {})
            file_path.unlink()
            if rel_path in metadata:
                metadata.pop(rel_path)
                self._save_metadata()
            return record


# 全局store实例，支持延迟初始化
_store: FileSystemStore | None = None


def get_store() -> FileSystemStore:
    """获取全局store实例，如果未初始化则使用默认配置创建。"""
    global _store
    if _store is None:
        _store = FileSystemStore()
    return _store


def set_store(store: FileSystemStore) -> None:
    """设置全局store实例。"""
    global _store
    _store = store


# 向后兼容：保持原有的store变量
store = get_store()
