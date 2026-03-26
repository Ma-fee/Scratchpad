# MCP Scratchpad FastMCP 迁移方案

## 1. 项目概述

本文档详细描述了将现有的 mcp_scratchpad 项目从官方 MCP 库迁移到 FastMCP 框架的完整方案。迁移的目标是保持所有现有功能，同时利用 FastMCP 的现代化架构和装饰器模式。

## 2. 现有架构分析

### 2.1 当前组件结构

```
packages/mcp-scratchpad/
├── src/mcp_scratchpad/
│   ├── server.py              # FastMCP 服务器主入口
│   ├── tools/                 # FastMCP 工具实现
│   │   ├── __init__.py
│   │   └── file_tools.py
│   ├── models.py              # Pydantic 数据模型
│   ├── storage.py             # 文件系统存储
│   └── utils.py               # 工具函数
├── pyproject.toml             # 项目配置
└── README.md                  # 项目文档
```

### 2.2 当前依赖

- `mcp>=1.22.0`: 官方 MCP 库
- `fastapi>=0.121.3`: HTTP API
- `uvicorn>=0.38.0`: ASGI 服务器
- `pydantic>=2.12.4`: 数据验证

### 2.3 现有工具函数

1. `scratchpad_list_files`: 列出会话文件，支持过滤
2. `scratchpad_read_file`: 读取单个或多个文件内容
3. `scratchpad_write_file`: 创建或更新文件
4. `scratchpad_remove_file`: 删除文件

## 3. FastMCP 迁移架构设计

### 3.1 新组件结构

```
packages/mcp-scratchpad/
├── src/mcp_scratchpad/
│   ├── server.py              # FastMCP 服务器主入口
│   ├── tools/                 # FastMCP 工具实现
│   │   ├── __init__.py
│   │   ├── file_tools.py      # 文件操作工具
│   │   └── health_tools.py    # 健康检查工具
│   ├── models.py              # 保持现有模型（可能需要小幅调整）
│   ├── storage.py             # 保持现有存储实现
│   ├── utils.py               # 保持现有工具函数
│   └── tools/                 # FastMCP 工具实现
│   ├── __init__.py
│   └── file_tools.py      # 文件操作工具
├── pyproject.toml             # 更新依赖
└── fastmcp.json              # FastMCP 配置文件
```

### 3.2 依赖更新

```toml
dependencies = [
    "fastapi>=0.121.3",
    "httpx<1.0",
    "httpx-sse>=0.4.3",
    "fastmcp>=0.1.0",          # 替换 mcp
    "pydantic>=2.12.4",
    "uvicorn>=0.38.0",
]
```

## 4. 核心迁移策略

### 4.1 渐进式迁移

1. **阶段1**: 添加 FastMCP 依赖，创建新的服务器实现
2. **阶段2**: 使用 FastMCP 装饰器重构工具函数
3. **阶段3**: 适配传输层（stdio/SSE）
4. **阶段4**: 更新 FastAPI 集成
5. **阶段5**: 测试和文档更新

### 4.2 兼容性保证

- 保持所有现有的 API 接口不变
- 保持现有的数据模型和存储层
- 提供向后兼容的入口点
- 确保现有的 HTTP API 继续工作

## 5. FastMCP 工具重构方案

### 5.1 工具装饰器模式

使用 FastMCP 的 `@mcp.tool` 装饰器替换现有的手动工具注册：

```python
from fastmcp import FastMCP, Context

mcp = FastMCP(name="MCP Scratchpad")

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
    # 实现逻辑...
```

### 5.2 Context 集成

利用 FastMCP 的 Context 对象提供更好的用户体验：

```python
@mcp.tool
async def write_file(
    session_id: str,
    file_path: str,
    content: str,
    overwrite: bool = False,
    persistent: bool = False,
    permission: str = "read_write",
    ctx: Context
) -> Dict[str, Any]:
    """写入文件内容"""
    await ctx.info(f"正在写入文件: {file_path}")
    await ctx.report_progress(50, 100)
    # 实现逻辑...
    await ctx.report_progress(100, 100)
```

