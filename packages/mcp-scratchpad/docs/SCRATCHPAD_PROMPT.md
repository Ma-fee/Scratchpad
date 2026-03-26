# MCP Scratchpad 工具使用指南

## 概述

MCP Scratchpad 是一个基于 FastMCP 框架的高质量文件管理服务，为 AI 助手和开发者提供持久化的草稿箱功能。该工具支持文件创建、读取、更新、删除等操作，并提供会话管理和版本控制功能。

## 核心使用原则

### 1. 优先查看草稿箱内容

在执行任何文件操作之前，**始终优先使用 `scratchpad_list_files` 工具**查看当前草稿箱的内容。这有助于：

- 了解现有文件结构
- 避免重复创建文件
- 确定正确的文件路径
- 检查文件版本和权限

### 2. 使用 write_file 形式写入报告

所有报告、分析结果和输出内容都应使用 `scratchpad_write_file` 工具写入文件。这确保：

- 内容持久化保存
- 支持版本控制
- 便于后续引用和修改
- 实现 agent 之间的文件传递

### 3. 通过 Markdown Citation 引用文件

在输出中使用 markdown citation 格式 `[^%file_path%]` 引用文件，实现：

- agent 之间的文件传递
- 精确的文件路径引用
- 可追溯的内容来源
- 标准化的引用格式

## 工具详细说明

### 文件管理工具

#### scratchpad_list_files

**功能**：列出会话中的所有文件，支持多种过滤条件

**参数**：

- `session_id` (必需)：会话唯一标识符
- `persistent` (可选)：过滤持久化文件 (true/false/None)
- `keyword` (可选)：按文件名模糊匹配的关键字
- `namespace` (可选)：命名空间过滤 (如 session, kb)
- `agent_name` (可选)：仅返回指定 Agent 的文件

**使用示例**：

```python
# 查看会话中的所有文件
result = await scratchpad_list_files(session_id="user_123-agent_456")

# 查看特定 agent 的文件
result = await scratchpad_list_files(
    session_id="user_123-agent_456",
    agent_name="assistant"
)

# 查找包含特定关键字的文件
result = await scratchpad_list_files(
    session_id="user_123-agent_456",
    keyword="report"
)
```

**返回格式**：

- `files`：文件元数据列表
- `total_files`：文件总数
- `summary`：文本摘要
- `session_id`：会话ID

#### scratchpad_read_file

**功能**：读取一个或多个文件的内容，支持行范围选择

**参数**：

- `session_id` (必需)：会话唯一标识符
- `file_paths` (可选)：多个文件路径列表
- `file_requests` (可选)：详细文件读取请求列表，包含行范围

**使用示例**：

```python
# 读取单个文件
result = await scratchpad_read_file(
    session_id="user_123-agent_456",
    file_paths=["session/assistant/report.md"]
)

# 读取多个文件
result = await scratchpad_read_file(
    session_id="user_123-agent_456",
    file_paths=["session/assistant/config.json", "session/assistant/notes.md"]
)

# 读取文件的特定行范围
result = await scratchpad_read_file(
    session_id="user_123-agent_456",
    file_requests=[{
        "file_path": "session/assistant/report.md",
        "start_line": 10,
        "end_line": 50
    }]
)
```

**返回格式**：

- `files`：文件内容和元数据
- `total_files`：读取的文件总数
- `content`：格式化的文件内容块

#### scratchpad_write_file

**功能**：创建或更新文件内容

**参数**：

- `session_id` (必需)：会话唯一标识符
- `mode` (必需)：操作类型 ("create" 或 "update")
- `file_path` (update模式必需)：文件路径
- `file_name` (create模式必需)：文件名
- `agent_name` (create模式必需)：Agent名称
- `content` (必需)：文件内容
- `overwrite` (可选)：是否覆盖现有文件 (默认false)
- `persistent` (可选)：是否持久化保存 (默认false)
- `permission` (可选)：文件权限 ("read" 或 "read_write")
- `expected_version` (可选)：乐观锁版本号

**使用示例**：

```python
# 创建新文件
result = await scratchpad_write_file(
    session_id="user_123-agent_456",
    mode="create",
    agent_name="assistant",
    file_name="analysis_report.md",
    content="# 分析报告\n\n这是分析结果...",
    persistent=True,
    permission="read_write"
)

# 更新现有文件
result = await scratchpad_write_file(
    session_id="user_123-agent_456",
    mode="update",
    file_path="session/assistant/analysis_report.md",
    content="# 更新后的分析报告\n\n这是更新后的内容...",
    expected_version=2
)
```

#### scratchpad_remove_file

**功能**：删除文件

**参数**：

