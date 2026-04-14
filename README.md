# mcp-scratchpad

`mcp-scratchpad` 是一个基于 FastMCP 的文件管理服务器，面向 Agent、IDE 和其他 MCP 客户端提供统一的 scratchpad 读写能力。服务支持 `stdio` 和 `SSE` 两种传输方式，内置会话隔离、路径安全校验、资源访问封装、健康检查和结构化日志。

## 核心能力

- 会话级文件管理：按 `session_id` 隔离文件读写上下文
- 多传输方式：支持 `stdio` 和 `SSE`
- Overlay/FS 抽象：支持本地文件系统、内存文件系统，以及可选的 S3 后端
- 资源访问能力：支持文本、图片、二进制等资源读取
- 安全保护：路径校验、资源限制、审计与敏感信息脱敏
- 运行监控：健康检查、系统信息和存储状态工具

## 环境要求

- Python `>=3.10`
- 使用 `uv` 管理依赖和运行命令

## 安装

基础安装：

```bash
cd packages/mcp-scratchpad
uv sync
```

安装测试与开发依赖：

```bash
uv sync --group test
```

如果需要 S3 后端支持：

```bash
uv sync --extra s3
```

## 启动服务

默认以 `stdio` 方式启动：

```bash
uv run mcp-scratchpad
```

也可以直接运行模块入口：

```bash
uv run python -m mcp_scratchpad.server
```

以 `SSE` 方式启动：

```bash
uv run mcp-scratchpad --transport sse --host 0.0.0.0 --port 8890
```

指定基础目录：

```bash
uv run mcp-scratchpad --base-dir /path/to/files
```

## 配置

环境变量统一使用 `MCP_SCRATCHPAD_` 前缀。

常用配置项：

- `MCP_SCRATCHPAD_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR`
- `MCP_SCRATCHPAD_LOG_FORMAT=text|json`
- `MCP_SCRATCHPAD_BASE_DIR=/path/to/base-dir`

当 `MCP_SCRATCHPAD_LOG_FORMAT=json` 时，服务会启用 `structlog` 输出 JSON 日志。

## 主要工具

服务暴露的工具主要分为三类。

文件操作：

- `list_files`：列出会话文件，支持按关键字、命名空间、持久化状态等过滤
- `read_file`：读取单个或多个文件内容，支持按范围读取
- `write_file`：创建或更新文件，支持覆盖控制、持久化和乐观锁版本校验
- `remove_file`：删除文件，可配合 `expected_version` 和 `force` 使用

运行状态：

- `health_check`：检查系统整体健康状态
- `system_info`：返回服务运行信息
- `storage_status`：检查底层存储系统状态

资源访问：

- 通过 `resources/` 模块注册文本、图片、二进制等资源读取能力

## 使用约束

- 写入路径必须位于当前会话允许的命名空间内
- `expected_version` 用于乐观锁控制，并发写入时建议显式传入
- `persistent=true` 的文件默认不会被普通删除，需结合 `force=true`
- 默认单文件大小限制由存储层控制
- 如果以 SSE 对外暴露，认证、鉴权、限流应由上游代理或部署层负责

## 示例

```python
result = await client.call_tool(
    "write_file",
    {
        "session_id": "user_123-agent_456",
        "mode": "create",
        "agent_name": "assistant",
        "file_name": "notes.md",
        "content": "# hello",
        "persistent": False,
    },
)

result = await client.call_tool(
    "read_file",
    {
        "session_id": "user_123-agent_456",
        "file_path": "session/assistant/notes.md",
    },
)
```

## 项目结构

```text
packages/mcp-scratchpad/
├── src/mcp_scratchpad/
│   ├── server.py          # 服务入口
│   ├── storage.py         # 文件存储与元数据
│   ├── models.py          # Pydantic 模型
│   ├── config/            # 配置加载、校验与模型
│   ├── exceptions/        # 自定义异常与异常处理
│   ├── fs/                # 文件系统后端、overlay、session manager
│   ├── resources/         # 文本/图片/二进制资源读取
│   ├── security/          # 审计、脱敏、资源限制
│   ├── monitoring/        # 健康检查
│   └── tools/             # MCP 工具实现
└── tests/
    ├── unit/
    ├── integration/
    ├── security/
    ├── performance/
    └── stress/
```

## 开发

运行测试：

```bash
uv run pytest
uv run pytest -m unit
uv run pytest -m integration
uv run pytest tests/unit/test_storage.py
```

运行代码检查：

```bash
uv run ruff check src/ tests/
uv run mypy src/
```

如果需要自动修复部分 lint 问题：

```bash
uv run ruff check --fix src/ tests/
```

## 说明

- 当前包使用独立的 `uv` 环境，建议在 `packages/mcp-scratchpad/` 目录下执行命令
- S3 支持是可选能力，未安装 `s3fs` 时不会启用对应后端
- 更多设计背景和 RFC 可参考 `docs/` 目录
