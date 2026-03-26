from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

ALLOWED_PERMISSIONS = {"read", "read_write"}


@dataclass
class FileRecord:
    """表示存储层中的单个文件及其元数据。"""

    file_path: str
    name: str
    content: str
    persistent: bool = False
    permission: str = "read"
    created_at: datetime.datetime = field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = field(default_factory=datetime.datetime.utcnow)
    size: int = 0
    version: int = 1

    def _namespace(self) -> str:
        return self.file_path.split("/", 1)[0] if "/" in self.file_path else "session"

    def to_metadata(self) -> dict[str, Any]:
        """把 dataclass 转成便于序列化的字典。"""
        return {
            "file_path": self.file_path,
            "name": self.name,
            "size": self.size,
            "content_type": "text/markdown",
            "created_at": self.created_at.isoformat() + "Z",
            "updated_at": self.updated_at.isoformat() + "Z",
            "persistent": self.persistent,
            "line_count": self.content.count("\n") + 1 if self.content else 0,
            "permission": self.permission,
            "namespace": self._namespace(),
            "version": self.version,
        }


class ListFilesRequest(BaseModel):
    """列举文件并支持多条件筛选。"""

    persistent: bool | None = Field(
        None, description="true: 仅持久化；false: 仅临时；None: 全部"
    )
    keyword: str | None = Field(None, description="按文件名模糊匹配的关键字")
    namespace: str | None = Field(None, description="命名空间，例如 session 或 kb")
    agent_name: str | None = Field(None, description="仅返回指定 Agent 的文件")


class FileReadSlice(BaseModel):
    file_path: str = Field(..., description="要读取的文件路径")
    start_line: int | None = Field(None, ge=1, description="起始行号（从 1 开始）")
    end_line: int | None = Field(
        None, ge=1, description="结束行号（必须大于等于起始行号）"
    )

    @field_validator("end_line")
    @classmethod
    def _validate_line_range(cls, v, info):
        start = info.data.get("start_line")
        if v is not None and start is not None and v < start:
            raise ValueError("end_line must be >= start_line")
        return v


class ReadFileRequest(BaseModel):
    """读取一个或多个文件内容。"""

    file_requests: list[FileReadSlice] | None = Field(
        None, min_length=1, description="详细文件读取请求列表"
    )
    file_paths: list[str] | None = Field(
        None, min_length=1, description="简化模式：指定一个或多个文件路径"
    )


class WriteFileRequest(BaseModel):
    """创建或更新文件。"""

    file_path: str = Field(..., description="文件路径")
    content: str = Field(..., description="UTF-8 文本内容")
    expected_version: int | None = Field(None, ge=1, description="乐观锁：预期版本号")
    permission: str | None = Field(None, description="read 或 read_write")
    overwrite: bool = Field(
        True, description="若存在是否覆盖，默认允许覆盖以提升用户体验"
    )
    persistent: bool = Field(False, description="是否写入持久化文件夹")

    @model_validator(mode="after")
    def _validate_request(self) -> WriteFileRequest:
        permission = self.permission
        if permission and permission not in ALLOWED_PERMISSIONS:
            raise ValueError("permission must be read or read_write")
        return self


class RemoveFileRequest(BaseModel):
    """删除文件。"""

    file_path: str = Field(..., description="目标文件路径")
    expected_version: int | None = Field(None, ge=1, description="乐观锁：预期版本号")
    force: bool = Field(False, description="删除 persistent=true 的文件时是否强制执行")


class EditOperation(BaseModel):
    """单个编辑操作。"""

    oldString: str = Field(..., description="要替换的文本（必须与文件内容完全匹配，包括所有空白和缩进）")
    newString: str = Field(..., description="替换后的文本（必须与 oldString 不同）")
    replaceAll: bool = Field(False, description="是否替换所有出现的 oldString（默认为 false）")

    @model_validator(mode="after")
    def _validate_edit_operation(self) -> EditOperation:
        if self.oldString == self.newString:
            raise ValueError("oldString and newString must be different")
        return self