- `session_id` (必需)：会话唯一标识符
- `file_path` (必需)：要删除的文件路径
- `expected_version` (可选)：乐观锁版本号
- `force` (可选)：是否强制删除持久化文件 (默认false)

**使用示例**：

```python
# 删除普通文件
result = await scratchpad_remove_file(
    session_id="user_123-agent_456",
    file_path="session/assistant/temp_file.txt"
)

# 强制删除持久化文件
result = await scratchpad_remove_file(
    session_id="user_123-agent_456",
    file_path="session/assistant/important_file.md",
    force=True
)
```

### 系统监控工具

#### scratchpad_health_check

**功能**：执行系统健康检查，返回各组件状态

**使用示例**：

```python
result = await scratchpad_health_check()
```

**返回信息**：

- 系统整体健康状态
- 存储系统状态
- 配置验证结果
- 错误详情（如有）

#### scratchpad_system_info

**功能**：获取系统信息和服务器状态

**使用示例**：

```python
result = await scratchpad_system_info()
```

**返回信息**：

- 服务器启动时间
- 运行时长
- 版本信息
- 配置参数

#### scratchpad_storage_status

**功能**：检查存储系统状态

**使用示例**：

```python
result = await scratchpad_storage_status()
```

**返回信息**：

- 存储目录可访问性
- 磁盘空间状态
- 写入权限检查

## 最佳实践

### 1. 工作流程规范

**标准操作流程**：

1. **查看现有文件**：使用 `scratchpad_list_files` 了解草稿箱状态
2. **读取相关文件**：使用 `scratchpad_read_file` 获取需要参考的内容
3. **创建/更新文件**：使用 `scratchpad_write_file` 写入新内容
4. **引用文件**：在输出中使用 `[^%file_path%]` 格式引用

### 2. 文件命名规范

**推荐命名模式**：

- 报告类：`report_YYYY-MM-DD.md`、`analysis_主题.md`
- 配置类：`config_服务名.json`、`settings_环境.yaml`
- 临时文件：`temp_描述.txt`、`draft_版本.md`
- 数据文件：`data_类型_日期.csv`、`results_实验ID.json`

**路径结构**：

```
session/
├── {agent_name}/
│   ├── reports/
│   ├── configs/
│   ├── data/
│   └── drafts/
```

### 3. 版本控制策略

**乐观锁使用**：

- 在更新文件前，先读取文件获取当前版本
- 使用 `expected_version` 参数避免冲突
- 处理版本冲突时重新读取并合并更改

**版本管理最佳实践**：

```python
# 1. 读取文件获取版本
files_result = await scratchpad_read_file(
    session_id=session_id,
    file_paths=[file_path]
)
current_version = files_result["files"][0]["version"]

# 2. 更新文件时指定版本
await scratchpad_write_file(
    session_id=session_id,
    mode="update",
    file_path=file_path,
    content=new_content,
    expected_version=current_version
)
```

### 4. 权限管理

**权限级别**：

- `read`：只读权限，适合最终报告和配置文件
- `read_write`：读写权限，适合草稿和临时文件

**持久化策略**：

- `persistent=true`：重要文件、最终报告、配置文件
- `persistent=false`：临时草稿、中间结果、测试文件

### 5. 错误处理

**常见错误及处理**：

1. **文件不存在**：
   - 检查文件路径是否正确
   - 使用 `scratchpad_list_files` 确认文件存在

2. **版本冲突**：
   - 重新读取文件获取最新版本
   - 合并更改后重新尝试更新

3. **权限不足**：
   - 检查文件权限设置
   - 使用 `force=true` 删除持久化文件（谨慎操作）

4. **文件过大**：
   - 检查文件大小是否超过限制（默认10MB）
   - 考虑分割大文件或压缩内容

## 高级用法

### 1. 批量文件操作

**批量读取**：

```python
# 读取多个相关文件
file_paths = [
    "session/assistant/config.json",
    "session/assistant/data.csv",
    "session/assistant/template.md"
]
result = await scratchpad_read_file(
    session_id=session_id,
    file_paths=file_paths
)
```

**批量创建**：

```python
# 为不同类型的报告创建模板
templates = {
    "daily_report.md": "# 日报 - {date}\n\n## 工作内容\n\n## 问题与解决方案\n\n## 明日计划",
    "meeting_notes.md": "# 会议记录 - {date}\n\n## 参与人员\n\n## 议题\n\n## 决策\n\n## 行动项",
    "analysis_report.md": "# 分析报告\n\n## 背景\n\n## 方法\n\n## 结果\n\n## 结论"
}

for filename, content in templates.items():
    await scratchpad_write_file(
        session_id=session_id,
        mode="create",
        agent_name="assistant",
        file_name=filename,
        content=content,
        persistent=True
    )
```

