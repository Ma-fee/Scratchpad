# 配置文件使用指南

MCP Scratchpad 支持通过 YAML 配置文件定义 overlay 文件系统挂载点，支持环境变量扩展和多种存储后端。

## 配置文件位置

配置文件按以下顺序查找（优先级从高到低）：

1. `./scratchpad.yaml` - 当前目录
2. `~/.config/mcp-scratchpad/config.yaml` - 用户配置目录
3. `/etc/mcp-scratchpad/config.yaml` - 系统全局配置

也可以通过代码显式指定配置文件路径。

## 环境变量支持

配置文件支持以下语法扩展环境变量：

- `${VAR}` - 扩展为环境变量 VAR 的值，未设置时为空字符串
- `${VAR:default}` - 扩展为环境变量 VAR 的值，未设置时为默认值 `default`

## 完整配置示例

### 基础示例 (basic-config.yaml)

```yaml
# 基础配置 - 本地文件系统挂载
mounts:
  - name: workspace
    source: file:///tmp/scratchpad-workspace
    mount_point: /
    mode: rw
    priority: 0
```

### 多层覆盖示例 (overlay-config.yaml)

```yaml
# 多层 overlay 配置 - 共享模板 + 工作空间
mounts:
  # 底层: 只读模板 (低优先级)
  - name: templates
    source: file:///var/lib/scratchpad/templates
    mount_point: /templates
    mode: ro
    priority: 0
    
  # 中层: 共享数据 (中优先级)
  - name: shared_data
    source: file:///var/lib/scratchpad/shared
    mount_point: /shared
    mode: ro
    priority: 10
    
  # 顶层: 可写工作空间 (高优先级)
  - name: workspace
    source: file:///home/user/workspace
    mount_point: /
    mode: rw
    priority: 100
```

### 多后端混合示例 (hybrid-config.yaml)

```yaml
# 混合存储后端 - 本地 + S3 + 内存
mounts:
  # 本地缓存
  - name: cache
    source: file:///tmp/scratchpad-cache
    mount_point: /cache
    mode: rw
    priority: 10
    options:
      max_size: 1073741824  # 1GB limit
      
  # S3 存储桶
  - name: s3_storage
    source: s3://my-bucket/scratchpad-data
    mount_point: /s3
    mode: ro
    priority: 5
    options:
      endpoint_url: https://s3.amazonaws.com
      region_name: us-east-1
      
  # 内存存储 (临时文件)
  - name: temp
    source: memory://
    mount_point: /tmp
    mode: rw
    priority: 20
    options:
      max_size: 104857600  # 100MB limit
```

### 使用环境变量 (env-config.yaml)

```yaml
# 使用环境变量的配置
mounts:
  - name: workspace
    source: file://${WORKSPACE_DIR:/tmp/workspace}
    mount_point: /
    mode: rw
    priority: 0
    
  - name: secrets
    source: file://${SECRETS_DIR}
    mount_point: /secrets
    mode: ro
    priority: 100
    
  - name: s3_data
    source: s3://${S3_BUCKET:default-bucket}/data
    mount_point: /data
    mode: ${DATA_MODE:ro}
    priority: 50
```

### 生产环境示例 (production-config.yaml)

```yaml
# 生产环境配置 - 只读模板 + 可写工作区
mounts:
  # 团队共享的只读模板
  - name: team_templates
    source: file:///opt/scratchpad/templates
    mount_point: /templates
    mode: ro
    priority: 10
    
  # 团队共享的知识库
  - name: knowledge_base
    source: file:///opt/scratchpad/kb
    mount_point: /kb
    mode: ro
    priority: 20
    
  # 用户工作空间 (唯一可写)
  - name: user_workspace
    source: file://${USER_WORKSPACE_DIR}
    mount_point: /
    mode: rw
    priority: 100
```

### 开发环境示例 (development-config.yaml)

```yaml
# 开发环境配置 - 全部使用本地路径
mounts:
  - name: dev_templates
    source: file://./dev-templates
    mount_point: /templates
    mode: ro
    priority: 10
    
  - name: dev_workspace
    source: file://./workspace
    mount_point: /
    mode: rw
    priority: 100
```

## 配置字段说明

### MountConfig 字段

