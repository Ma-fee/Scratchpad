# FastMCP 实现技术规范

## 1. 技术实现概述

本文档提供了将 mcp_scratchpad 迁移到 FastMCP 的详细技术实现规范，包括具体的代码结构、接口定义和实现细节。

## 2. 核心文件实现规范

### 2.1 新的 FastMCP 服务器 (`src/mcp_scratchpad/server.py`)

```python
"""
FastMCP 服务器主入口文件
提供 stdio 和 SSE 传输支持，保持与现有实现的兼容性
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP, Context
from .storage import FileSystemStore, set_store
from .tools.file_tools import register_file_tools

def create_server(base_dir: Optional[Path] = None) -> FastMCP:
    """创建 FastMCP 服务器实例"""
    mcp = FastMCP(
        name="MCP Scratchpad",
        version="2.0.0",
        description="基于 FastMCP 的文件管理服务器"
    )
    
    # 初始化存储
    store = FileSystemStore(base_dir=base_dir)
    set_store(store)
    
    # 注册工具
    register_file_tools(mcp)
    
    return mcp

def main() -> None:
    """主入口函数，支持命令行参数"""
    parser = argparse.ArgumentParser(description="MCP Scratchpad FastMCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="传输方式")
    parser.add_argument("--host", default="0.0.0.0", help="SSE 主机地址")
    parser.add_argument("--port", type=int, default=8890, help="SSE 端口")
    parser.add_argument("--base-dir", type=str, default="out/files", help="文件存储基础目录")
    
    args = parser.parse_args()
    
    # 创建服务器
    base_dir = Path(args.base_dir).resolve() if args.base_dir else None
    mcp = create_server(base_dir)
    
    # 启动服务器
    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport="sse", host=args.host, port=args.port)

if __name__ == "__main__":
    main()
```

### 2.2 文件工具实现 (`src/mcp_scratchpad/tools/file_tools.py`)