### 2. 文件引用和链接

**在内容中引用其他文件**：

```markdown
# 项目总结

本文档基于以下分析结果：

- 数据分析报告：[^session/assistant/data_analysis.md]
- 用户调研结果：[^session/assistant/user_research.md]
- 技术评估：[^session/assistant/tech_evaluation.md]

详细的技术实现请参考：[^session/assistant/implementation.md]
```

**创建文件索引**：

```python
# 创建文件索引
index_content = "# 文件索引\n\n"
for file_record in files_result["files"]:
    file_path = file_record["file_path"]
    file_name = file_record["name"]
    updated_time = file_record["updated_at"]
    index_content += f"- [{file_name}]({file_path}) - 更新时间: {updated_time}\n"

await scratchpad_write_file(
    session_id=session_id,
    mode="create",
    agent_name="assistant",
    file_name="index.md",
    content=index_content,
    persistent=True
)
```

### 3. 会话管理

**会话隔离**：

- 每个用户对话使用独立的 `session_id`
- 不同 agent 使用不同的子目录
- 敏感数据设置适当的权限

**数据清理**：

```python
# 清理临时文件
temp_files = []
for file_record in files_result["files"]:
    if not file_record["persistent"] and "temp" in file_record["name"]:
        temp_files.append(file_record["file_path"])

for temp_file in temp_files:
    await scratchpad_remove_file(
        session_id=session_id,
        file_path=temp_file
    )
```

## 集成示例

### Claude Desktop 配置

```json
{
  "mcpServers": {
    "scratchpad": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-scratchpad", "mcp-scratchpad"]
    }
  }
}
```

### 典型使用场景

**场景1：生成分析报告**

```python
# 1. 查看现有文件
await scratchpad_list_files(session_id="user_123-agent_456")

# 2. 读取数据文件
data_result = await scratchpad_read_file(
    session_id="user_123-agent_456",
    file_paths=["session/assistant/raw_data.csv"]
)

# 3. 生成分析报告
report_content = generate_analysis_report(data_result["content"])

# 4. 保存报告
await scratchpad_write_file(
    session_id="user_123-agent_456",
    mode="create",
    agent_name="assistant",
    file_name="analysis_report.md",
    content=report_content,
    persistent=True
)

# 5. 在回复中引用
print("分析报告已生成：[^session/assistant/analysis_report.md]")
```

**场景2：配置管理**

```python
# 1. 检查现有配置
config_result = await scratchpad_list_files(
    session_id="user_123-agent_456",
    keyword="config"
)

# 2. 更新配置文件
await scratchpad_write_file(
    session_id="user_123-agent_456",
    mode="update",
    file_path="session/assistant/app_config.json",
    content=new_config,
    expected_version=current_version
)
```

## 注意事项

### 安全考虑

1. **路径验证**：系统自动验证文件路径，防止目录遍历攻击
2. **权限控制**：根据文件敏感度设置适当的权限
3. **大小限制**：单个文件默认限制10MB，可根据需要调整
4. **会话隔离**：不同会话之间的数据完全隔离

### 性能优化

1. **批量操作**：尽量使用批量读取减少网络开销
2. **缓存策略**：合理使用持久化设置避免重复计算
3. **文件清理**：定期清理临时文件释放存储空间
4. **版本管理**：避免不必要的版本更新

### 兼容性

1. **传输协议**：支持 stdio 和 SSE 两种传输方式
2. **数据格式**：使用 UTF-8 编码，支持多语言内容
3. **路径格式**：使用正斜杠(/)作为路径分隔符
4. **时间格式**：使用 ISO 8601 格式，以 "Z" 结尾表示UTC

## 故障排除

### 常见问题

**Q: 文件写入失败**
A: 检查文件大小是否超限、路径是否有效、权限设置是否正确

**Q: 版本冲突错误**
A: 重新读取文件获取最新版本，合并更改后重试

**Q: 无法删除文件**
A: 检查是否为持久化文件，如需删除请使用 force=true

**Q: 读取文件为空**
A: 确认文件路径正确，检查文件是否成功写入

### 调试技巧

1. **使用健康检查**：定期运行 `scratchpad_health_check` 检查系统状态
2. **查看系统信息**：使用 `scratchpad_system_info` 获取配置详情
3. **检查存储状态**：使用 `scratchpad_storage_status` 验证存储系统
4. **日志分析**：启用详细日志记录帮助诊断问题

---

通过遵循本指南，您可以充分利用 MCP Scratchpad 工具的强大功能，实现高效的文件管理和 agent 间的协作。