| 字段 | 类型 | 必需 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | string | 是 | - | 挂载点名称，必须以字母开头，只能包含字母、数字、下划线和连字符 |
| `source` | string | 是 | - | 源 URI，支持 `file://`, `s3://`, `memory://` |
| `mount_point` | string | 是 | - | 挂载路径，必须是绝对路径 (以 `/` 开头) |
| `mode` | string | 否 | `ro` | 访问模式: `ro` (只读) 或 `rw` (读写) |
| `priority` | integer | 否 | `0` | 优先级，数字越大优先级越高 |
| `options` | dict | 否 | `{}` | 后端特定选项 |

### 验证规则

1. **挂载点名称唯一**: 所有 mounts 的 name 必须唯一
2. **只有一个读写挂载**: 只能有一个 `mode: rw` 的挂载点
3. **挂载点不重叠**: 挂载路径不能是另一个挂载路径的前缀
4. **优先级唯一**: 所有 mounts 的 priority 必须唯一

## 使用方式

### 1. 命令行使用 - 使用 -c/--config 参数

使用 `-c` 或 `--config` 参数指定配置文件：

```bash
# 使用 -c 参数指定配置文件
uv run mcp-scratchpad -c ./my-config.yaml

# 或使用 --config 长参数
uv run mcp-scratchpad --config /path/to/config.yaml

# 结合其他参数使用
uv run mcp-scratchpad -c ./prod-config.yaml --transport sse --port 8890
```

如果不指定 `-c` 参数，服务器会自动搜索标准位置：
1. `./scratchpad.yaml` - 当前目录
2. `~/.config/mcp-scratchpad/config.yaml` - 用户配置
3. `/etc/mcp-scratchpad/config.yaml` - 系统配置

### 2. 命令行参数帮助

查看所有可用参数：

```bash
uv run mcp-scratchpad --help
```

输出示例：
```
usage: mcp-scratchpad [-h] [--transport {stdio,sse}] [--host HOST] [--port PORT]
                     [--base-dir BASE_DIR] [-c CONFIG]

MCP Scratchpad FastMCP Server

options:
  -h, --help            show this help message and exit
  --transport {stdio,sse}
                        Transport method
  --host HOST           SSE host address
  --port PORT           SSE port
  --base-dir BASE_DIR   File storage base directory
  -c CONFIG, --config CONFIG
                        Path to configuration file (YAML). Searches standard
                        locations if not specified.
```

### 3. 代码中使用

```python
from mcp_scratchpad.config.loader import load_overlay_config
from mcp_scratchpad.fs.session_manager import SessionFileSystemManager

# 加载配置
config = load_overlay_config("./my-config.yaml")
# 或自动搜索标准位置
config = load_overlay_config()

# 使用配置创建 session manager
manager = SessionFileSystemManager(config)

# 创建 session
session_id = manager.create_session()
```

### 4. 检查配置

### 重复挂载点名称
```yaml
mounts:
  - name: workspace
    source: file:///a
    mount_point: /
  - name: workspace  # ❌ 错误: 重复名称
    source: file:///b
    mount_point: /b
```

### 多个读写挂载
```yaml
mounts:
  - name: a
    source: file:///a
    mount_point: /a
    mode: rw
  - name: b
    source: file:///b
    mount_point: /b
    mode: rw  # ❌ 错误: 只能有一个 rw
```

### 挂载点重叠
```yaml
mounts:
  - name: parent
    source: file:///a
    mount_point: /parent
  - name: child
    source: file:///b
    mount_point: /parent/child  # ❌ 错误: 重叠路径
```

## 模板配置

### Agent Skills 场景
```yaml
mounts:
  # 共享的 skills (只读)
  - name: skills
    source: file://${SKILLS_DIR}
    mount_point: /.claude/skills
    mode: ro
    priority: 10
    
  # 会话工作空间 (可写)
  - name: workspace
    source: file://${WORKSPACE_DIR}
    mount_point: /
    mode: rw
    priority: 100
```

### 模板 Copy-on-Write 场景
```yaml
mounts:
  # 基础模板 (只读)
  - name: templates
    source: file:///templates
    mount_point: /templates
    mode: ro
    priority: 10
    
  # 工作副本 (可写，修改时会复制到此处)
  - name: workspace
    source: file:///workspace
    mount_point: /
    mode: rw
    priority: 100
```

## 相关文档

- [配置模型 API](src/mcp_scratchpad/config/models.py) - Pydantic 模型定义
- [配置加载器](src/mcp_scratchpad/config/loader.py) - 加载和环境变量扩展
- [RFC-0001](docs/rfcs/draft/RFC-0001-scratchpad-overlay-fs.md) - Overlay 文件系统架构设计