```python
"""
FastMCP 文件操作工具实现
使用装饰器模式重构现有的 handler 函数
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastmcp import FastMCP, Context
from ..models import (
    ListScratchpadRequest,
    ReadFileRequest,
    WriteFileRequest,
    RemoveFileRequest,
    FileReadSlice
)
from ..storage import store
from ..utils import normalize_path, build_file_block

def register_file_tools(mcp: FastMCP) -> None:
    """注册所有文件操作工具到 FastMCP 服务器"""
    
    @mcp.tool
    async def list_files(
        session_id: str,
        persistent: Optional[bool] = None,
        keyword: Optional[str] = None,
        namespace: Optional[str] = None,
        agent_name: Optional[str] = None,
        ctx: Context
    ) -> Dict[str, Any]:
        """列出会话文件，支持多种过滤条件"""
        await ctx.info(f"正在列出会话 {session_id} 的文件")
        
        # 构建请求对象
        request = ListScratchpadRequest(
            session_id=session_id,
            persistent=persistent,
            keyword=keyword,
            namespace=namespace,
            agent_name=agent_name
        )
        
        # 调用现有的存储逻辑
        records = store.list_files(
            session_id=request.session_id,
            persistent=request.persistent,
            keyword=request.keyword,
            namespace=request.namespace,
            agent_name=request.agent_name,
        )
        
        await ctx.report_progress(100, 100, "文件列表获取完成")
        
        # 构建响应
        structured_files = [record.to_metadata() for record in records]
        preview_limit = min(len(records), 10)
        summary_lines = [
            f"找到 {len(records)} 个文件",
        ]
        
        if records:
            summary_lines.extend([
                "编号 | 路径 | 权限 | 持久化 | 版本 | 更新时间",
                "---- | ---- | ---- | ---- | ---- | ----"
            ])
            for idx, record in enumerate(records[:preview_limit], start=1):
                summary_lines.append(
                    f"{idx} | {record.file_path} | {record.permission} | {'是' if record.persistent else '否'} | v{record.version} | {record.updated_at.isoformat()}Z"
                )
        
        return {
            "files": structured_files,
            "total_files": len(records),
            "session_id": session_id,
            "summary": "\n".join(summary_lines)
        }
    
    @mcp.tool
    async def read_file(
        session_id: str,
        file_path: Optional[str] = None,
        file_paths: Optional[List[str]] = None,
        file_requests: Optional[List[Dict[str, Any]]] = None,
        ctx: Context
    ) -> Dict[str, Any]:
        """读取文件内容，支持单个或多个文件"""
        await ctx.info("正在读取文件内容")
        
        # 构建请求对象
        request = ReadFileRequest(
            session_id=session_id,
            file_path=file_path,
            file_paths=file_paths,
            file_requests=file_requests
        )
        
        # 解析请求
        requests = _resolve_requests(request)
        normalized_paths = []
        for req in requests:
            try:
                normalized_paths.append(normalize_path(req.file_path))
            except ValueError:
                normalized_paths.append(None)
        
        # 读取文件
        valid_unique_paths = _deduplicate([p for p in normalized_paths if p])
        ok_records, failed = store.read_files(session_id, valid_unique_paths)
        record_map = {record.file_path: record for record in ok_records}
        failed_set = set(failed)
        
        # 构建响应
        content_blocks = []
        structured_files = []
        
        for idx, (req, normalized) in enumerate(zip(requests, normalized_paths), start=1):
            if not normalized or normalized in failed_set:
                structured_files.append({
                    "file_path": req.file_path,
                    "status": "error",
                    "error_code": "FILE_NOT_FOUND" if normalized else "INVALID_FILE_NAME"
                })
                continue
            
            record = record_map.get(normalized)
            if not record:
                structured_files.append({
                    "file_path": normalized,
                    "status": "error",
                    "error_code": "FILE_MISSING"
                })
                continue
            
            # 提取内容片段
            snippet, (start, end) = _extract_content_slice(
                record.content, req.start_line, req.end_line
            )
            block = build_file_block(record.file_path, snippet, start, end)
            content_blocks.append(block)
            
            meta = record.to_metadata()
            meta.update({
                "status": "ok",
                "requested_start_line": req.start_line,
                "requested_end_line": req.end_line,
                "start_line": start,
                "end_line": end,
            })
            structured_files.append(meta)
        
        await ctx.report_progress(100, 100, "文件读取完成")
        
        return {
            "files": structured_files,
            "total_files": len(structured_files),
            "session_id": session_id,
            "content": content_blocks
        }
    
    @mcp.tool
    async def write_file(
        session_id: str,
        mode: str,
        file_name: Optional[str] = None,
        agent_name: Optional[str] = None,
        file_path: Optional[str] = None,
        content: str = "",
        expected_version: Optional[int] = None,
        permission: Optional[str] = None,
        overwrite: bool = False,
        persistent: bool = False,
        ctx: Context
    ) -> Dict[str, Any]:
        """写入文件内容"""
        await ctx.info(f"正在写入文件: {file_name or file_path}")
        await ctx.report_progress(25, 100, "准备写入")
        
        # 构建请求对象
        request = WriteFileRequest(
            session_id=session_id,
            mode=mode,
            file_name=file_name,
            agent_name=agent_name,
            file_path=file_path,
            content=content,
            expected_version=expected_version,
            permission=permission,
            overwrite=overwrite,
            persistent=persistent
        )
        
        # 确定目标路径
        if request.mode == "create":
            target_path = _compose_session_path(request.agent_name or "", request.file_name or "")
            overwrite = request.overwrite
        else:
            target_path = _normalize_update_path(request.file_path or "")
            overwrite = True
        
        await ctx.report_progress(50, 100, "正在写入文件")
        
        # 写入文件
        record = store.write_file(
            session_id=request.session_id,
            file_path=target_path,
            content=request.content,
            overwrite=overwrite,
            persistent=request.persistent,
            expected_version=request.expected_version,
            permission=request.permission,
        )
        
        await ctx.report_progress(100, 100, "文件写入完成")
        
        operation = "created" if record.version == 1 else "updated"
        structured = record.to_metadata()
        structured.update({"operation": operation, "session_id": session_id})
        
        return structured
    
    @mcp.tool
    async def remove_file(
        session_id: str,
        file_path: str,
        expected_version: Optional[int] = None,
        force: bool = False,
        ctx: Context
    ) -> Dict[str, Any]:
        """删除文件"""
        await ctx.info(f"正在删除文件: {file_path}")
        await ctx.report_progress(50, 100, "正在删除")
        
        # 构建请求对象
        request = RemoveFileRequest(
            session_id=session_id,
            file_path=file_path,
            expected_version=expected_version,
            force=force
        )
        
        # 删除文件
        removed = store.remove_file(
            session_id=request.session_id,
            path=request.file_path,
            expected_version=request.expected_version,
            force=request.force,
        )
        
        await ctx.report_progress(100, 100, "文件删除完成")
        
        # 构建响应
        import datetime
        deleted_at = datetime.datetime.utcnow().isoformat() + "Z"
        actor = _infer_actor(removed.file_path)
        
        return {
            "file_path": removed.file_path,
            "name": removed.name,
            "deleted_at": deleted_at,
            "deleted_by": actor,
            "persistent_before": removed.persistent,
            "version": removed.version,
            "session_id": session_id,
        }

# 辅助函数（从现有 handlers 移植）
def _resolve_requests(payload: ReadFileRequest) -> List[FileReadSlice]:
    """把多种入参形式统一转换为 file_requests 列表"""
    if payload.file_requests:
        return [FileReadSlice(**req) if isinstance(req, dict) else req for req in payload.file_requests]
    if payload.file_path:
        return [FileReadSlice(file_path=payload.file_path)]
    if payload.file_paths:
        return [FileReadSlice(file_path=path) for path in payload.file_paths]
    raise ValueError("file_requests 或 file_path(s) 不能为空")

def _deduplicate(paths: List[str]) -> List[str]:
    """保持先出现者的顺序去重"""
    seen = set()
    ordered = []
    for path in paths:
        if path not in seen:
            ordered.append(path)
            seen.add(path)
    return ordered

def _extract_content_slice(text: str, start_line: Optional[int], end_line: Optional[int]):
    """根据请求的行范围切割文本"""
    lines = text.splitlines()
    total = len(lines)
    start_idx = max((start_line or 1) - 1, 0)
    end_idx = end_line if end_line else total
    end_idx = min(end_idx, total)
    selected = lines[start_idx:end_idx]
    numbered = [f"  {idx + start_idx + 1} | {line}" for idx, line in enumerate(selected)]
    snippet = "\n".join(numbered)
    actual_start = start_idx + 1
    actual_end = start_idx + len(selected)
    return snippet, (actual_start, actual_end)

def _compose_session_path(agent_name: str, file_name: str) -> str:
    """将 agent + 文件名拼成 session 下的相对路径"""
    if "/" in agent_name or "\\" in agent_name:
        raise ValueError("agent_name must not contain path separators")
    raw_path = f"session/{agent_name}/{file_name}"
    return normalize_path(raw_path)

def _normalize_update_path(file_path: str) -> str:
    """校验 update 模式下的路径只能指向 session 命名空间"""
    normalized = normalize_path(file_path)
    if not normalized.startswith("session/"):
        raise ValueError("仅允许写入 session 命名空间的文件")
    return normalized

def _infer_actor(file_path: str) -> str:
    """简单解析 session/{agent}/ 前缀"""
    if file_path.startswith("session/"):
        parts = file_path.split("/")
        if len(parts) >= 2:
            return parts[1]
    return "unknown"
```
### 2.3 FastMCP 配置文件 (`fastmcp.json`)