## 6. 传输层适配

### 6.1 stdio 传输

FastMCP 原生支持 stdio，只需要：

```python
if __name__ == "__main__":
    mcp.run()
```

### 6.2 SSE 传输

保持现有的 SSE 实现，但使用 FastMCP 的内置支持：

```python
# FastMCP 会自动处理 SSE 传输
mcp.run(transport="sse", host="0.0.0.0", port=8890)
```

## 7. FastAPI 集成更新

### 7.1 兼容性适配器

创建适配器来桥接 FastMCP 和现有的 FastAPI 应用：

```python
```python
# FastMCP 工具直接通过 MCP 协议调用
# 不再需要 FastAPI 适配层，专注于 MCP 协议实现
```
## 8. 配置文件

### 8.1 FastMCP 配置

创建 `fastmcp.json` 配置文件：

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
  }
}
```

## 9. 迁移步骤详解

### 9.1 步骤1: 依赖更新

- 移除 `mcp>=1.22.0`
- 添加 `fastmcp>=0.1.0`
- 运行 `uv sync` 更新依赖

### 9.2 步骤2: 创建 FastMCP 服务器

- 创建 `src/mcp_scratchpad/server.py`
- 实现 FastMCP 实例和基本配置
- 保持与现有存储层的集成

### 9.3 步骤3: 工具函数重构

- 将现有的 handler 函数转换为 FastMCP 工具
- 使用装饰器模式
- 集成 Context 功能

### 9.4 步骤4: 传输层实现

- 实现 stdio 传输（FastMCP 原生支持）
- 适配 SSE 传输
- 保持现有命令行参数

### 9.5 步骤5: 测试和验证

- 单元测试：验证每个工具函数
- 集成测试：验证 stdio 和 SSE 传输
- 兼容性测试：验证 MCP 协议接口

### 9.6 步骤6: 测试验证

- 单元测试：验证每个工具函数
- 集成测试：验证 stdio 和 SSE 传输
- 兼容性测试：验证现有 HTTP API

## 10. 风险评估和缓解

### 10.1 主要风险

1. **API 兼容性**: FastMCP 的响应格式可能与现有实现不同
2. **性能影响**: 新架构可能影响性能
3. **依赖冲突**: FastMCP 可能与其他依赖冲突

### 10.2 缓解措施

1. **渐进式迁移**: 分阶段实施，每个阶段都可以回滚
2. **兼容性适配器**: 创建适配层确保接口一致性
3. **全面测试**: 在每个阶段进行充分测试

## 11. 验收标准

### 11.1 功能完整性

- [ ] 所有现有工具函数正常工作
- [ ] stdio 传输正常
- [ ] SSE 传输正常
- [ ] HTTP API 保持兼容

### 11.2 性能标准

- [ ] 响应时间不超过现有实现的 110%
- [ ] 内存使用不超过现有实现的 120%

### 11.3 代码质量

- [ ] 代码覆盖率不低于 80%
- [ ] 所有类型检查通过
- [ ] 文档完整更新

## 12. 后续优化建议

### 12.1 FastMCP 特性利用

迁移完成后，可以考虑利用 FastMCP 的高级特性：

- 资源管理（Resources）
- 提示管理（Prompts）
- 中间件系统
- 更好的错误处理

### 12.2 架构改进

- 添加配置管理
- 实现更好的日志系统
- 添加监控和指标
- 支持更多存储后端

## 13. 总结

本迁移方案采用渐进式策略，确保在利用 FastMCP 现代化架构的同时，保持所有现有功能的兼容性。通过分阶段实施和充分测试，可以最小化迁移风险，并为未来的功能扩展奠定基础。

关键成功因素：

1. 严格的向后兼容性保证
2. 全面的测试覆盖
3. 清晰的回滚计划
4. 详细的文档更新