```json
{
  "name": "MCP Scratchpad",
  "version": "2.0.0",
  "description": "基于 FastMCP 的文件管理服务器",
  "entrypoint": "src/mcp_scratchpad/server.py",
  "environment": {
    "type": "uv",
    "python": ">=3.10",
    "dependencies": [
      "fastapi>=0.121.3",
      "httpx<1.0",
      "httpx-sse>=0.4.3",
      "pydantic>=2.12.4",
      "uvicorn>=0.38.0"
    ],
    "editable": ["."]
  },
  "transport": {
    "stdio": {
      "enabled": true
    },
    "sse": {
      "enabled": true,
      "host": "0.0.0.0",
      "port": 8890
    }
  }
}
```

### 2.4 FastMCP 工具注册示例

FastMCP 使用装饰器模式注册工具，所有工具函数都在 `tools/file_tools.py` 中实现：

```python
from fastmcp import FastMCP, Context
from .tools.file_tools import register_file_tools

mcp = FastMCP(name="MCP Scratchpad")

# 注册所有文件操作工具
register_file_tools(mcp)
```
```

### 2.4 FastMCP 配置文件 (`fastmcp.json`)

```json
{
  "name": "MCP Scratchpad",
  "version": "2.0.0",
  "description": "基于 FastMCP 的文件管理服务器",
  "entrypoint": "src/mcp_scratchpad/server.py",
  "environment": {
    "type": "uv",
    "python": ">=3.10",
    "dependencies": [
      "fastapi>=0.121.3",
      "httpx<1.0",
      "httpx-sse>=0.4.3",
      "pydantic>=2.12.4",
      "uvicorn>=0.38.0"
    ],
    "editable": ["."]
  },
  "transport": {
    "stdio": {
      "enabled": true
    },
    "sse": {
      "enabled": true,
      "host": "0.0.0.0",
      "port": 8890
    }
  }
}
```

## 3. 依赖更新规范

### 3.1 pyproject.toml 更新

```toml
[project]
name = "mcp-scratchpad"
version = "2.0.0"
description = "基于 FastMCP 的文件管理服务器"
readme = "README.md"
authors = [
    { name = "Leoyzen", email = "leoyzen@gmail.com" }
]
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.121.3",
    "httpx<1.0",
    "httpx-sse>=0.4.3",
    "fastmcp>=0.1.0",  # 替换 mcp>=1.22.0
    "pydantic>=2.12.4",
    "uvicorn>=0.38.0",
]

[build-system]
requires = ["uv_build>=0.9.8,<0.10.0"]
build-backend = "uv_build"

[project.scripts]
mcp-scratchpad = "mcp_scratchpad.server:main"
```

## 4. 兼容性保证

### 4.1 向后兼容性

- 保持所有现有的 HTTP API 端点
- 保持现有的请求/响应格式
- 保持现有的命令行参数
- 保持现有的文件存储格式

### 4.2 渐进式迁移

- 新旧服务器可以并存
- 提供配置选项选择使用哪个实现
- 逐步验证和切换

## 5. 测试策略

### 5.1 单元测试

- 测试每个 FastMCP 工具函数
- 测试与现有存储层的集成
- 测试错误处理

### 5.2 集成测试

- 测试 stdio 传输
- 测试 SSE 传输
- 测试 HTTP API 兼容性

### 5.3 性能测试

- 对比新旧实现的性能
- 确保性能不降级

## 6. 部署和运行

### 6.1 开发环境

```bash
# 安装依赖
uv sync

# 运行 stdio 模式
uv run python -m mcp_scratchpad.server

# 运行 SSE 模式
uv run python -m mcp_scratchpad.server --transport sse

# 运行 FastAPI
uv run python -m mcp_scratchpad.app
```

### 6.2 生产环境

```bash
# 使用 FastMCP 配置
fastmcp run fastmcp.json

# 或直接运行
uv run mcp-scratchpad --transport stdio
```

## 7. 监控和日志

### 7.1 日志集成

- 利用 FastMCP 的 Context 对象进行日志记录
- 保持与现有日志格式的兼容性

### 7.2 错误处理

- 统一的错误处理机制
- 详细的错误信息和状态码

## 8. 文档更新

### 8.1 README 更新

- 更新安装和运行说明
- 添加 FastMCP 相关信息

### 8.2 API 文档

- 更新 API 文档
- 添加新的配置选项说明

这个技术规范为具体的代码实现提供了详细的指导，确保迁移过程的一致性和完整性。
