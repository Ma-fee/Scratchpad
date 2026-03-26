# RFC-0001: MCP Scratchpad Overlay Filesystem Architecture

---

## Metadata

| Field | Value |
|-------|-------|
| **RFC ID** | RFC-0001 |
| **Title** | MCP Scratchpad Overlay Filesystem Architecture |
| **Status** | DRAFT |
| **Author** | MCP Scratchpad Team |
| **Reviewers** | TBD |
| **Created** | 2026-03-19 |
| **Last Updated** | 2026-03-19 (Review Complete) |
| **Decision Date** | TBD |

---

## Overview

本 RFC 提议对 MCP Scratchpad 系统进行架构升级，引入基于 fsspec 的多层 overlay 文件系统支持。该架构将支持多种后端存储（S3、本地文件系统、内存等）的混合挂载，实现只读与读写路径的灵活组合，并通过 `scratchpad://` URI 方案将文件系统资源完全暴露为 MCP Resources，同时保持 session 级别的完全隔离。

预期成果：
- 支持配置文件驱动下的多路径混合挂载（如 S3 + 本地文件系统）
- 实现基于 fsspec 的统一文件操作抽象层
- 提供完整的 MCP Resources 集成（`scratchpad://` 前缀 URI）
- 维持并强化 session 级别的文件隔离机制
- 支持只读路径、只写路径、读写混合路径配置

---

## Background & Context

### 当前系统状态

MCP Scratchpad 是一个基于 FastMCP 框架的文件管理服务器，当前实现包含以下特性：

1. **文件操作能力**
   - 基础 CRUD：read, write, delete, list
   - 文本编辑：string replacement, unified diff application
   - 批量操作：batch read with offset/limit

2. **Session 隔离机制**
   - 基于 `session_id` 的文件目录隔离
   - 存储路径：`{base_dir}/{session_id}/`
   - 元数据管理：`.metadata.json` 存储版本、时间戳、权限

3. **Namespace 限制**
   - `session/`：读写操作命名空间
   - `kb/`：只读知识库命名空间

4. **当前架构限制**
   | 限制 | 说明 |
   |------|------|
   | 后端单一 | 仅支持本地文件系统 |
   | 无 overlay 能力 | 不支持多路径联合挂载 |
   | 无 Resource 集成 | 无法通过 MCP Resources 访问文件 |
   | 配置受限 | 仅支持 `base_dir` 路径配置 |

### 业务场景与需求驱动

本 RFC 的需求来源于实际业务场景中遇到的复杂文件管理挑战：

#### 场景 1: Agent Skills 共享与模板 COW

**背景**: .claude/skills 目录包含共享的 Agent skills 定义，每个 session 需要读取这些 skills，同时要支持基于模板的创建工作空间。

**当前痛点**:
- Skills 需要在每个 session 中重复复制，浪费存储
- Notepads 初始化目录结构和模板时，需要基础模板 + session 本地修改
- Agent 编写的内容需要隔离，但又需要基于共享模板启动

**需要的 Overlay 能力**:
```
[Lower层 - 只读共享]
  ├─ .claude/skills/        # 所有 session 共享的 skills
  └─ templates/notepad/     # Notepad 基础模板

[Upper层 - Session 可写]
  └─ workspace/             # Agent 实际编辑的内容

[Merged View]
  ├─ .claude/skills/        # 可读取，不可修改
  ├─ templates/notepad/     # 可读取，修改时 COW 到 workspace/
  └─ workspace/             # Agent 自由编辑
```

**Copy-on-Write 示例**:
1. Session 启动，挂载共享 skills 作为 lower layer
2. Agent 读取 `.claude/skills/web-search.yaml` → 直接从 lower 读取
3. Agent 修改 `templates/notepad/README.md` → COW 到 upper layer
4. Another session 启动 → 有自己的 upper，但共享只读的 lower

#### 场景 2: 多模态内容引用与溯源

**背景**: 用户在对话中上传图片，后续生成的报告需要引用这些图片，并支持通过 URI 溯源。

**当前痛点**:
- 对话中的图片无法持久化到 session workspace
- 生成的报告无法直接引用原始图片 URI
- 缺乏标准化的多模态内容管理

**需要的多模态能力**:
```
User uploads: screenshot.png (in conversation)
    ↓
Stored at: scratchpad://sess_abc123/inputs/screenshot.png
    ↓
Agent generates report.md:
    "如图 [screenshot](scratchpad://sess_abc123/inputs/screenshot.png) 所示..."
    ↓
Client 渲染报告时:
    - 识别 scratchpad:// URI
    - 通过 MCP Resource 获取图片
    - 支持缩放、预览等交互
```

**URI 溯源**:
- 任何内容都可以通过 `scratchpad://{session_id}/{path}` 定位
- 图片与文本引用解耦，支持跨 session 相对引用
- 支持多版本（修改后的图片与原始图片共存不同 layer）

#### 场景 3: 实时文档变更通知

**背景**: Agent 长时间运行任务，生成阶段性报告或编辑文档，需要 Client 实时感知变化。

**当前痛点**:
- Agent 写入文件后 Client 无法自动刷新
- 需要轮询或手动触发才能查看最新内容
- 无法区分手动编辑 vs Agent 自动生成的变更

**需要的通知能力**:
```
Agent 工作流程:
    [Research Phase] 
        → writes: report/phase-1-findings.md
        → MCP Notification: resources/updated 
        → Client 自动显示新文件
    
    [Writing Phase]
        → edits: report/final-report.md (line 100-200)
        → MCP Notification: resources/updated
        → Client 高亮变更部分
    
    [Review Phase]
        → generates: report/charts/summary.png
        → MCP Notification: resources/updated
        → Client 实时渲染新图片
```

**订阅模式**:
- Client 可以订阅 `scratchpad://{session_id}/report/*`
- 任何匹配的文件变更触发通知
- 支持批量防抖（快速连续编辑合并为一次通知）

#### 场景 4: 跨会话资源共享与协作

**背景**: 多个相关 session 需要访问相同的知识库或数据集，但保持各自的编辑隔离。

**示例**: 数据分析工作流
```
Session A (Data Engineer):
    Mounts: /data/raw/customers.csv (S3, RO)
    Workspace: /workspace/data-cleaning/
    Output: /workspace/cleaned-data.parquet

Session B (Analyst):
    Mounts: /data/cleaned/ (从 Session A 导出，RO)
            /templates/analysis/ (本地，RO)
    Workspace: /workspace/analysis/
    Output: /workspace/report.md

Session C (Reviewer):
    Mounts: /data/cleaned/ (RO)
            /analysis/report.md (从 Session B, RO)
    Workspace: /workspace/review/
    Output: /workspace/review-comments.md
```

每个 Session 只看到需要的共享数据 + 自己的编辑空间。

#### 场景 5: 混合存储后端支持

**背景**: 不同数据有不同的存储需求和生命周期。

| 数据类型 | 存储后端 | 理由 |
|----------|---------|------|
| Session workspace | Memory (upper) + Local (backup) | 高性能，可持久化 |
| Skills / Templates | S3 / Local | 版本化，全局共享 |
| Large datasets | S3 with local cache | 大容量，按需加载 |
| Temporary files | Memory only | 快速，无需持久化 |
| Audit logs | S3 append-only | 不可变，合规存储 |

**统一访问示例**:
```python
# 用户无感知存储位置
read("scratchpad://sess_123/data/large-dataset.csv")  # 实际来自 S3
read("scratchpad://sess_123/output/report.md")        # 实际来自 Memory upper
read("scratchpad://sess_123/.claude/skills/web.yaml") # 实际来自本地 skills 目录
```

### 技术背景

#### fsspec 文件系统抽象层

fsspec (filesystem-spec) 是 Python 生态中使用最广泛的文件系统抽象库，提供统一接口访问不同后端存储：

| 后端类型 | 类名 | 用途 |
|----------|------|------|
| Local | `LocalFileSystem` | 本地文件系统 |
| S3 | `S3FileSystem` | AWS S3 / MinIO |
| Memory | `MemoryFileSystem` | 内存文件系统 |
| HTTP | `HTTPFileSystem` | HTTP(S) 只读访问 |
| Caching | `CachingFileSystem` | 缓存层 |

#### Docker Overlay2 模式参考

Docker 使用 overlay2 存储驱动实现容器文件系统隔离，其架构值得借鉴：

```
[Upperdir]    [Lowerdir(s)]
   │              │
   ├─ diff/       ├─ (base image layers)
   ├─ work/       │
   └─ link        │
         │
         └─────── [Merged View]
```

- **Upperdir**: 容器专属的可写层
- **Lowerdir**: 多个可以叠加的只读层
- **Copy-on-Write**: 首次写入时复制文件到上层

#### MCP Resources 架构

MCP (Model Context Protocol) Resources 提供声明式资源访问机制：

- **URI 方案**: `protocol://` 自定义协议支持
- **资源模板**: RFC 6570 URI模板用于参数化资源
- **订阅通知**: `resources/subscribe` 支持变更推送
- **分页查询**: `resources/list` 支持游标分页

---

## Problem Statement

### 当前面临的挑战

1. **存储后端单一性**
   - 当前仅支持本地文件系统
   - 无法实现云存储（S3）与本地存储的透明混合
   - 限制了大文件和高可用场景的应用

2. **缺乏 Overlay 能力**
   - 没有联合挂载机制
   - 无法将知识库（只读）与工作目录（读写）叠加
   - 每个 session 需要独立复制基础数据，效率低下

3. **与 MCP 生态集成不足**
   - 文件只能通过 tools 访问，无法通过 resources 发现
   - 客户端无法获知哪些文件可用
   - 缺乏标准的资源变更通知机制

4. **配置灵活性不足**
   - 仅支持单一 `base_dir` 配置
   - 无法为不同用途配置不同挂载点
   - 只读/读写混合场景需要硬编码逻辑

### 不解决的限制

- 跨 session 文件共享（每个 session 保持完全隔离）
- 全局写锁机制（维持乐观锁策略）
- 文件内容搜索索引（超出本 RFC 范围）
- 多节点分布式一致性（假设单实例部署）

---

## Goals & Non-Goals

### Goals (Scope Within)

| # | Goal | Success Criteria |
|---|------|-----------------|
| G1 | 多后端存储支持 | 支持本地、S3、内存三种后端，可扩展更多 |
| G2 | Overlay 文件系统 | 实现类似 overlay2 的多层挂载机制 |
| G3 | MCP Resources 集成 | 完整实现 `scratchpad://` URI scheme 资源 |
| G4 | Session 隔离 | 每个 session 独立的 overlay 视图 |
| G5 | 配置驱动挂载 | 通过配置文件定义挂载点及属性 |
| G6 | 读写混合支持 | 支持 RO base + RW overlay 模式 |

### Non-Goals (Scope Outside)

| # | Non-Goal | Reasoning |
|---|----------|-----------|
| NG1 | 网络文件系统 (NFS) 支持 | 超出当前优先级，后续 RFC 可覆盖 |
| NG2 | 实时文件同步 | 复杂度高，需要分布式共识协议 |
| NG3 | 文件加密层 | 可在 storage layer 独立实现 |
| NG4 | 版本控制系统 | Git 集成可独立作为工具提供 |
| NG5 | 磁盘配额管理 | 可在 overlay layer 上层实现 |

---

## Evaluation Criteria

### 技术评估维度

| Criterion | Weight | Measurement | Threshold |
|-----------|--------|-------------|-----------|
| **Performance** | 25% | 文件操作延迟 | < 50ms for 1MB read |
| **Scalability** | 20% | 并发 session 数 | > 100 concurrent |
| **Maintainability** | 20% | 代码复杂度 | Cyclomatic < 10 per file |
| **Extensibility** | 15% | 新后端支持成本 | < 1 day to add new FS |
| **Compatibility** | 10% | 现有 API 兼容 | 100% backward compatible |
| **Resource Efficiency** | 10% | 内存 overhead | < 10MB per session |

### 业务评估维度

| Criterion | Weight | Priority |
|-----------|--------|----------|
| **Time to Implement** | 30% | 2-4 weeks |
| **Migration Effort** | 25% | Zero-downtime |
| **Operational Complexity** | 25% | Comparable to current |
| **User Learning Curve** | 20% | Minimal additional concepts |

---

## Options Analysis

### Option 1: Pure fsspec Implementation with Custom MountFS

**Description**: 基于 fsspec 的 `AbstractFileSystem` 实现自定义的 `MountFileSystem`，内部管理多个底层 filesystem 实例，实现路径到 FS 的映射。

```python
class MountFileSystem(AbstractFileSystem):
    def __init__(self, mounts: list[Mount]):
        self.mounts = sorted(mounts, key=lambda m: m.path)
        self._cache = {}
    
    def _resolve(self, path: str) -> tuple[AbstractFileSystem, str]:
        # Find matching mount and return (fs, relative_path)
        ...
```

**Advantages**:
- **完全控制**：自主实现所有文件操作逻辑
- **性能优化**：可为 MCP 特定用例优化
- **零外部依赖**：不需要 fsspec-union 等第三方库

**Disadvantages**:
- **开发成本高**：需要完整实现所有 fsspec 方法
- **维护负担**：需跟随 fsspec API 变化更新
- **社区兼容性**：可能与其他 fsspec 生态工具不兼容

**Evaluation**:
| Criterion | Score | Notes |
|-----------|-------|-------|
| Performance | 8/10 | 可针对场景优化 |
| Scalability | 7/10 | 自定义缓存策略 |
| Maintainability | 4/10 | 大量代码需要维护 |
| Extensibility | 6/10 | 需手动支持新后端 |
| Compatibility | 7/10 | 需完整实现协议 |
| Resource Efficiency | 8/10 | 可控内存使用 |

**Effort Estimate**: 3-4 weeks, 2 engineers
**Risk Assessment**: Medium - implementation complexity, testing burden

---

### Option 2: fsspec-union + DirFileSystem Composition

**Description**: 使用第三方库 `fsspec-union` 实现联合文件系统，结合 `DirFileSystem` 进行路径前缀映射。

```python
from fsspec_union import UnionFileSystem
from fsspec.implementations.dirfs import DirFileSystem

# Session overlay
overlay_fs = DirFileSystem(f"/sessions/{session_id}", memory_fs)
base_fs = DirFileSystem("/templates", local_fs)

# Union: overlay (RW) + base (RO)
union_fs = UnionFileSystem([overlay_fs, base_fs])
```

**Advantages**:
- **成熟实现**：fsspec-union 经过生产验证
- **快速集成**：较少的自定义代码
- **社区兼容**：与 fsspec 生态完全兼容
- **稳定维护**：由社区维护底层逻辑

**Disadvantages**:
- **额外依赖**：增加 `fsspec-union` 依赖
- **性能开销**：多层的线性搜索在大量文件时影响性能
- **定制受限**：修改底层行为需要 fork

**Evaluation**:
| Criterion | Score | Notes |
|-----------|-------|-------|
| Performance | 6/10 | 多层的线性搜索开销 |
| Scalability | 7/10 | 测试过大规模使用 |
| Maintainability | 9/10 | 大部分逻辑在外部库 |
| Extensibility | 8/10 | fsspec 标准接口 |
| Compatibility | 9/10 | 完全兼容 |
| Resource Efficiency | 7/10 | 依赖库的内存模式 |

**Effort Estimate**: 1-2 weeks, 1-2 engineers
**Risk Assessment**: Low - proven pattern, stable dependency

---

### Option 3: Hybrid Approach with Custom Session Layer

**Description**: 自定义 SessionFileSystem 管理层，底层使用 fsspec，但在 session 层做 overlay 和隔离，类似 Docker 的 overlay2 + 挂载命名空间。

```python
class SessionFileSystemManager:
    def __init__(self, config: OverlayConfig):
        self._mounts = config.mounts
        self._sessions: dict[str, OverlayFS] = {}
    
    def get_session_fs(self, session_id: str) -> OverlayFS:
        if session_id not in self._sessions:
            # Create session-specific overlay
            self._sessions[session_id] = self._create_overlay(session_id)
        return self._sessions[session_id]
    
    def _create_overlay(self, session_id: str) -> OverlayFS:
        # Create upperdir (session workspace)
        upper = MemoryFileSystem()
        upper.mkdirs(f"/sessions/{session_id}", exist_ok=True)
        
        # Create lowerdirs from config
        lowers = [DirFileSystem(m.path, m.fs) for m in self._mounts if m.read_only]
        
        return OverlayFS(upper, lowers)
```

**Advantages**:
- **最佳灵活性**：平衡自定义和复用
- **Session 感知的优化**：可在 session 层做缓存和优化
- **渐进式迁移**：可逐步替换底层实现
- **符合现有架构**：与当前 session_id 设计对齐

**Disadvantages**:
- **中等复杂度**：需要设计清晰的层间接口
- **测试复杂度**：多层交互增加测试难度

**Evaluation**:
| Criterion | Score | Notes |
|-----------|-------|-------|
| Performance | 8/10 | 可在多层优化 |
| Scalability | 8/10 | Session 级隔离天然支持 |
| Maintainability | 8/10 | 清晰分层，职责单一 |
| Extensibility | 9/10 | 各层可独立演进 |
| Compatibility | 9/10 | 保持现有 API，增加新能力 |
| Resource Efficiency | 9/10 | Session 级资源管理 |

**Effort Estimate**: 2-3 weeks, 1-2 engineers
**Risk Assessment**: Low-Medium - clear architecture, incremental delivery

---

### Comparative Summary

| Option | Performance | Maintainability | Extensibility | Effort | Risk | **Score** |
|--------|-------------|-----------------|---------------|--------|------|-----------|
| Option 1: Pure fsspec | 8 | 4 | 6 | High | Medium | 6.5 |
| Option 2: fsspec-union | 6 | 9 | 8 | Low | Low | 7.2 |
| **Option 3: Hybrid (推荐)** | 8 | 8 | 9 | Medium | Low | **8.5** |

---

## Recommendation

### 推荐方案: Option 3 - Hybrid Approach

**理由**:
1. **架构对齐**：与现有 session-based 设计完全契合，自然演进而非推翻重来
2. **平衡取舍**：在开发效率和系统能力之间取得最佳平衡
3. **渐进交付**：可分阶段实现，降低集成风险
4. **扩展性强**：支持未来添加更多后端和高级功能
5. **维护友好**：清晰的分层架构，便于长期维护

**接受的技术债**:
- 相比 Option 1，对极端性能场景的优化空间较小
- 相比 Option 2，需要维护更多自定义代码

**缓解措施**:
- 底层 fsspec 操作封装为独立模块，便于后续替换优化
- 核心逻辑完善测试覆盖，确保重构安全

---

## Technical Design (Recommended Approach)

### 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    MCP Server Layer                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   Tools      │  │  Resources   │  │  Health Checks   │  │
│  │  (existing)  │  │   (new)      │  │                  │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              Session FileSystem Manager                      │
│         ┌─────────────────────────────────┐                │
│         │  Session-scoped Overlay FS      │                │
│         │  - Upper: MemoryFileSystem      │                │
│         │  - Lower: Configured mounts     │                │
│         └─────────────────────────────────┘                │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                   fsspec Abstract Layer                      │
│  ┌─────────────┐ ┌─────────────┐ ┌────────────────────────┐ │
│  │   LocalFS   │ │    S3FS     │ │    MemoryFS            │ │
│  └─────────────┘ └─────────────┘ └────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 核心组件设计

#### 1. Mount Configuration Model

```python
# config/models.py
from pydantic import BaseModel, Field
from typing import Literal

class MountConfig(BaseModel):
    """Mount point configuration"""
    name: str = Field(..., description="Mount name for reference")
    source: str = Field(..., description="Source URI (s3://, file://, memory://)")
    mount_point: str = Field(..., description="Mount path within scratchpad namespace")
    mode: Literal["ro", "rw"] = Field(default="ro", description="Read-only or read-write")
    priority: int = Field(default=0, description="Priority for overlay ordering (higher = checked first)")
    options: dict = Field(default_factory=dict, description="Backend-specific options")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "templates",
                "source": "file:///opt/mcp/templates",
                "mount_point": "/templates",
                "mode": "ro"
            }
        }

class OverlayConfig(BaseModel):
    """Overlay filesystem configuration"""
    mounts: list[MountConfig] = Field(default_factory=list)
    default_mount: str | None = Field(default=None, description="Default mount for session workspace")
    cache_enabled: bool = Field(default=True)
    cache_dir: str | None = Field(default=None)
```

#### 2. Session FileSystem Manager

```python
# fs/session_manager.py
import fsspec
from fsspec.implementations.dirfs import DirFileSystem
from fsspec.implementations.memory import MemoryFileSystem
from typing import Protocol
import uuid

class OverlayFileSystem(Protocol):
    """Protocol for session-specific overlay filesystem"""
    
    def ls(self, path: str, **kwargs) -> list[dict]:
        ...
    
    def open(self, path: str, mode: str = "r", **kwargs):
        ...
    
    def exists(self, path: str) -> bool:
        ...
    
    def isfile(self, path: str) -> bool:
        ...
    
    def isdir(self, path: str) -> bool:
        ...
    
    def info(self, path: str) -> dict:
        ...


class SessionFileSystemManager:
    """
    Manages per-session overlay filesystem instances.
    
    Architecture:
    - Upper layer: MemoryFileSystem per session (read-write)
    - Lower layers: Configured mounts from OverlayConfig (read-only typically)
    - Union: Overlay layers with union logic
    """
    
    def __init__(self, config: OverlayConfig):
        self.config = config
        self._mounts: dict[str, AbstractFileSystem] = {}
        self._sessions: dict[str, OverlayFileSystem] = {}
        self._initialize_mounts()
    
    def _initialize_mounts(self):
        """Initialize underlying filesystems from config"""
        for mount in self.config.mounts:
            self._mounts[mount.name] = self._create_filesystem(mount)
    
    def _create_filesystem(self, mount: MountConfig) -> AbstractFileSystem:
        """Create fsspec filesystem from mount configuration"""
        if mount.source.startswith("s3://"):
            return fsspec.filesystem(
                "s3",
                **mount.options
            )
        elif mount.source.startswith("file://"):
            return fsspec.filesystem(
                "file",
                **mount.options
            )
        elif mount.source == "memory://":
            return MemoryFileSystem()
        else:
            raise ValueError(f"Unsupported scheme in: {mount.source}")
    
    def get_session_fs(self, session_id: str) -> OverlayFileSystem:
        """
        Get or create session-scoped overlay filesystem.
        
        Each session gets:
        1. A memory-based upper layer for writes
        2. Access to configured readonly lower layers
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = self._create_session_fs(session_id)
        return self._sessions[session_id]
    
    def _create_session_fs(self, session_id: str) -> OverlayFileSystem:
        """Create new session overlay filesystem"""
        # TODO: Implement actual overlay logic
        # For MVP: return DirFileSystem scoped to session path
        mem_fs = MemoryFileSystem()
        session_path = f"/sessions/{session_id}"
        mem_fs.makedirs(session_path, exist_ok=True)
        
        return DirFileSystem(session_path, mem_fs)
    
    def cleanup_session(self, session_id: str):
        """Cleanup session resources"""
        if session_id in self._sessions:
            # TODO: Close files, cleanup memory
            del self._sessions[session_id]
```

#### 3. Overlay FileSystem Implementation

```python
# fs/overlay.py
from typing import Sequence
from fsspec import AbstractFileSystem
from fsspec.implementations.memory import MemoryFileSystem

class OverlayFileSystem(AbstractFileSystem):
    """
    Multi-layer overlay filesystem implementation.
    
    Inspired by Docker overlay2, implements:
    - Write operations go to upper layer only
    - Read operations check layers in priority order
    - Copy-on-write for file modifications
    - Whiteout handling for deletions
    
    Layer ordering (higher priority = first checked):
    - Layer 0: Upper (writable) - session workspace
    - Layer 1+: Lower (readonly) - configured mounts
    """
    
    protocol = "overlay"
    
    def __init__(
        self,
        upper: AbstractFileSystem,
        lowers: Sequence[AbstractFileSystem],
        **kwargs
    ):
        super().__init__(**kwargs)
        self.upper = upper
        self.lowers = lowers
        self._layers = [upper] + list(lowers)
    
    # ─────────────────────────────────────────────────────────────
    # Path Resolution
    # ─────────────────────────────────────────────────────────────
    
    def _resolve(self, path: str) -> tuple[AbstractFileSystem, str, int]:
        """
        Resolve path to filesystem and relative path.
        
        Returns:
            tuple: (filesystem, relative_path, layer_index)
            For write operations, always returns upper layer.
        """
        # Check layers in priority order for read operations
        for idx, layer in enumerate(self._layers):
            if layer.exists(path):
                return layer, path, idx
        
        # Path not found - return upper for potential write
        return self.upper, path, 0
    
    # ─────────────────────────────────────────────────────────────
    # Read Operations
    # ─────────────────────────────────────────────────────────────
    
    def ls(self, path: str, detail: bool = True, **kwargs):
        """List directory, merging results from all layers"""
        seen = set()
        results = []
        
        for layer in self._layers:
            if not layer.isdir(path):
                continue
            
            try:
                items = layer.ls(path, detail=detail, **kwargs)
                for item in items:
                    name = item["name"] if detail else item
                    if name not in seen:
                        seen.add(name)
                        # Mark layer source if detail=True
                        if detail:
                            item["_layer"] = layer
                        results.append(item)
            except FileNotFoundError:
                continue
        
        return results
    
    def exists(self, path: str) -> bool:
        """Check if path exists in any layer"""
        return any(layer.exists(path) for layer in self._layers)
    
    def isfile(self, path: str) -> bool:
        """Check if path is file in any layer"""
        return any(layer.isfile(path) for layer in self._layers if layer.exists(path))
    
    def isdir(self, path: str) -> bool:
        """Check if path is directory in any layer"""
        return any(layer.isdir(path) for layer in self._layers if layer.exists(path))
    
    def info(self, path: str, **kwargs) -> dict:
        """Get file info from first matching layer"""
        fs, rel_path, layer_idx = self._resolve(path)
        info = fs.info(rel_path, **kwargs)
        info["_layer"] = layer_idx
        return info
    
    def open(self, path: str, mode: str = "rb", **kwargs):
        """
        Open file handle.
        
        Read modes: Check layers in order
        Write modes: Always use upper layer (with copy-on-write if needed)
        """
        if "w" in mode or "a" in mode or "+" in mode:
            # Write mode - ensure copy-on-write if exists in lower
            return self._open_write(path, mode, **kwargs)
        else:
            # Read mode - use first matching layer
            fs, rel_path, _ = self._resolve(path)
            return fs.open(rel_path, mode, **kwargs)
    
    def _open_write(self, path: str, mode: str, **kwargs):
        """Handle write with copy-on-write semantics"""
        # If exists in lower but not upper, copy first
        if not self.upper.exists(path):
            for layer in self.lowers:
                if layer.exists(path):
                    self._copy_up(path, layer)
                    break
        
        return self.upper.open(path, mode, **kwargs)
    
    def _copy_up(self, path: str, source_layer: AbstractFileSystem):
        """Copy file from lower layer to upper (copy-on-write)"""
        import shutil
        
        # Ensure parent directories exist
        parent = self.upper._parent(path)
        if parent:
            self.upper.makedirs(parent, exist_ok=True)
        
        # Copy file content
        with source_layer.open(path, "rb") as src:
            with self.upper.open(path, "wb") as dst:
                shutil.copyfileobj(src, dst)
    
    # ─────────────────────────────────────────────────────────────
    # Write Operations (Upper Layer Only)
    # ─────────────────────────────────────────────────────────────
    
    def mkdir(self, path: str, create_parents: bool = True, **kwargs):
        """Create directory in upper layer"""
        return self.upper.mkdir(path, create_parents=create_parents, **kwargs)
    
    def makedirs(self, path: str, exist_ok: bool = False):
        """Create directories recursively in upper layer"""
        return self.upper.makedirs(path, exist_ok=exist_ok)
    
    def rm(self, path: str, recursive: bool = False, maxdepth: int | None = None):
        """Remove file or directory (whiteout in upper layer)"""
        if self.upper.exists(path):
            return self.upper.rm(path, recursive=recursive, maxdepth=maxdepth)
        
        # If exists in lower layers, create whiteout marker
        if any(layer.exists(path) for layer in self.lowers):
            self._create_whiteout(path)
    
    def _create_whiteout(self, path: str):
        """Create whiteout marker for deleted files in lower layers"""
        whiteout_path = path + ".wh."
        with self.upper.open(whiteout_path, "w") as f:
            f.write("")
    
    def rm_file(self, path: str):
        """Remove file"""
        return self.rm(path, recursive=False)
    
    def cp_file(self, path1: str, path2: str, **kwargs):
        """Copy file within overlay"""
        # Copy source to upper first if needed
        if not self.upper.exists(path1):
            self._copy_up(path1, self._get_source_layer(path1))
        
        # Now copy within upper
        return self.upper.cp_file(path1, path2, **kwargs)
    
    def _get_source_layer(self, path: str) -> AbstractFileSystem:
        """Get the layer containing path"""
        for layer in self._layers:
            if layer.exists(path):
                return layer
        raise FileNotFoundError(path)
    
    def mv(self, path1: str, path2: str, **kwargs):
        """Move file (copy then delete)"""
        self.cp_file(path1, path2, **kwargs)
        self.rm(path1)
```

#### 4. Whiteout 生命周期与文件删除机制

**Whiteout 设计原理**:

Overlay 文件系统需要处理下层（lower）只读层中的文件删除。由于下层是只读的，无法真正删除文件，因此使用 whiteout 机制：

```
场景：删除只存在于 lower_0 层的文件

[Upper Layer - RW]          [Lower_0 Layer - RO]
  (空)                          templates/
                                   └─ readme.md  ← 要删除的文件
                                     
删除操作后：

[Upper Layer - RW]          [Lower_0 Layer - RO]
  templates/                      templates/
    └─ readme.md.wh.                  └─ readme.md
      (whiteout marker)
```

**Whiteout 生命周期**:

```
1. 创建 (Delete Operation)
   ├─ 用户调用 rm("/templates/readme.md")
   ├─ 检查：文件存在于 lower_0 但不在 upper
   ├─ 在 upper 层创建 whiteout 标记文件
   └─ 标记路径: "/templates/readme.md.wh."

2. 读取时解析 (Read Resolution)
   ├─ 用户调用 exists("/templates/readme.md")
   ├─ 遍历所有层检查文件
   ├─ 发现 whiteout 标记 → 文件视为不存在
   └─ 返回 False

3. 目录列表过滤 (Directory Listing)
   ├─ 用户调用 ls("/templates/")
   ├─ 合并所有层的结果
   ├─ 过滤掉有 whiteout 标记的文件
   └─ readme.md 不会出现在列表中

4. 再次创建 (Recreate After Delete)
   ├─ 用户调用 write("/templates/readme.md", content)
   ├─ 检查到有 whiteout 标记
   ├─ 删除 whiteout 标记
   └─ 创建新文件（正常写入流程）

5. 清理 (Cleanup)
   ├─ Session 结束或显式清理时
   ├─ 遍历 upper 层的 .wh.* 文件
   └─ 可选：定期清理 stale whiteouts
```

**Whiteout 标记格式**:

```python
# Whiteout 文件命名约定
WHITEOUT_PREFIX = ".wh."
WHITEOUT_SUFFIX = ""

# 示例转换
original_path = "/templates/readme.md"
whiteout_path = "/templates/readme.md.wh."

# 目录 whiteout（递归删除）
original_dir = "/templates/"
whiteout_dir = "/templates.wh/"
```

**文件解析算法**:

```python
def resolve_path(self, path: str) -> ResolutionResult:
    """
    解析路径，考虑 whiteout 机制。
    
    优先级（从高到低）：
    1. Upper 层存在的文件/目录
    2. Upper 层的 whiteout 标记（文件视为不存在）
    3. Lower 层存在的文件/目录
    4. 文件不存在
    """
    # 1. 检查 upper 层
    if self.upper.exists(path):
        return ResolutionResult(self.upper, path, layer="upper")
    
    # 2. 检查 whiteout 标记
    if self.upper.exists(path + ".wh."):
        return ResolutionResult(None, path, layer="whiteout", exists=False)
    
    # 3. 检查 lower 层
    for idx, lower in enumerate(self.lowers):
        if lower.exists(path):
            return ResolutionResult(lower, path, layer=f"lower_{idx}")
    
    # 4. 不存在
    return ResolutionResult(None, path, exists=False)
```

**冲突处理**:

| 场景 | 上层状态 | 下层状态 | 行为 |
|------|----------|----------|------|
| 删除下层存在的文件 | - | 存在 | 创建 whiteout |
| 删除上层存在的文件 | 存在 | - | 直接删除 |
| 删除两层都存在的文件 | 存在 | 存在 | 删除上层 + 创建 whiteout |
| 创建与 whiteout 同名的文件 | .wh. 存在 | - | 移除 whiteout + 创建新文件 |
| 重命名涉及下层 | - | 存在 | copy-up + whiteout + 新位置创建 |

**清理策略**:

```python
class WhiteoutManager:
    """管理 whiteout 标记的生命周期"""
    
    def cleanup_stale_whiteouts(self, session_id: str):
        """
        清理过期的 whiteout 标记。
        
        调用时机：
        1. Session 显式 cleanup 时
        2. 定期后台任务（如每小时）
        3. 内存压力时
        """
        upper_fs = self.get_session_upper(session_id)
        
        for root, dirs, files in upper_fs.walk("/"):
            for file in files:
                if file.endswith(".wh."):
                    whiteout_path = f"{root}/{file}"
                    original_path = whiteout_path[:-4]  # 移除 .wh.
                    
                    # 如果原始文件在 lower 层已被删除，则清理 whiteout
                    if not any(lower.exists(original_path) for lower in self.lowers):
                        upper_fs.rm(whiteout_path)
                        logger.debug(f"Cleaned stale whiteout: {whiteout_path}")
    
    def get_visible_files(self, session_id: str, path: str) -> list[str]:
        """
        获取可见文件列表（已考虑 whiteout 过滤）。
        """
        all_files = self.collect_from_all_layers(path)
        whiteouts = self.collect_whiteouts(path)
        
        # 过滤掉有 whiteout 标记的文件
        return [f for f in all_files if f not in whiteouts]
```

**性能考虑**:

- Whiteout 检查增加一次 upper 层查找，但 overhead 极小
- 目录列表需要额外过滤，复杂度 O(n) 其中 n = 文件数
- 建议在 SessionFileSystemManager 层缓存 whiteout 列表（per-directory cache）

### MCP Resources 集成

#### 1. Resource URI 方案

```
scratchpad://<session_id>/<path>
```

**设计原则**：
- 不暴露底层 mount 结构，下游无需了解文件存储在哪个后端
- 路径是 overlay 视图中的统一路径，mount 的组合在服务端处理

**示例 URIs**:
- `scratchpad://sess_123/project/main.py`
- `scratchpad://sess_123/readme.md`
- `scratchpad://sess_123/archive/data/file.csv`

**注意**：下游通过统一的 `scratchpad://{session_id}/{path}` 访问，无需知道文件实际存储在 S3、本地还是内存中。

#### 2. Resource 响应格式 (XML Wrapper)

所有 Resource 响应都包含 XML wrapper，提供完整的 metadata 信息，帮助下游理解文件上下文。

```python
# resources/scratchpad_resources.py
import json
import base64
from xml.etree.ElementTree import Element, tostring
from urllib.parse import unquote
from mcp.server.fastmcp import FastMCP
from mcp.types import TextResourceContents, BlobResourceContents

def build_file_resource_xml(
    session_id: str,
    file_path: str,
    content: str | bytes,
    info: dict,
    is_preview: bool = False
) -> str:
    """
    Build XML-wrapped file resource response with full metadata.
    
    Structure:
    <file_resource>
        <metadata>
            <uri>scratchpad://{session_id}/{file_path}</uri>
            <session_id>{session_id}</session_id>
            <path>{file_path}</path>
            <name>{filename}</name>
            <size>{bytes}</size>
            <mime_type>{mime}</mime_type>
            <is_directory>{true/false}</is_directory>
            <layer>{upper|lower_N}</layer>
            <modified_at>{ISO8601}</modified_at>
            <version>{int}</version>
            <permissions>{ro|rw}</permissions>
        </metadata>
        <content preview="{true|false}">
            <![CDATA[...actual content...]]>
        </content>
        <access>
            <method>direct_read</method>
            <method>range_read</method>
        </access>
    </file_resource>
    """
    root = Element("file_resource")
    
    # Metadata section
    meta = Element("metadata")
    Element("uri").text = f"scratchpad://{session_id}/{file_path}"
    Element("session_id").text = session_id
    Element("path").text = file_path
    Element("name").text = info.get("name", file_path.split("/")[-1])
    Element("size").text = str(info.get("size", 0))
    Element("mime_type").text = info.get("type", "application/octet-stream")
    Element("is_directory").text = str(info.get("is_directory", False)).lower()
    Element("layer").text = info.get("_layer", "unknown")  # upper or lower_N
    Element("modified_at").text = info.get("updated_at", info.get("mtime", ""))
    Element("version").text = str(info.get("version", 1))
    Element("permissions").text = "rw" if info.get("_layer") == "upper" else "ro"
    root.append(meta)
    
    # Content section (with CDATA for text)
    content_elem = Element("content")
    content_elem.set("preview", str(is_preview).lower())
    if isinstance(content, str):
        content_elem.text = f"<![CDATA[{content}]]>"
    else:
        content_elem.text = base64.b64encode(content).decode()
        content_elem.set("encoding", "base64")
    root.append(content_elem)
    
    # Access methods
    access = Element("access")
    Element("method").text = "direct_read"
    if info.get("size", 0) > 1024 * 1024:  # > 1MB
        Element("method").text = "range_read"
        Element("method").text = "chunked_download"
    root.append(access)
    
    return tostring(root, encoding="unicode")


class ScratchpadResources:
    """MCP Resources integration for scratchpad filesystem"""
    
    def __init__(self, mcp: FastMCP, fs_manager: SessionFileSystemManager):
        self.mcp = mcp
        self.fs_manager = fs_manager
        self._register_handlers()
    
    def _register_handlers(self):
        """Register MCP resource handlers"""
        
        @self.mcp.resource("scratchpad://{session_id}/{path:path}")
        async def read_scratchpad_file(session_id: str, path: str) -> str:
            """
            Read a file from scratchpad filesystem.
            Returns XML-wrapped response with full metadata.
            """
            from utils import mcp_error  # Assume existing error utility
            
            # Decode path
            file_path = unquote(path)
            
            try:
                fs = self.fs_manager.get_session_fs(session_id)
                
                if not fs.exists(file_path):
                    return mcp_error(
                        "RESOURCE_NOT_FOUND",
                        f"File not found: {file_path}"
                    )
                
                # Get file info
                info = fs.info(file_path)
                
                # Handle directory
                if fs.isdir(file_path):
                    items = fs.ls(file_path, detail=True)
                    return build_directory_resource_xml(session_id, file_path, items)
                
                # Determine if this is a large file
                file_size = info.get("size", 0)
                max_inline_size = 1024 * 1024  # 1MB
                
                if file_size > max_inline_size:
                    # Large file - return metadata + preview only
                    return build_large_file_resource_xml(
                        session_id, file_path, info, fs
                    )
                
                # Read full content
                mime_type = self._guess_mime_type(file_path)
                
                if mime_type.startswith("text/"):
                    with fs.open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                else:
                    with fs.open(file_path, "rb") as f:
                        content = f.read()
                
                return build_file_resource_xml(
                    session_id=session_id,
                    file_path=file_path,
                    content=content,
                    info=info,
                    is_preview=False
                )
                
            except Exception as e:
                return mcp_error("RESOURCE_READ_ERROR", str(e))
        
        @self.mcp.resource("scratchpad://{session_id}/")
        async def list_session_root(session_id: str) -> str:
            """List root directory of session"""
            return await read_scratchpad_file(session_id, "/")
    
    def _guess_mime_type(self, path: str) -> str:
        """Guess MIME type from file extension"""
        import mimetypes
        mime, _ = mimetypes.guess_type(path)
        return mime or "application/octet-stream"


def build_directory_resource_xml(session_id: str, dir_path: str, items: list) -> str:
    """Build XML response for directory listing"""
    from xml.etree.ElementTree import Element, tostring
    
    root = Element("directory_resource")
    
    # Metadata
    meta = Element("metadata")
    Element("uri").text = f"scratchpad://{session_id}/{dir_path}"
    Element("path").text = dir_path
    Element("item_count").text = str(len(items))
    root.append(meta)
    
    # Items list
    items_elem = Element("items")
    for item in items:
        item_elem = Element("item")
        item_elem.set("name", item.get("name", ""))
        item_elem.set("type", "directory" if item.get("is_directory") else "file")
        item_elem.set("size", str(item.get("size", 0)))
        item_elem.set("modified_at", str(item.get("updated_at", "")))
        items_elem.append(item_elem)
    root.append(items_elem)
    
    return tostring(root, encoding="unicode")


def build_large_file_resource_xml(
    session_id: str, 
    file_path: str, 
    info: dict,
    fs
) -> str:
    """
    Build response for large files (> 1MB).
    Returns metadata + preview + access methods.
    """
    from xml.etree.ElementTree import Element, tostring
    import base64
    
    root = Element("file_resource")
    root.set("large_file", "true")
    
    # Full metadata
    meta = Element("metadata")
    Element("uri").text = f"scratchpad://{session_id}/{file_path}"
    Element("path").text = file_path
    Element("name").text = info.get("name", file_path.split("/")[-1])
    Element("size").text = str(info.get("size", 0))
    Element("size_human").text = _format_bytes(info.get("size", 0))
    Element("mime_type").text = info.get("type", "application/octet-stream")
    Element("modified_at").text = str(info.get("updated_at", ""))
    meta.append(Element("checksum", {"type": "noop"}))  # Placeholder
    root.append(meta)
    
    # Preview (first 100KB)
    preview_size = min(102400, info.get("size", 0))
    preview_elem = Element("preview")
    preview_elem.set("size", str(preview_size))
    
    try:
        with fs.open(file_path, "rb") as f:
            preview_data = f.read(preview_size)
            # Try to decode as text
            try:
                text_preview = preview_data.decode("utf-8")
                preview_elem.text = f"<![CDATA[{text_preview}...]]>"
            except UnicodeDecodeError:
                preview_elem.text = base64.b64encode(preview_data).decode()
                preview_elem.set("encoding", "base64")
    except Exception as e:
        preview_elem.text = f"Preview unavailable: {e}"
    
    root.append(preview_elem)
    
    # Access methods for full content
    access = Element("access")
    Element("method").text = "range_read"
    Element("method").text = "scratchpad_read_file_tool"
    
    # If S3 backend, could add presigned URL option
    if info.get("_backend") == "s3":
        Element("method").text = "presigned_url"
    
    root.append(access)
    
    return tostring(root, encoding="unicode")


def _format_bytes(num: int) -> str:
    """Format bytes to human readable"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"
```

#### 3. Resource 响应示例

**正常文件响应**（扁平化 XML 格式）:
```xml
<file_resource><metadata><uri>scratchpad://sess_123/src/main.py</uri><session_id>sess_123</session_id><path>src/main.py</path><name>main.py</name><size>2048</size><mime_type>text/x-python</mime_type><is_directory>false</is_directory><layer>upper</layer><modified_at>2026-03-19T10:30:00Z</modified_at><version>3</version><permissions>rw</permissions></metadata><content preview="false">1 | def main():
2 |     print("Hello World")
3 | ...</content><access><method>direct_read</method></access></file_resource>
```

**大文件响应**（扁平化 XML 格式）:
```xml
<file_resource large_file="true"><metadata><uri>scratchpad://sess_123/data/large.csv</uri><path>data/large.csv</path><name>large.csv</name><size>524288000</size><size_human>500.0 MB</size_human><mime_type>text/csv</mime_type><modified_at>2026-03-19T10:00:00Z</modified_at></metadata><preview size="102400">1 | id,name,value
2 | 1,Alice,100
3 | 2,Bob,200
4 | ...</preview><access><method>range_read</method><method>scratchpad_read_file_tool</method></access></file_resource>
```

**目录列表响应**（扁平化 XML 格式）:
```xml
<directory_resource><metadata><uri>scratchpad://sess_123/src/</uri><path>src/</path><item_count>3</item_count></metadata><items><item name="__init__.py" type="file" size="0" modified_at="2026-03-19T10:00:00Z"/><item name="main.py" type="file" size="2048" modified_at="2026-03-19T10:30:00Z"/><item name="utils" type="directory" size="0" modified_at="2026-03-19T09:00:00Z"/></items></directory_resource>
```

#### 3. 多模态文件支持（图片、PDF 等）

方案支持多模态文件（图片、PDF、音频等）的存储和访问。

**MCP 协议层设计**:

根据 MCP 规范，图片资源应返回 `ImageResourceContents` 类型（或其他具体的资源类型）。

**关键问题处理**:

1. **URI 声明**: OpenAI 的 resource content 格式中没有 `uri` 字段，因此 URI 必须在文本/XML 内容中声明
2. **Client 能力检测**: MCP 连接初始化时可以交换能力信息，检测 client 是否支持多模态
3. **Fallback**: 如果 client 不支持多模态，只返回文本描述（包含 metadata）

**Client 能力协商**:

```python
# capability_detection.py

class ClientCapabilityDetector:
    """Detect client capabilities during MCP initialization"""
    
    def __init__(self):
        self.supports_multimodal = False
        self.supports_images = False
        self.supports_pdf = False
        self.max_image_size = 512 * 1024  # Default limit
    
    def on_initialize(self, client_capabilities: dict):
        """Called during MCP initialize handshake"""
        # Check for multimodal support in client capabilities
        experimental = client_capabilities.get("experimental", {})
        
        # OpenAI-style capabilities
        if "multimodal" in experimental:
            self.supports_multimodal = experimental["multimodal"].get("enabled", False)
            self.supports_images = experimental["multimodal"].get("images", False)
            self.max_image_size = experimental["multimodal"].get("maxImageSize", 512 * 1024)
        
        # Claude/Anthropic-style capabilities
        if "imageSupport" in client_capabilities:
            self.supports_images = client_capabilities["imageSupport"]
        
        print(f"Client capabilities detected:")
        print(f"  - Multimodal: {self.supports_multimodal}")
        print(f"  - Images: {self.supports_images}")
        print(f"  - Max image size: {self.max_image_size / 1024:.0f}KB")


# Server capability advertisement
SERVER_CAPABILITIES = {
    "resources": {
        "supportedTypes": [
            "text/resource",
            "image/resource",
            "binary/resource"
        ],
        "multimodal": {
            "enabled": True,
            "imageFormats": ["image/png", "image/jpeg", "image/gif", "image/webp"],
            "maxImageSize": 10 * 1024 * 1024,  # 10MB
            "thumbnailGeneration": True
        }
    }
}
```

**资源类型定义**:

```python
# mcp_types_extensions.py
from dataclasses import dataclass
from typing import Literal

@dataclass
class ImageResourceContents:
    """
    MCP Image Resource Contents.
    Note: OpenAI format doesn't have 'uri' field - URI is embedded in content or context.
    """
    type: Literal["image"] = "image"
    mimeType: str  # image/png, image/jpeg, etc.
    data: str  # base64 encoded image data
    # uri field intentionally NOT included (OpenAI compatibility)

@dataclass  
class TextResourceContents:
    """Text resource with metadata"""
    type: Literal["text"] = "text"
    text: str  # Content with embedded metadata
    mimeType: str = "text/plain"

# Union type for resource contents
ResourceContents = ImageResourceContents | TextResourceContents
```

**多模态资源处理实现**:

```python
# resources/multimodal.py
import base64
import io
import json
from pathlib import Path
from PIL import Image
from xml.etree.ElementTree import Element, tostring

# 支持的图片格式
SUPPORTED_IMAGE_TYPES = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp',
    'image/svg+xml': '.svg',
    'image/bmp': '.bmp',
}


def is_image_file(mime_type: str) -> bool:
    """Check if file is an image"""
    return mime_type.startswith('image/')


class MultimodalResourceHandler:
    """Handler for multi-modal file resources with client capability awareness"""
    
    def __init__(
        self,
        fs_manager: SessionFileSystemManager,
        config: MultimodalConfig,
        capability_detector: ClientCapabilityDetector
    ):
        self.fs_manager = fs_manager
        self.config = config
        self.capabilities = capability_detector
    
    async def read_resource(
        self,
        session_id: str,
        file_path: str
    ) -> list[ImageResourceContents | TextResourceContents]:
        """
        Read a resource, adapting to client capabilities.
        
        - If client supports images: return ImageResourceContents
        - If not: return TextResourceContents with metadata/description only
        """
        fs = self.fs_manager.get_session_fs(session_id)
        
        if not fs.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        info = fs.info(file_path)
        mime_type = self._guess_mime_type(file_path)
        
        # Check if it's an image
        is_image = is_image_file(mime_type)
        
        # If client doesn't support multimodal, return text-only
        if is_image and not self.capabilities.supports_images:
            return [self._build_text_only_response(
                session_id, file_path, info, mime_type
            )]
        
        # Read content
        with fs.open(file_path, "rb") as f:
            content = f.read()
        
        file_size = len(content)
        
        # Check size limits
        if file_size > self.capabilities.max_image_size:
            # Too large - return thumbnail or text description
            if is_image and self.config.thumbnail.enabled:
                thumbnail_data = self._generate_thumbnail(content)
                return [ImageResourceContents(
                    type="image",
                    mimeType=mime_type,
                    data=base64.b64encode(thumbnail_data).decode(),
                )]
            else:
                return [self._build_text_only_response(
                    session_id, file_path, info, mime_type, content
                )]
        
        # Return image content
        if is_image:
            return [ImageResourceContents(
                type="image",
                mimeType=mime_type,
                data=base64.b64encode(content).decode(),
            )]
        
        # For non-image binary (PDF, etc.), return text description
        return [self._build_text_only_response(
            session_id, file_path, info, mime_type, content
        )]
    
    def _build_text_only_response(
        self,
        session_id: str,
        file_path: str,
        info: dict,
        mime_type: str,
        content: bytes | None = None
    ) -> TextResourceContents:
        """
        Build text-only response for clients that don't support multimodal.
        URI is embedded in XML since OpenAI format lacks URI field.
        """
        # Build XML with embedded URI and metadata
        root = Element("file_resource")
        root.set("multimodal", "false")  # Client doesn't support multimodal
        root.set("type", "image" if is_image_file(mime_type) else "binary")
        
        # Metadata section - URI embedded here
        meta = Element("metadata")
        Element("uri").text = f"scratchpad://{session_id}/{file_path}"
        Element("path").text = file_path
        Element("name").text = info.get("name", Path(file_path).name)
        Element("size").text = str(info.get("size", 0))
        Element("mime_type").text = mime_type
        Element("description").text = f"{mime_type} file ({info.get('size', 0)} bytes)"
        
        if is_image_file(mime_type):
            try:
                if content:
                    img = Image.open(io.BytesIO(content))
                    Element("width").text = str(img.width)
                    Element("height").text = str(img.height)
            except Exception:
                pass
        
        root.append(meta)
        
        # Access instructions
        access = Element("access")
        access.text = "Client does not support multimodal. Use scratchpad_read_file tool with appropriate parameters to access this file."
        root.append(access)
        
        xml_str = tostring(root, encoding="unicode")
        
        return TextResourceContents(
            type="text",
            text=xml_str,
            mimeType="application/xml"
        )
    
    def _generate_thumbnail(self, image_data: bytes, max_size: int = 128) -> bytes:
        """Generate thumbnail for image"""
        try:
            img = Image.open(io.BytesIO(image_data))
            img.thumbnail((max_size, max_size))
            
            output = io.BytesIO()
            img_format = img.format or 'PNG'
            img.save(output, format=img_format)
            return output.getvalue()
        except Exception:
            return image_data[:4096]
    
    def _guess_mime_type(self, path: str) -> str:
        import mimetypes
        mime, _ = mimetypes.guess_type(path)
        return mime or "application/octet-stream"


@dataclass
class MultimodalConfig:
    """Configuration for multi-modal files"""
    enabled: bool = True
    max_inline_size: int = 512 * 1024  # 512KB
    thumbnail_size: int = 128
    thumbnail = None  # Nested dataclass placeholder
            "mime_type": mime_type,
            "size": len(content),
            "layer": info.get("_layer", "unknown"),
        }
        
        # Image-specific metadata
        if is_image_file(mime_type):
            try:
                img = Image.open(io.BytesIO(content))
                metadata["width"] = img.width
                metadata["height"] = img.height
                metadata["format"] = img.format
            except Exception:
                pass
        
        metadata_json = json.dumps(metadata, indent=2)
        
        # Determine if we need thumbnail
        file_size = len(content)
        is_large = file_size > self.config.max_inline_size
        
        if is_large and is_image_file(mime_type):
            # Large image - return metadata + thumbnail
            thumbnail_data = self._generate_thumbnail(content)
            return [
                TextResourceContents(
                    uri=f"scratchpad://{session_id}/{file_path}#metadata",
                    mimeType="application/json",
                    text=metadata_json,
                ),
                BlobResourceContents(
                    uri=f"scratchpad://{session_id}/{file_path}",
                    mimeType=mime_type,
                    blob=base64.b64encode(thumbnail_data).decode(),
                ),
            ]
        
        # Normal case - metadata + full content
        return [
            TextResourceContents(
                uri=f"scratchpad://{session_id}/{file_path}#metadata",
                mimeType="application/json",
                text=metadata_json,
            ),
            BlobResourceContents(
                uri=f"scratchpad://{session_id}/{file_path}",
                mimeType=mime_type,
                blob=base64.b64encode(content).decode(),
            ),
        ]
    
    def _generate_thumbnail(self, image_data: bytes, max_size: int = 128) -> bytes:
        """Generate thumbnail for image"""
        try:
            img = Image.open(io.BytesIO(image_data))
            img.thumbnail((max_size, max_size))
            
            output = io.BytesIO()
            img_format = img.format or 'PNG'
            img.save(output, format=img_format)
            return output.getvalue()
        except Exception:
            # Fallback: return partial content
            return image_data[:4096]
    
    def _guess_mime_type(self, path: str) -> str:
        import mimetypes
        mime, _ = mimetypes.guess_type(path)
        return mime or "application/octet-stream"


@dataclass
class MultimodalConfig:
    """Configuration for multi-modal files"""
    enabled: bool = True
    max_inline_size: int = 512 * 1024  # 512KB
    thumbnail_size: int = 128
```
    Element("method").text = "base64_inline"  # Current method
    
    if is_large:
        Element("method").text = "scratchpad_read_file_tool"
        Element("method").text = "range_read"
    
    if is_image:
        Element("method").text = "thumbnail"
        Element("method").text = "resize"
    
    # If from S3, could provide presigned URL
    if info.get("_backend") == "s3":
        Element("method").text = "presigned_url"
    
    root.append(access)
    
    # Image-specific metadata
    if is_image:
        img_meta = Element("image_metadata")
        try:
            img = Image.open(io.BytesIO(content))
            Element("width").text = str(img.width)
            Element("height").text = str(img.height)
            Element("format").text = img.format
            Element("mode").text = img.mode
        except Exception:
            pass
        root.append(img_meta)
    
    return tostring(root, encoding="unicode")


def generate_image_thumbnail(image_data: bytes, max_size: int = 128) -> bytes:
    """Generate thumbnail for image"""
    try:
        img = Image.open(io.BytesIO(image_data))
        img.thumbnail((max_size, max_size))
        
        output = io.BytesIO()
        format = img.format or 'PNG'
        img.save(output, format=format)
        return output.getvalue()
    except Exception:
        # Fallback: return original if thumbnail fails
        return image_data[:4096]  # Return partial content


def build_image_gallery_xml(
    session_id: str,
    directory: str,
    images: list[dict]  # List of {path, info, thumbnail_base64}
) -> str:
    """
    Build gallery view for directories containing multiple images
    
    Example:
    <image_gallery>
        <metadata>
            <directory>assets/screenshots/</directory>
            <image_count>5</image_count>
        </metadata>
        <images>
            <image>
                <name>screenshot_1.png</name>
                <path>assets/screenshots/screenshot_1.png</path>
                <width>1920</width>
                <height>1080</height>
                <size>245760</size>
                <thumbnail encoding="base64">...</thumbnail>
            </image>
            ...
        </images>
    </image_gallery>
    """
    root = Element("image_gallery")
    
    meta = Element("metadata")
    Element("directory").text = directory
    Element("image_count").text = str(len(images))
    root.append(meta)
    
    images_elem = Element("images")
    for img in images:
        img_elem = Element("image")
        Element("name").text = img["name"]
        Element("path").text = img["path"]
        Element("width").text = str(img.get("width", 0))
        Element("height").text = str(img.get("height", 0))
        Element("size").text = str(img.get("size", 0))
        
        thumb = Element("thumbnail")
        thumb.set("encoding", "base64")
        thumb.text = img.get("thumbnail_base64", "")
        img_elem.append(thumb)
        
        images_elem.append(img_elem)
    
    root.append(images_elem)
    return tostring(root, encoding="unicode")
```

**图片文件响应示例**:

**Case 1: Client 支持多模态 (ImageResourceContents)**

```python
# Returned type: ImageResourceContents
{
    "type": "image",
    "mimeType": "image/png",
    "data": "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAA..."
}
```

**Case 2: Client 不支持多模态 (TextResourceContents with embedded URI)**

由于 OpenAI 格式的 resource content 没有 `uri` 字段，URI 必须嵌入到 XML 内容中：

```xml
<file_resource multimodal="false" type="image">
  <metadata>
    <uri>scratchpad://sess_123/assets/logo.png</uri>
    <path>assets/logo.png</path>
    <name>logo.png</name>
    <size>24576</size>
    <mime_type>image/png</mime_type>
    <width>128</width>
    <height>128</height>
    <description>image/png file (24576 bytes)</description>
  </metadata>
  <access>
    Client does not support multimodal. 
    Use scratchpad_read_file tool with appropriate parameters to access this file.
  </access>
</file_resource>
```

**关键点说明**:

| 方面 | 支持多模态的 Client | 不支持多模态的 Client |
|------|------------------|-------------------|
| **返回类型** | `ImageResourceContents` | `TextResourceContents` |
| **mimeType** | `image/png` (实际 image) | `application/xml` |
| **URI 位置** | Context/registration 隐含 | 嵌入 XML `<uri>` 标签 |
| **数据位置** | `data` 字段 (base64) | 无数据，仅有描述 |
| **处理方式** | 直接渲染图片 | 用 tool 再次请求 |

**Client 能力协商示例**:

```python
# Client initialization (example capabilities)
client_capabilities = {
    "experimental": {
        "multimodal": {
            "enabled": True,
            "images": True,
            "maxImageSize": 2097152  # 2MB
        }
    }
}

# Server detects this and returns appropriate format
if capability_detector.supports_images:
    return ImageResourceContents(type="image", mimeType="image/png", data=base64_data)
else:
    return TextResourceContents(type="text", text=xml_with_embedded_uri)
```

**Binary 文件 (PDF) - 不支持多模态时**（扁平化 XML 格式）:
```xml
<file_resource multimodal="false" type="binary"><metadata><uri>scratchpad://sess_123/docs/report.pdf</uri><path>docs/report.pdf</path><name>report.pdf</name><size>1048576</size><mime_type>application/pdf</mime_type><description>application/pdf file (1048576 bytes)</description></metadata><access>Use scratchpad_read_file tool to access this file.</access></file_resource>
```

**目录列表（Text Resource）**:

```json
{
  "type": "text",
  "mimeType": "application/json",
      "text": "[{\"name\": \"main.py\", \"type\": \"file\", \"size\": 2048}, ...]"
    }
  ]
}
```

**PDF 文件响应**:
```xml
<multimodal_resource type="binary">
  <metadata>
    <uri>scratchpad://sess_123/docs/report.pdf</uri>
    <path>docs/report.pdf</path>
    <name>report.pdf</name>
    <size>1048576</size>
    <size_human>1.0 MB</size_human>
    <mime_type>application/pdf</mime_type>
    <is_image>false</is_image>
  </metadata>
  <content encoding="base64" size="1024" preview="true" truncated="true">
    JVBERi0xLjQKJdPr6eEKMSAwIG9iago8PAovVHlwZSAvQ2F0YWxvZwovUGFnZXMgMiAwIFIK...
  </content>
  <access>
    <method>scratchpad_read_file_tool</method>
    <method>range_read</method>
  </access>
</multimodal_resource>
```

**用户场景示例**:

1. **查看代码截图**:
   ```
   User: "打开 scratchpad://sess_123/debug/screenshot.png"
   URI 解析 -> 读取文件 (24KB PNG)  
   -> Returns BlobResourceContents with base64 encoded PNG
   -> Model/Client decodes base64 to display image
   ```

2. **分析大相册**:
   ```
   User: "列出 photos/ 目录里的所有图片"
   list_resources -> 返回目录列表 (JSON text resource)
   User: "查看第5张图片"
   -> Large image (5MB) detected
   -> If client supports images: Returns ImageResourceContents with 128x128 thumbnail
   -> If not: Returns TextResourceContents with XML description + URI
   -> Model/Client handles accordingly
   ```

3. **查看 PDF 报告** (Client 不支持多模态):
   ```
   User: "读取 report.pdf"
   Client capability detected: multimodal=False
   -> Returns TextResourceContents with XML containing:
      - Embedded URI: scratchpad://sess_123/docs/report.pdf
      - Metadata: size, path, mime_type
      - Instructions: "Use scratchpad_read_file tool..."
   ```

**Implementation Notes**:
- **Client 能力检测**: 在 MCP 初始化时检测 `experimental.multimodal` 或类似字段
- **Image 资源**: 图片使用 `ImageResourceContents` (或具体图片类型) 返回 base64 `data`
- **URI 嵌入**: 对于不支持多模态的 client，URI 必须嵌入 XML/text 内容（OpenAI 格式无 URI 字段）
- **FastMCP Integration**: FastMCP 自动处理 bytes → base64 转换
- **Image Processing**: Pillow 用于缩略图生成 (optional dependency)
- **Size Limits**:
  - < 512KB: Full image inline (如果 client 支持)
  - 512KB - client max: Thumbnail preview
  - > client max 或不支持多模态: XML description only

**重要区分**:

| 层级 | 返回类型 | 用途 | URI 位置 |
|------|---------|------|---------|
| **MCP Resources** | `ImageResourceContents` | 支持的 client 接收图片 | Implicit from resource registration |
| **MCP Resources** | `TextResourceContents` | 不支持的 client 接收文本/XML | 嵌入 `<uri>` 标签内 |
| **MCP Tools** | `ToolResult` with XML | Tools 操作结果 | 嵌入 XML `<metadata><uri>` |

**Client Capability Example**:

```python
# Claude Desktop (supports images)
client_caps = {"imageSupport": True}
# -> Returns ImageResourceContents

# OpenAI GPT-4 (no explicit URI in content)
client_caps = {"experimental": {"multimodal": {"enabled": False}}}
# -> Returns TextResourceContents with embedded URI in XML
```

#### 4. Resource 列表和订阅

```python
# resources/listing.py
from typing import AsyncIterator
import asyncio

class ResourceListingManager:
    """Manage resource listing and change notifications"""
    
    def __init__(self, fs_manager: SessionFileSystemManager):
        self.fs_manager = fs_manager
        self._subscriptions: dict[str, set[str]] = {}  # uri -> session_ids
    
    async def list_resources(
        self,
        session_id: str | None = None,
        cursor: str | None = None
    ) -> dict:
        """List all available resources with pagination"""
        # Implementation for resources/list method
        ...
    
    async def subscribe(self, uri: str, session_id: str):
        """Subscribe to resource changes"""
        if uri not in self._subscriptions:
            self._subscriptions[uri] = set()
        self._subscriptions[uri].add(session_id)
    
    async def unsubscribe(self, uri: str, session_id: str):
        """Unsubscribe from resource changes"""
        if uri in self._subscriptions:
            self._subscriptions[uri].discard(session_id)
    
    async def notify_change(self, uri: str):
        """Notify subscribers of resource change"""
        if uri in self._subscriptions:
            # Send notifications/resources/updated
            for session_id in self._subscriptions[uri]:
                await self._send_notification(session_id, uri)
```

#### 4. Tools 返回格式 (XML Wrapper)

所有 MCP Tools（scratchpad_read_file, scratchpad_write_file, scratchpad_list_files）的返回也应采用 XML wrapper 格式，与 Resources 保持一致，便于下游解析。

```python
# tools/file_tools.py - XML wrapper helpers

def build_tool_read_response(
    session_id: str,
    file_path: str,
    content: str,
    info: dict,
    line_range: tuple[int, int] | None = None
) -> str:
    """
    Build XML-wrapped read_file tool response.
    
    Example:
    <read_result>
      <metadata>
        <session_id>sess_123</session_id>
        <path>src/main.py</path>
        <name>main.py</name>
        <size>2048</size>
        <mime_type>text/x-python</mime_type>
        <version>3</version>
        <permissions>rw</permissions>
        <layer>upper</layer>
      </metadata>
      <content lines="1-50" total_lines="100">
1 | def main():
2 |     print("Hello World")
3 |     
4 | if __name__ == "__main__":
5 |     main()
      </content>
    </read_result>
    """
    from xml.etree.ElementTree import Element, tostring
    
    root = Element("read_result")
    root.set("success", "true")
    
    # Metadata
    meta = Element("metadata")
    Element("session_id").text = session_id
    Element("path").text = file_path
    Element("name").text = info.get("name", file_path.split("/")[-1])
    Element("size").text = str(info.get("size", 0))
    Element("mime_type").text = info.get("type", "text/plain")
    Element("version").text = str(info.get("version", 1))
    Element("permissions").text = "rw" if info.get("_layer") == "upper" else "ro"
    Element("layer").text = info.get("_layer", "unknown")
    root.append(meta)
    
    # Content with line numbers (no CDATA for editability)
    content_elem = Element("content")
    if line_range:
        content_elem.set("lines", f"{line_range[0]}-{line_range[1]}")
    # Content formatted with line numbers: "1 | line content"
    content_elem.text = content_with_line_numbers(content)
    root.append(content_elem)
    
    return tostring(root, encoding="unicode")


def content_with_line_numbers(content: str, start_line: int = 1) -> str:
    """
    Format content with line numbers for edit-friendly XML.
    Format: "{line_num} | {content}\n"
    """
    lines = content.split('\n')
    numbered_lines = [f"{start_line + i} | {line}" for i, line in enumerate(lines)]
    return '\n'.join(numbered_lines)


def build_tool_write_response(
    session_id: str,
    file_path: str,
    operation: str,  # "created" | "updated"
    info: dict
) -> str:
    """
    Build XML-wrapped write_file tool response.
    
    Returns both path (relative) and uri (full scratchpad://) for flexibility.
    
    Example:
    <write_result><metadata><session_id>sess_123</session_id><path>src/main.py</path><uri>scratchpad://sess_123/src/main.py</uri><name>main.py</name></metadata><operation>updated</operation><new_version>4</new_version><new_size>2048</new_size><layer>upper</layer></write_result>
    """
    from xml.etree.ElementTree import Element, tostring
    
    root = Element("write_result")
    root.set("success", "true")
    
    meta = Element("metadata")
    Element("session_id").text = session_id
    Element("path").text = file_path  # Relative path
    Element("uri").text = f"scratchpad://{session_id}/{file_path}"  # Full URI for Resource access
    Element("name").text = info.get("name", file_path.split("/")[-1])
    root.append(meta)
    
    Element("operation").text = operation
    Element("new_version").text = str(info.get("version", 1))
    Element("new_size").text = str(info.get("size", 0))
    Element("layer").text = info.get("_layer", "upper")
    
    return tostring(root, encoding="unicode")


def build_tool_list_response(
    session_id: str,
    directory: str,
    items: list[dict],
    filters_applied: dict | None = None
) -> str:
    """
    Build XML-wrapped list_files tool response.
    
    Each item includes both path (relative) and uri (full scratchpad://).
    
    Example:
    <list_result><metadata><session_id>sess_123</session_id><directory>src/</directory><item_count>3</item_count></metadata><items><file><name>main.py</name><path>src/main.py</path><uri>scratchpad://sess_123/src/main.py</uri><size>2048</size><layer>upper</layer></file><directory><name>utils</name><path>src/utils</path><uri>scratchpad://sess_123/src/utils</uri><item_count>5</item_count><layer>lower_0</layer></directory></items></list_result>
    """
    from xml.etree.ElementTree import Element, tostring
    
    root = Element("list_result")
    root.set("success", "true")
    
    # Metadata
    meta = Element("metadata")
    Element("session_id").text = session_id
    Element("directory").text = directory
    Element("item_count").text = str(len(items))
    
    if filters_applied:
        filters_elem = Element("filters")
        for key, value in filters_applied.items():
            filters_elem.set(key, str(value))
        meta.append(filters_elem)
    
    root.append(meta)
    
    # Items with both path and uri
    items_elem = Element("items")
    for item in items:
        item_type = "directory" if item.get("is_directory") else "file"
        item_elem = Element(item_type)
        
        item_path = item.get("path", "")
        Element("name").text = item.get("name", "")
        Element("path").text = item_path  # Relative path
        Element("uri").text = f"scratchpad://{session_id}/{item_path}"  # Full URI
        Element("size").text = str(item.get("size", 0))
        Element("version").text = str(item.get("version", 1))
        Element("layer").text = item.get("_layer", "unknown")
        Element("modified_at").text = str(item.get("updated_at", ""))
        
        if item_type == "directory":
            Element("item_count").text = str(item.get("item_count", 0))
        
        items_elem.append(item_elem)
    
    root.append(items_elem)
    return tostring(root, encoding="unicode")
```

**Tools 返回示例**:

**read_file 响应**:
```xml
<read_result success="true"><metadata><session_id>sess_123</session_id><path>src/main.py</path><name>main.py</name><size>2048</size><mime_type>text/x-python</mime_type><version>3</version><permissions>rw</permissions><layer>upper</layer></metadata><content lines="1-5">1 | def main():
2 |     print("Hello World")
3 |
4 | if __name__ == "__main__":
5 |     main()</content></read_result>
```

**write_file 响应** (同时返回 path 和 uri):
```xml
<write_result success="true"><metadata><session_id>sess_123</session_id><path>src/main.py</path><uri>scratchpad://sess_123/src/main.py</uri><name>main.py</name></metadata><operation>created</operation><new_version>1</new_version><new_size>2048</new_size><layer>upper</layer></write_result>
```

**list_files 响应** (每个 item 包含 path 和 uri):
```xml
<list_result success="true"><metadata><session_id>sess_123</session_id><directory>src/</directory><item_count>3</item_count></metadata><items><file><name>main.py</name><path>src/main.py</path><uri>scratchpad://sess_123/src/main.py</uri><size>2048</size><version>4</version><layer>upper</layer></file><file><name>__init__.py</name><path>src/__init__.py</path><uri>scratchpad://sess_123/src/__init__.py</uri><size>0</size><version>1</version><layer>lower_0</layer></file><directory><name>utils</name><path>src/utils</path><uri>scratchpad://sess_123/src/utils</uri><item_count>5</item_count><layer>lower_1</layer></directory></items></list_result>
```

**字段说明**:
| 字段 | 示例 | 说明 |
|------|------|------|
| `path` | `src/main.py` | 相对于 session 根的路径，简洁 |
| `uri` | `scratchpad://sess_123/src/main.py` | 完整 URI，可直接用于 Resource 访问 |
| `session_id` | `sess_123` | 所属 session，用于隔离 |

**设计原则**:
1. **一致性**: Tools 和 Resources 都使用 XML wrapper，下游 parser 可复用
2. **完整性**: 每个响应包含 session_id、path、layer、version 等完整元数据
3. **编辑友好**: XML 不使用 CDATA，文本内容使用行号格式（如 "5 | line content"）
4. **扁平化**: XML 无缩进和空格，减小传输大小，简化解析

**错误响应格式**:
```xml
<error_response><error><code>RESOURCE_NOT_FOUND</code><message>File not found: src/main.py</message><details><session_id>sess_123</session_id><path>src/main.py</path><timestamp>2026-03-19T10:30:00Z</timestamp></details><suggestions><suggestion>Check if the file exists using list_files tool</suggestion><suggestion>Verify session_id is correct</suggestion></suggestions></error></error_response>
```

**错误码表**:

| 错误码 | HTTP 状态 | 说明 |
|--------|-----------|------|
| `RESOURCE_NOT_FOUND` | 404 | 文件或目录不存在 |
| `PERMISSION_DENIED` | 403 | 对只读层执行写操作 |
| `INVALID_PATH` | 400 | 路径包含非法字符或路径遍历尝试 |
| `SESSION_NOT_FOUND` | 404 | Session ID 不存在或已过期 |
| `FILE_TOO_LARGE` | 413 | 文件超过大小限制 |
| `BACKEND_ERROR` | 502 | 底层存储后端（S3等）错误 |
| `CACHE_ERROR` | 503 | 缓存系统异常 |
| `CONCURRENT_MODIFICATION` | 409 | 文件被并发修改 |

**Multi-modal 文件设计原则**:
1. **透明存储**: 图片、PDF 与普通文件统一处理，路径无特殊标记
2. **自动识别**: 通过扩展名/MIME type 自动检测文件类型
3. **渐进加载**: 小文件 inline，大文件缩略图/分段
4. **Base64 安全传输**: 避免 binary 在 XML 中的编码问题

### 配置示例

#### YAML 配置文件

```yaml
# config/scratchpad.yaml

overlay:
  # Session workspace configuration
  workspace:
    type: memory  # memory or file
    max_size: 100MB  # For memory type
    
  # Mount points (ordered by priority, higher first)
  mounts:
    - name: workspace
      source: memory://
      mount_point: /workspace
      mode: rw
      priority: 100
      
    - name: templates
      source: file:///opt/mcp/templates
      mount_point: /templates
      mode: ro
      priority: 50
      
    - name: shared_kb
      source: s3://mcp-knowledge-base/shared
      mount_point: /kb
      mode: ro
      priority: 40
      options:
        endpoint_url: https://s3.amazonaws.com
        aws_access_key_id: ${AWS_ACCESS_KEY_ID}
        aws_secret_access_key: ${AWS_SECRET_ACCESS_KEY}
        
    - name: data_archive
      source: s3://mcp-data-archive/
      mount_point: /archive
      mode: ro
      priority: 30
      options:
        endpoint_url: https://s3.amazonaws.com
        
  # Caching configuration
  cache:
    enabled: true
    type: memory  # memory, file, or null
    max_size: 500MB
    ttl: 3600  # seconds

  # Multi-modal files configuration
  multimodal:
    enabled: true
    
    # Image processing
    image:
      enabled: true
      max_inline_size: 524288        # 512KB - max size for inline base64
      preview_size: 102400           # 100KB - size for truncated preview
      thumbnail:
        enabled: true
        max_size: 128                # 128x128 px thumbnail
        format: "PNG"                # Thumbnail output format
      supported_formats:
        - "image/png"
        - "image/jpeg"
        - "image/gif"
        - "image/webp"
        - "image/svg+xml"
    
    # Binary files (PDF, audio, video)
    binary:
      max_inline_size: 262144        # 256KB for PDFs etc.
      preview_bytes: 1024            # First 1KB as preview
    
    # Client capability defaults (fallback if client doesn't advertise)
    client_capabilities:
      detect_from_client: true        # Auto-detect from MCP initialize
      default:
        supports_multimodal: false    # Conservative default
        supports_images: false
        max_image_size: 524288        # 512KB default limit
      # Client-specific overrides (by client name/type)
      overrides:
        claude-desktop:
          supports_multimodal: true
          supports_images: true
          max_image_size: 5242880     # 5MB for Claude
        openai-gpt4:
          supports_multimodal: false  # Use text fallback

# MCP Resources configuration
resources:
  enabled: true
  max_list_page_size: 100
  notification_enabled: true
```

#### 配置加载

```python
# config/loader.py
import yaml
from pathlib import Path
from functools import lru_cache

@lru_cache()
def load_overlay_config(config_path: str | None = None) -> OverlayConfig:
    """Load overlay configuration from YAML file"""
    if config_path is None:
        # Search standard locations
        for path in [
            Path("config/scratchpad.yaml"),
            Path("/etc/mcp-scratchpad/config.yaml"),
            Path.home() / ".config/mcp-scratchpad/config.yaml",
        ]:
            if path.exists():
                config_path = str(path)
                break
    
    if config_path is None:
        return OverlayConfig()  # Default config
    
    with open(config_path) as f:
        data = yaml.safe_load(f)
    
    return OverlayConfig(**data.get("overlay", {}))
```

---

## Implementation Plan

### Phase 1: Foundation (Week 1)

**Goals**: 建立基础架构，实现核心 fsspec 集成，包含缓存机制

| Task | Owner | Duration | Deliverable | Related DEC |
|------|-------|----------|-------------|-------------|
| Setup fsspec dependencies | TBD | 0.5 day | Updated pyproject.toml | - |
| Implement MountConfig models | TBD | 0.5 day | Config dataclasses | DEC-6 |
| Implement directory index cache | TBD | 1 day | CachedOverlayFileSystem | DEC-8 |
| Create SessionFileSystemManager | TBD | 1.5 days | Basic session FS management | - |
| Implement shared mount support | TBD | 1 day | COW shared layer | DEC-4 |
| Add tests for manager + cache | TBD | 1 day | Unit test coverage >80% | - |

**Milestone**: Session isolation + shared mounts + directory cache working

### Phase 2: Overlay FS Core (Week 2)

**Goals**: 实现多层 overlay 文件系统核心

| Task | Owner | Duration | Deliverable |
|------|-------|----------|-------------|
| Implement OverlayFileSystem | TBD | 2.5 days | Full overlay with COW |
| Add mount integration | TBD | 0.5 day | Config-driven mounts |
| Support Local + S3 backends | TBD | 1 day | Backend abstraction |
| Comprehensive test suite | TBD | 1 day | Integration tests |

**Milestone**: Multi-layer overlay working with config-driven mounts

### Phase 2b: Extended Overlay & Performance (Week 3)

**Goals**: 完成 COW 高级特性，性能优化

| Task | Owner | Duration | Deliverable | Related DEC |
|------|-------|----------|-------------|-------------|
| Complete COW implementation | TBD | 1.5 days | Full COW with edge cases | - |
| Whiteout handling & testing | TBD | 0.5 day | Complete lifecycle tests | - |
| Cache performance tuning | TBD | 1 day | TTL + hybrid mode | DEC-8 |
| Large file streaming | TBD | 1 day | >100MB file support | DEC-5 |
| Stress testing | TBD | 1 day | 100+ concurrent sessions | - |

**Milestone**: Production-grade overlay FS with performance validation

### Phase 3: MCP Resources (Week 4)

**Goals**: 完整集成 MCP Resources，含大文件处理

| Task | Owner | Duration | Deliverable | Related DEC |
|------|-------|----------|-------------|-------------|
| Implement scratchpad:// resources | TBD | 1.5 days | Resource handlers | - |
| Add resource listing | TBD | 0.5 day | Pagination support | - |
| Implement large file partial read | TBD | 1 day | Metadata + preview response | DEC-5 |
| Implement subscription | TBD | 1 day | Change notifications | - |
| Resource tests (incl. large files) | TBD | 1 day | E2E coverage | - |

**Milestone**: Files accessible via MCP Resources protocol, large files handled

### Phase 4: Integration & Migration (Week 4-5)

**Goals**: 与现有系统集成，安全审查

| Task | Owner | Duration | Deliverable |
|------|-------|----------|-------------|
| Integrate with existing tools | TBD | 1.5 days | Backward compatible |
| Update existing storage layer | TBD | 0.5 day | Migrate to new FS |
| Security review & penetration test | TBD | 1.5 days | Security checklist passed |
| Write security documentation | TBD | 0.5 day | Security guide added |

**Milestone**: Security-validated, production-ready integration

### Phase 5: Release Preparation (Week 5)

**Goals**: 最终性能优化、文档、发布准备

| Task | Owner | Duration | Deliverable |
|------|-------|----------|-------------|
| Performance benchmarking | TBD | 1 day | Baseline metrics, bottlenecks identified |
| Documentation review | TBD | 0.5 day | API docs, migration guide complete |
| Breaking change communication | TBD | 0.5 day | CHANGELOG, announcement drafted |
| Production deployment prep | TBD | 0.5 day | Monitoring, alerting configured |
| Buffer for critical fixes | TBD | 1.5 days | Contingency time |

**Milestone**: Ready for production deployment

### Dependencies Timeline (Updated - 5 Week Plan)

```
Week 1 (Foundation + Cache)
  │
  ├─ Setup fsspec dependencies
  ├─ MountConfig models [DEC-6]
  ├─ Directory index cache [DEC-8]
  ├─ SessionFileSystemManager
  └─ Shared mounts support [DEC-4]
  
Week 2 (Overlay FS Core)
  │
  ├─ OverlayFileSystem core
  ├─ COW implementation (MVP)
  ├─ Local + S3 backends
  └─ Basic integration tests
  
Week 3 (Extended Overlay + Performance)
  │
  ├─ Complete COW with edge cases
  ├─ Whiteout lifecycle [CRITICAL]
  ├─ Cache performance tuning [DEC-8]
  ├─ Large file streaming [DEC-5]
  └─ Stress testing (100+ sessions)
  
Week 4 (MCP Resources + Security)
  │
  ├─ scratchpad:// resources
  ├─ Multimodal support [DEC-9]
  ├─ Resource subscription
  ├─ Security review [NEW]
  └─ Security documentation [NEW]
  
Week 5 (Integration + Release)
  │
  ├─ Existing tool migration
  ├─ Breaking change docs [DEC-7]
  ├─ Performance benchmarking
  └─ Production release prep
```

### Rollback Strategy

1. **Feature flag**: 使用环境变量控制新功能启用
2. **Dual write**: 新旧存储同时运行，逐步切换
3. **Backward compatible**: 现有 API 行为保持不变
4. **Data safety**: 任何写入操作前进行备份验证

---

## Configuration Schema

### Full Configuration Reference

```yaml
# schema/scratchpad.yaml

version: "1.0"

overlay:
  # Workspace configuration for session storage
  workspace:
    type: memory           # Options: memory, file
    
    # For memory type
    memory:
      max_size: 100MB      # Per-session memory limit
      
    # For file type
    file:
      base_dir: "out/workspaces"
      max_size: 1GB
      
  # Mount points - ordered by priority (higher = first)
  mounts:
    - name: string                    # Unique mount identifier
      source: string                  # URI (s3://, file://, memory://)
      mount_point: string             # Mount path (e.g., "/data")
      mode: ro | rw                   # Read-only or read-write
      priority: integer               # Overlay priority (higher = checked first)
      options:                        # Backend-specific options
        # S3 options
        endpoint_url: string?
        aws_access_key_id: string?
        aws_secret_access_key: string?
        region_name: string?
        
        # Local file options
        auto_mkdir: boolean?
        
        # Memory options
        persistent: boolean?
        
  # Caching layer
  cache:
    enabled: true
    type: memory           # memory, file, or null
    
    memory:
      max_size: 500MB
      
    file:
      path: ".cache"
      max_size: 5GB
      
    # Cache policies
    policies:
      default_ttl: 3600    # seconds
      max_entry_size: 10MB
      
# MCP Resources configuration
resources:
  enabled: true
  
  # Resource URI scheme
  scheme: "scratchpad"
  
  # Listing configuration
  listing:
    enabled: true
    default_page_size: 50
    max_page_size: 200
    
  # Subscriptions
  subscriptions:
    enabled: true
    max_per_session: 100
    
  # Size limits (in bytes)
  limits:
    max_inline_text: 1048576      # 1MB
    max_base64_binary: 524288     # 512KB
    
# Session management
session:
  # Cleanup configuration
  cleanup:
    enabled: true
    timeout_seconds: 3600         # Cleanup after 1 hour inactive
    
  # Limits
  limits:
    max_concurrent: 100
    max_files_per_session: 10000
    max_total_size_per_session: 5368709120  # 5GB
    
# Logging
logging:
  level: INFO
  format: text                   # text or json
  
  # FS operation logging
  operations:
    enabled: true
    log_reads: false            # Can be verbose
    log_writes: true
```

### Environment Variable Mapping

| Environment Variable | Config Path | Description |
|---------------------|-------------|-------------|
| `MCP_SCRATCHPAD_CONFIG` | - | Path to YAML config file |
| `MCP_SCRATCHPAD_WORKSPACE_TYPE` | `overlay.workspace.type` | Workspace storage type |
| `MCP_SCRATCHPAD_WORKSPACE_DIR` | `overlay.workspace.file.base_dir` | Base directory for file workspace |
| `MCP_SCRATCHPAD_S3_ENDPOINT` | - | Default S3 endpoint |
| `MCP_SCRATCHPAD_RESOURCES_ENABLED` | `resources.enabled` | Enable MCP Resources |
| `MCP_SCRATCHPAD_CACHE_TYPE` | `overlay.cache.type` | Cache type |
| `MCP_SCRATCHPAD_LOG_LEVEL` | `logging.level` | Log level |

### Configuration Validation

配置加载时执行严格的校验，确保在启动阶段发现问题：

```python
# config/validator.py
from pydantic import BaseModel, validator, root_validator
from typing import List
import re

class ConfigValidationError(Exception):
    """配置校验错误"""
    pass

class MountConfig(BaseModel):
    """带校验的 Mount 配置"""
    name: str
    source: str
    mount_point: str
    mode: str = "ro"
    priority: int = 0
    
    @validator('name')
    def validate_name(cls, v):
        """Mount 名称校验"""
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', v):
            raise ValueError(
                f"Mount name '{v}' invalid. "
                "Must start with letter, contain only alphanumeric, underscore, hyphen"
            )
        if len(v) > 64:
            raise ValueError(f"Mount name '{v}' too long (max 64 chars)")
        return v
    
    @validator('source')
    def validate_source(cls, v):
        """Source URI 格式校验"""
        allowed_schemes = ['s3://', 'file://', 'memory://', 'http://', 'https://']
        if not any(v.startswith(scheme) for scheme in allowed_schemes):
            raise ValueError(
                f"Source '{v}' has invalid scheme. "
                f"Allowed: {', '.join(allowed_schemes)}"
            )
        return v
    
    @validator('mount_point')
    def validate_mount_point(cls, v):
        """Mount point 路径校验"""
        if not v.startswith('/'):
            raise ValueError(f"Mount point '{v}' must start with '/'")
        # 防止路径遍历
        normalized = os.path.normpath(v)
        if '..' in normalized or normalized.startswith('..'):
            raise ValueError(f"Mount point '{v}' contains path traversal")
        return normalized
    
    @validator('mode')
    def validate_mode(cls, v):
        """Mode 值校验"""
        if v not in ('ro', 'rw'):
            raise ValueError(f"Mode '{v}' invalid. Must be 'ro' or 'rw'")
        return v

class OverlayConfig(BaseModel):
    """Overlay 配置根对象"""
    mounts: List[MountConfig]
    
    @root_validator
    def validate_mounts(cls, values):
        """跨 mount 校验"""
        mounts = values.get('mounts', [])
        
        # 检查重复的 mount 名称
        names = [m.name for m in mounts]
        if len(names) != len(set(names)):
            duplicates = [n for n in set(names) if names.count(n) > 1]
            raise ValueError(f"Duplicate mount names: {duplicates}")
        
        # 检查 mount point 冲突
        mount_points = [m.mount_point for m in mounts]
        for i, mp1 in enumerate(mount_points):
            for mp2 in mount_points[i+1:]:
                # 检查是否是父子关系
                if mp1.startswith(mp2) or mp2.startswith(mp1):
                    raise ValueError(
                        f"Mount point conflict: '{mp1}' and '{mp2}' "
                        "(one is prefix of another)"
                    )
        
        # 检查是否有 rw mount
        rw_mounts = [m for m in mounts if m.mode == 'rw']
        if len(rw_mounts) > 1:
            raise ValueError(
                f"Multiple RW mounts not supported. Found: "
                f"{[m.name for m in rw_mounts]}"
            )
        
        return values

# 配置加载入口
def load_and_validate_config(path: str) -> OverlayConfig:
    """
    加载并校验配置文件。
    
    异常时抛出 ConfigValidationError，包含所有校验错误。
    """
    try:
        with open(path) as f:
            raw_data = yaml.safe_load(f)
        
        config = OverlayConfig(**raw_data.get('overlay', {}))
        return config
        
    except ValidationError as e:
        # 收集所有错误
        errors = []
        for error in e.errors():
            loc = '.'.join(str(x) for x in error['loc'])
            errors.append(f"  [{loc}] {error['msg']}")
        
        raise ConfigValidationError(
            f"Configuration validation failed:\n" + "\n".join(errors)
        )
```

**校验规则汇总**:

| 校验项 | 规则 | 错误级别 |
|--------|------|----------|
| Mount 名称格式 | `^[a-zA-Z][a-zA-Z0-9_-]*$`, max 64 chars | Error |
| Source URI Scheme | 必须匹配 `s3://`, `file://`, `memory://` 等 | Error |
| Mount Point 路径 | 必须以 `/` 开头，无路径遍历 | Error |
| Mode 值 | 必须是 `ro` 或 `rw` | Error |
| 重复 Mount 名称 | 名称必须唯一 | Error |
| Mount Point 冲突 | 不能有前缀重叠 | Error |
| 多个 RW Mount | 仅支持一个 RW mount | Error |
| Priority 值范围 | 建议 0-1000 | Warning |

**启动时校验流程**:

```
1. 加载 YAML 文件
2. 解析为基本数据结构
3. Pydantic 模型校验
   ├─ 字段类型检查
   ├─ 字段格式检查
   └─ 跨字段交叉校验
4. 挂载点可访问性检查
   ├─ 尝试连接 S3（验证凭证）
   ├─ 检查本地目录是否存在
   └─ 测试内存 FS 可用性
5. 加载成功 / 报错退出
```

---

## Open Questions

### Technical Questions (已决策)

1. ✅ **已决策: DEC-4** - 支持跨 session 的 COW 共享机制
2. ✅ **已决策: DEC-5** - 大文件返回部分 + 元数据
3. ✅ **已决策: DEC-8** - Phase 1 实现目录索引缓存
4. ✅ **已决策: DEC-6** - 使用环境变量引用管理密钥

### 业务问题 (已决策)

1. ✅ **已决策: DEC-7** - 全新开始，不兼容旧格式（breaking change）

2. ✅ **已决策: DEC-6** - `fsspec-union` Apache-2.0 许可可接受，直接使用
   - **分析**: Apache-2.0 与 MIT/其他许可兼容
   - **结论**: 可直接使用作为依赖

### 未解决问题

1. **Q**: 是否需要支持网络文件系统 (NFS) 后端？
   - **当前**: 未纳入 MVP，后续 RFC 再议
   
2. **Q**: 文件级权限控制粒度？
   - **当前**: 仅支持 mount-level 的 ro/rw
   - **待评估**: 是否需要 file-level ACL

3. **Q**: 监控和可观测性需求？
   - **待补充**: Metrics (文件操作数、延迟)、Tracing 需求

---

## Decision Record

### Decision 1: 选用 Hybrid Approach (Option 3)

**Status**: PROPOSED  
**Date**: 2026-03-19  

**Context**:
需要选择 overlay 文件系统的实现方式，在开发效率、系统能力和长期维护之间取得平衡。

**Decision**:
采用 Option 3 - Hybrid Approach with Custom Session Layer

**Rationale**:
1. 与现有 session-based 架构完全契合
2. 提供足够的定制空间应对 MCP 特定需求
3. 渐进式演进，降低集成风险
4. fsspec 生态的兼容性

**Consequences**:
- ✅ 平衡灵活性和开发效率
- ✅ 保持与现有代码的兼容性
- ⚠️ 需要维护中等复杂度的自定义层
- ⚠️ 相比纯 fsspec 方案，需要更多设计工作

**Alternatives Considered**:
- Option 1: 完全自定义实现（开发成本过高）
- Option 2: 纯 fsspec-union（定制空间不足）

---

### Decision 2: Resource URI Scheme 使用 `scratchpad://`

**Status**: PROPOSED | **UPDATED**  
**Date**: 2026-03-19  

**Context**:
需要定义 MCP Resources 的 URI scheme，使客户端能够一致地访问文件。

**Decision**:
使用自定义 scheme: `scratchpad://{session_id}/{path}`

**格式**:
```
scratchpad://<session_id>/<path>
```

**示例**:
- `scratchpad://sess_abc123/project/main.py`
- `scratchpad://sess_abc123/data/results.csv`
- `scratchpad://sess_abc123/` (根目录)

**Rationale**:
1. 明确的命名空间避免与其他 URI scheme 冲突
2. 包含 session_id 确保资源的全局唯一性
3. 与 `file://` 等标准 scheme 区分，表达特殊语义
4. **不暴露 mount 结构**: 下游无需了解文件存储在哪个底层 backend
5. MCP 规范允许自定义 URI scheme

**Implementation Note**:
- Path 是 overlay 视图中的统一路径
- mount 的组合在服务端处理，对下游透明
- 例如 `/templates/readme.md` 可能来自 S3 mount，但下游只需知道路径

**Consequences**:
- ✅ 清晰的资源标识
- ✅ 支持多 session 并行
- ✅ 后端存储对下游透明，简化客户端逻辑
- ⚠️ 需要 session 级别的路径解析逻辑

---

### Decision 3: 先实现 MemoryFileSystem 作为 Upper Layer

**Status**: PROPOSED  
**Date**: 2026-03-19  

**Context**:
Session 的可写层（Upper Layer）可以使用磁盘或内存存储。

**Decision**:
MVP 使用 MemoryFileSystem，后续添加本地磁盘选项

**Rationale**:
1. MemoryFileSystem 性能最优，适合临时编辑场景
2. 自动的 session 隔离（每个 session 不同内存空间）
3. 简化 cleanup 逻辑（进程退出自动清理）
4. 符合 ephemeral workspace 的语义

**Consequences**:
- ✅ 高性能读写
- ✅ 简化资源管理
- ⚠️ 内存限制可能影响大文件处理
- ⚠️ 进程重启数据丢失（符合预期行为）

**Future Consideration**:
- Phase 2 添加 `DiskFileSystem` 选项
- 配置 `workspace.type` 选择存储后端

---

### Decision 4: 支持跨 Session 的写时复制共享 (COW Shared Data)

**Status**: APPROVED  
**Date**: 2026-03-19  

**Context**:
需要决定 session 之间是否允许共享数据，以及如何实现。

**Decision**:
支持跨 session 的写时复制（COW）共享机制

**Rationale**:
1. 多个 session 可能需要访问相同的基础数据（如知识库、模板）
2. COW 模式保证数据隔离的同时节省存储
3. 每个 session 有自己的可写层，写入不影响共享数据
4. 类似 Docker 镜像层共享模型

**Implementation**:
- 提供全局共享挂载配置（`shared_mounts`）
- 共享层作为所有 session 的 lowerdir
- 每个 session 的 upperdir 为独立 workspace
- 写入触发 copy-up 到 session 专属层

**Consequences**:
- ✅ 多个 session 共享只读数据，节省存储
- ✅ 写入隔离，数据安全性有保障
- ⚠️ 实现复杂度增加，需要管理共享层生命周期
- ⚠️ 需要额外的并发控制机制

---

### Decision 5: 大文件资源返回部分内容和元数据

**Status**: APPROVED  
**Date**: 2026-03-19  

**Context**:
当 MCP Resources 访问超过 100MB 的大文件时的处理策略。

**Decision**:
采用选项 B：返回前 100KB 内容摘要 + 完整元数据

**Implementation**:
```python
# Resource 响应格式
{
    "metadata": {
        "size": 524288000,  # 500MB
        "mimeType": "application/octet-stream",
        "lastModified": "2026-03-19T10:00:00Z"
    },
    "summary": {
        "preview": "# First 100KB content\n...",
        "previewSize": 102400,
        "totalSize": 524288000
    },
    "accessMethods": [
        {
            "type": "range_read",
            "description": "使用 scratchpad_read_file tool 分段读取"
        },
        {
            "type": "full_download",
            "description": "下载完整文件"
        }
    ]
}
```

**Consequences**:
- ✅ 不会阻塞客户端加载大文件
- ✅ 客户端可选择合适的访问方式
- ⚠️ 需要客户端理解多层响应格式
- ⚠️ 需要扩展 MCP Resources 协议或自定义格式

---

### Decision 6: S3 等密钥通过环境变量引用管理

**Status**: APPROVED  
**Date**: 2026-03-19  

**Context**:
需要选择云存储后端（S3 等）鉴权密钥的安全管理方式。

**Decision**:
采用选项 A：配置文件中使用环境变量引用（已实现基础）

**Implementation**:
```yaml
# config/scratchpad.yaml
mounts:
  - name: s3_data
    source: s3://bucket/data
    options:
      aws_access_key_id: ${AWS_ACCESS_KEY_ID}
      aws_secret_access_key: ${AWS_SECRET_ACCESS_KEY}
      endpoint_url: ${S3_ENDPOINT_URL:https://s3.amazonaws.com}
```

**Rationale**:
1. 简单直观，与现有配置体系一致
2. 12-Factor App 原则推荐
3. 容器化环境、CI/CD 原生支持环境变量
4. 降低实现复杂度和外部依赖

**Security Best Practices**:
- 生产环境使用 secret injection（如 Kubernetes secrets, GitHub secrets）
- 配置文件中仅出现引用，不包含真实密钥
- 日志中过滤敏感信息
- 考虑支持 AWS IAM Role/Pod Identity（无需静态密钥）

**Consequences**:
- ✅ 实现简单，易于部署
- ✅ 兼容现有运维流程
- ⚠️ 环境变量中密钥仍可能被泄露（依赖进程安全）
- ⚠️ 不支持运行时动态轮换（需要重启）

**Future Consideration**:
- 后续可添加选项 B 支持：运行时通过 `set_credentials` tool 动态传入
- 支持 AWS STS AssumeRole 等临时凭证模式

---

### Decision 7: 全新开始，不兼容现有 .metadata.json 格式

**Status**: APPROVED  
**Date**: 2026-03-19  

**Context**:
是否需要向后兼容现有的 `.metadata.json` 文件格式。

**Decision**:
采用选项 C：全新开始（breaking change），不兼容旧格式

**Rationale**:
1. 新架构（fsspec overlay）与旧架构设计思路根本不同
2. 迁移需要复杂的数据转换逻辑
3. mcp-scratchpad 通常是 ephemeral workspace，数据生命周期短
4. 保持代码和配置简洁

**Migration Path**:
- 提供手动导出/导入脚本（非自动）
- 文档说明 breaking change
- 在 CHANGELOG 中明确标注
- 如需保留数据，用户可手动 copy 文件（不包含元数据）

**Consequences**:
- ✅ 实现简洁，无历史包袱
- ✅ 避免复杂迁移逻辑
- ⚠️ Breaking change，需要用户知情
- ⚠️ 旧 session 数据无法在新版本中读取

---

### Decision 8: 在 Phase 1 中实现目录索引缓存

**Status**: APPROVED  
**Date**: 2026-03-19  

**Context**:
Union FS 在大目录时使用线性搜索可能性能退化。

**Decision**:
采用方案 A：在 Phase 1 就实现目录索引缓存机制

**Implementation**:
```python
class CachedOverlayFileSystem(OverlayFileSystem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dir_cache: dict[str, list[dict]] = {}  # path -> merged listing
        self._cache_ttl = kwargs.get('cache_ttl', 5)  # seconds
        self._cache_timestamps: dict[str, float] = {}
    
    def ls(self, path: str, detail: bool = True, **kwargs):
        # Check cache first
        now = time.time()
        if path in self._dir_cache:
            if now - self._cache_timestamps.get(path, 0) < self._cache_ttl:
                return self._dir_cache[path]
        
        # Fresh listing from all layers
        result = self._merge_listings(path, detail)
        self._dir_cache[path] = result
        self._cache_timestamps[path] = now
        return result
    
    def invalidate_cache(self, path: str | None = None):
        """Invalidate cache on write operations"""
        if path is None:
            self._dir_cache.clear()
        else:
            # Invalidate path and its parents
            for cached_path in list(self._dir_cache.keys()):
                if cached_path.startswith(path) or path.startswith(cached_path):
                    del self._dir_cache[cached_path]
```

**Rationale**:
1. 树形目录结构是常见使用模式，性能问题会早期暴露
2. 线性遍历在并发/深层目录下退化明显
3. 缓存机制可读性好，维护成本可控
4. 避免后期重构带来回归风险

**Trade-offs**:
- ✅ 提前规避性能问题
- ❌ 增加初期开发成本和复杂度
- ⚠️ 需要处理缓存一致性问题

**缓存失效策略**:

```python
class CacheInvalidationStrategy:
    """
    目录索引缓存失效策略实现。
    
    支持三种失效模式：TTL、事件驱动、混合模式
    """
    
    def __init__(
        self,
        mode: str = "hybrid",  # "ttl" | "event" | "hybrid"
        default_ttl: int = 60,  # 默认 60 秒 TTL
        memory_limit_mb: int = 100,  # 缓存内存限制
    ):
        self.mode = mode
        self.default_ttl = default_ttl
        self.memory_limit = memory_limit_mb * 1024 * 1024
        
        # 缓存数据结构
        self._cache: dict[str, CacheEntry] = {}
        self._access_times: dict[str, float] = {}
    
    # ─────────────────────────────────────────────────────────────
    # 1. TTL 模式 (Time-To-Live)
    # ─────────────────────────────────────────────────────────────
    
    def get_with_ttl(self, path: str) -> list | None:
        """
        TTL 模式：检查缓存，过期则返回 None。
        
        适用场景：
        - 下层数据变化不频繁
        - 可容忍短暂的数据不一致
        - 简单实现，无外部依赖
        """
        if path not in self._cache:
            return None
        
        entry = self._cache[path]
        age = time.time() - entry.timestamp
        
        if age > entry.ttl:
            # TTL 过期，清理缓存
            del self._cache[path]
            return None
        
        return entry.data
    
    def set_with_ttl(
        self,
        path: str,
        data: list,
        ttl: int | None = None
    ):
        """设置 TTL 缓存"""
        self._check_memory_limit()
        
        self._cache[path] = CacheEntry(
            data=data,
            timestamp=time.time(),
            ttl=ttl or self.default_ttl
        )
    
    # ─────────────────────────────────────────────────────────────
    # 2. 事件驱动模式 (Event-Based)
    # ─────────────────────────────────────────────────────────────
    
    def invalidate_on_event(
        self,
        event_type: str,  # "write" | "delete" | "mkdir" | "rmdir"
        path: str,
        session_id: str
    ):
        """
        事件驱动模式：操作发生时立即失效相关缓存。
        
        适用场景：
        - 需要强一致性
        - 写操作相对读操作较少
        - 延迟敏感（不能接受 TTL 等待）
        """
        paths_to_invalidate = self._get_affected_paths(event_type, path)
        
        for p in paths_to_invalidate:
            self._invalidate_path(p)
            logger.debug(f"Cache invalidated due to {event_type}: {p}")
    
    def _get_affected_paths(
        self,
        event_type: str,
        path: str
    ) -> list[str]:
        """
        确定受影响的缓存路径。
        
        规则：
        - 写文件：失效该文件所在目录及所有祖先目录
        - 删除文件：同上
        - 创建目录：失效父目录
        - 删除目录：失效该目录、父目录及所有祖先
        """
        affected = []
        
        # 当前目录
        parent = os.path.dirname(path)
        affected.append(parent)
        
        # 所有祖先目录（向上遍历）
        while parent and parent != "/":
            parent = os.path.dirname(parent)
            if parent:
                affected.append(parent)
        
        # 如果是目录操作，包含自身
        if event_type in ("mkdir", "rmdir"):
            affected.append(path)
        
        return affected
    
    # ─────────────────────────────────────────────────────────────
    # 3. 混合模式 (Hybrid) - 推荐
    # ─────────────────────────────────────────────────────────────
    
    def get_hybrid(self, path: str, force_refresh: bool = False) -> list | None:
        """
        混合模式：TTL 兜底 + 事件驱动优化。
        
        策略：
        1. 写操作立即触发失效（强一致性）
        2. 读操作检查 TTL（性能）
        3. 支持 force_refresh 强制刷新
        4. 后台异步预加载常用目录
        
        适用场景：
        - 大部分 production 场景
        - 平衡一致性和性能
        """
        if force_refresh:
            return None
        
        # 检查是否被事件标记为脏
        if self._is_dirty(path):
            self._invalidate_path(path)
            return None
        
        # 检查 TTL
        return self.get_with_ttl(path)
    
    def mark_dirty(self, path: str):
        """标记路径为脏（由写操作调用）"""
        for cached_path in list(self._cache.keys()):
            if cached_path.startswith(path) or path.startswith(cached_path):
                self._cache[cached_path].dirty = True
    
    def _is_dirty(self, path: str) -> bool:
        """检查路径是否被标记为脏"""
        if path in self._cache:
            return self._cache[path].dirty
        return False
    
    # ─────────────────────────────────────────────────────────────
    # 4. 内存管理与清理
    # ─────────────────────────────────────────────────────────────
    
    def _check_memory_limit(self):
        """检查并清理缓存以保持在内存限制内"""
        current_size = self._estimate_memory_usage()
        
        if current_size > self.memory_limit:
            # LRU 清理：移除最旧的条目
            sorted_paths = sorted(
                self._access_times.items(),
                key=lambda x: x[1]  # 按访问时间排序
            )
            
            # 清理 20% 的条目
            to_remove = int(len(sorted_paths) * 0.2)
            for path, _ in sorted_paths[:to_remove]:
                self._invalidate_path(path)
                logger.debug(f"Cache evicted due to memory limit: {path}")
    
    def _estimate_memory_usage(self) -> int:
        """估算当前缓存内存使用量（字节）"""
        total = 0
        for entry in self._cache.values():
            # 粗略估算：每个条目开销
            total += len(str(entry.data).encode('utf-8'))
        return total
    
    def _invalidate_path(self, path: str):
        """失效指定路径的缓存"""
        self._cache.pop(path, None)
        self._access_times.pop(path, None)
    
    # ─────────────────────────────────────────────────────────────
    # 5. 后台预加载
    # ─────────────────────────────────────────────────────────────
    
    async def background_preload(
        self,
        fs,
        hot_paths: list[str],
        interval: int = 60
    ):
        """
        后台任务：定期预加载热点目录。
        
        避免首次访问时的缓存未命中延迟。
        """
        while True:
            for path in hot_paths:
                try:
                    items = fs.ls(path, detail=True)
                    self.set_with_ttl(path, items, ttl=self.default_ttl * 2)
                    logger.debug(f"Background preloaded: {path}")
                except Exception as e:
                    logger.warning(f"Preload failed for {path}: {e}")
            
            await asyncio.sleep(interval)


@dataclass
class CacheEntry:
    """缓存条目"""
    data: list
    timestamp: float
    ttl: int
    dirty: bool = False
```

**缓存策略选择指南**:

| 策略 | 一致性 | 性能 | 复杂度 | 推荐场景 |
|------|--------|------|--------|----------|
| **TTL Only** | 弱（TTL 期间可能陈旧） | 最高 | 低 | 只读数据、底层极少变化 |
| **Event-Based** | 强 | 中等 | 中等 | 写操作少、一致性要求高 |
| **Hybrid** | 强 | 高 | 中等 | **通用场景，推荐** |

**配置示例**:

```yaml
overlay:
  cache:
    enabled: true
    mode: hybrid  # ttl | event | hybrid
    default_ttl: 60  # seconds
    memory_limit: 100MB
    
    # 热点目录预加载
    preload:
      enabled: true
      paths:
        - "/workspace"
        - "/templates"
      interval: 300  # seconds
    
    # 长时间 TTL 的目录（ rarely change ）
    extended_ttl_paths:
      - pattern: "/kb/**"  # 知识库
        ttl: 3600  # 1 hour
      - pattern: "/archive/**"  # 归档数据
        ttl: 7200  # 2 hours
```

**监控指标**:

```python
# Prometheus metrics
cache_hit_counter = Counter('scratchpad_cache_hits', 'Cache hit count', ['path_pattern'])
cache_miss_counter = Counter('scratchpad_cache_misses', 'Cache miss count', ['path_pattern'])
cache_size_gauge = Gauge('scratchpad_cache_entries', 'Number of cached entries')
cache_memory_gauge = Gauge('scratchpad_cache_memory_bytes', 'Cache memory usage')
cache_invalidation_counter = Counter('scratchpad_cache_invalidations', 'Cache invalidations', ['reason'])
```

---

### Decision 9: Client 能力协商与多模态适配

**Status**: APPROVED  
**Date**: 2026-03-19  

**Context**:
不同 MCP Client 对多模态内容的支持能力不同（Claude Desktop 支持图片，OpenAI 格式无 URI 字段），需要自适应返回格式。

**Decision**:
1. MCP 初始化时检测 client capabilities
2. URI 嵌入 XML/text 内容（因 OpenAI 格式 resource 无 URI 字段）
3. 不支持多模态的 client 返回 text-only 描述
4. Config 支持 client-specific 覆盖

**Implementation**:

```python
# Server capabilities advertisement
SERVER_CAPABILITIES = {
    "resources": {
        "multimodal": {
            "enabled": True,
            "imageFormats": ["image/png", "image/jpeg"],
            "maxImageSize": 10 * 1024 * 1024
        }
    }
}

# Client capability detection
def detect_client_capabilities(client_info: dict) -> ClientCapabilities:
    caps = ClientCapabilities()
    
    # Check experimental fields
    experimental = client_info.get("experimental", {})
    if "multimodal" in experimental:
        caps.supports_images = experimental["multimodal"].get("images", False)
    
    # Client name-based override from config
    client_name = client_info.get("client", {}).get("name", "unknown")
    if client_name in config.client_capabilities.overrides:
        override = config.client_capabilities.overrides[client_name]
        caps.supports_images = override.get("supports_images", caps.supports_images)
    
    return caps

# Resource return logic
async def read_resource(self, session_id: str, path: str):
    if self.capabilities.supports_images and is_image(path):
        # Return ImageResourceContents (no URI field in OpenAI format)
        return ImageResourceContents(
            type="image",
            mimeType="image/png",
            data=base64_image_data
        )
    else:
        # Return TextResourceContents with embedded URI
        xml = f"""
        <file_resource>
            <metadata>
                <uri>scratchpad://{session_id}/{path}</uri>
                <!-- other metadata -->
            </metadata>
        </file_resource>
        """
        return TextResourceContents(type="text", text=xml)
```

**Rationale**:
1. **兼容性**: 支持不同 client 格式（Claude、OpenAI、自定义）
2. **无 breaking change**: 不支持多模态的 client 仍能正常使用（文本 fallback）
3. **URI 不丢失**: 即使 resource content 无 URI 字段，也能从 XML 中提取
4. **可配置**: 允许管理员覆盖 client 的 self-reported 能力

**Client 格式差异**:

| Client | Image Support | URI in Content | MIME Type Field |
|--------|---------------|----------------|-----------------|
| Claude Desktop | ✅ | ✅ | `mimeType` |
| OpenAI GPT-4 | ✅ | ❌ | `type` + implicit |
| Custom Clients | varies | varies | varies |

**Consequences**:
- ✅ 最大化 client 兼容性
- ✅ URI 始终可访问（嵌入 XML）
- ⚠️ 增加了能力检测逻辑的复杂度
- ⚠️ 需要维护 client-specific 配置映射

---

## Security Considerations

本节详细说明系统面临的安全风险及防护措施。

### 1. 路径遍历防护 (Path Traversal)

**风险描述**:
恶意用户通过构造包含 `../` 的路径，试图访问 session 根目录之外的文件。

```
攻击示例:
  request: scratchpad://sess_123/../../../etc/passwd
  预期：只访问 sess_123 目录内的文件
  真实风险：可能访问到 /etc/passwd
```

**防护措施**:

```python
# security/path_validation.py
import os
import re
from pathlib import Path

class PathSecurityValidator:
    """路径安全校验器"""
    
    # 禁止的文件名模式
    DANGEROUS_PATTERNS = [
        r'\.\.',           # 目录遍历
        r'^/',             # 绝对路径（用户输入）
        r'[~\\]',          # 特殊字符（Windows 兼容）
        r'\x00',           # Null 字节
        r'[%$&;|]',        # Shell 特殊字符
    ]
    
    # 危险扩展名
    DANGEROUS_EXTENSIONS = {
        '.exe', '.bat', '.cmd', '.sh', '.bin',
        '.so', '.dll', '.dylib'
    }
    
    @classmethod
    def validate_user_path(
        cls,
        user_input: str,
        session_root: str
    ) -> str:
        """
        校验并规范化用户输入路径。
        
        Args:
            user_input: 用户提供的相对路径
            session_root: session 的绝对根目录
            
        Returns:
            规范化后的绝对路径
            
        Raises:
            PathTraversalError: 检测到路径遍历攻击
            InvalidPathError: 路径格式无效
        """
        # 1. 检查危险模式
        for pattern in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, user_input):
                raise PathTraversalError(
                    f"Path contains dangerous pattern: {pattern}"
                )
        
        # 2. 规范化路径（移除冗余 . 和 ..）
        normalized = os.path.normpath(user_input)
        
        # 3. 确保是相对路径（不以 / 开头）
        if normalized.startswith('/'):
            raise InvalidPathError(
                "Absolute paths not allowed in user input"
            )
        
        # 4. 构建完整路径
        full_path = os.path.join(session_root, normalized)
        
        # 5. 关键检查：确保最终路径在 session_root 下
        real_session_root = os.path.realpath(session_root)
        real_full_path = os.path.realpath(full_path)
        
        if not real_full_path.startswith(real_session_root + os.sep) and \
           real_full_path != real_session_root:
            raise PathTraversalError(
                f"Path escapes session root: {user_input} -> {real_full_path}"
            )
        
        # 6. 检查扩展名
        _, ext = os.path.splitext(full_path)
        if ext.lower() in cls.DANGEROUS_EXTENSIONS:
            logger.warning(f"Access to executable file requested: {full_path}")
            # 不阻止，但记录警告
        
        return real_full_path
    
    @classmethod
    def sanitize_filename(cls, filename: str) -> str:
        """
        清理文件名，移除危险字符。
        
        用于处理用户上传的文件名。
        """
        # 移除控制字符
        sanitized = ''.join(
            c for c in filename 
            if c.isprintable() and c not in '<>:"/\\|?*'
        )
        
        # 防止空文件名
        if not sanitized or sanitized in ('.', '..'):
            raise InvalidPathError(f"Invalid filename: {filename}")
        
        return sanitized


class PathTraversalError(SecurityError):
    """路径遍历攻击检测"""
    pass

class InvalidPathError(SecurityError):
    """无效路径格式"""
    pass

class SecurityError(Exception):
    """安全相关错误基类"""
    pass
```

**防御层级**:

```
User Input
    │
    ▼
[Layer 1: 输入验证] 
  - 正则表达式过滤危险字符
  - 检查 .. 序列
    │
    ▼
[Layer 2: 路径规范化]
  - os.path.normpath() 处理
  - 移除冗余分隔符和 .
    │
    ▼
[Layer 3: 边界检查]
  - os.path.realpath() 解析符号链接
  - 验证最终路径在允许范围内
    │
    ▼
Safe Path
```

### 2. Session 隔离与权限控制

**风险描述**:
- Session A 试图访问 Session B 的文件
- Session 中的恶意代码尝试逃逸到宿主机

**隔离机制**:

```python
# security/session_isolation.py

class SessionIsolationManager:
    """
    Session 级别隔离管理。
    
    确保：
    1. 每个 session 只能访问自己的 upper layer
    2. 共享 lower layers 是只读的
    3. 跨 session 路径访问被严格禁止
    """
    
    def __init__(self):
        self._session_roots: dict[str, str] = {}
        self._access_logs: list[AccessLog] = []
    
    def register_session(self, session_id: str, root_path: str):
        """注册 session 的根目录"""
        self._session_roots[session_id] = os.path.realpath(root_path)
    
    def validate_cross_session_access(
        self,
        source_session: str,
        requested_path: str
    ) -> bool:
        """
        验证跨 session 访问请求。
        
        Returns:
            True if access is allowed (within same session)
            False if access should be denied
        """
        # 解析请求路径中的 session_id（如果是 scratchpad:// URI）
        target_session = self._extract_session_from_path(requested_path)
        
        if target_session and target_session != source_session:
            logger.warning(
                f"Cross-session access blocked: {source_session} tried to access {target_session}"
            )
            self._access_logs.append(AccessLog(
                timestamp=time.time(),
                source=source_session,
                target=target_session,
                action="BLOCKED"
            ))
            return False
        
        return True
    
    def _extract_session_from_path(self, path: str) -> str | None:
        """从路径中提取 session_id"""
        # Handle scratchpad://sess_id/path format
        if path.startswith("scratchpad://"):
            parts = path[13:].split("/", 1)  # Remove prefix
            return parts[0] if parts else None
        return None
```

**Mount 只读保证**:

```python
class ReadOnlyMountEnforcer:
    """强制只读 mount 不可写"""
    
    def __init__(self, overlay_fs: OverlayFileSystem):
        self.fs = overlay_fs
    
    def assert_readonly(self, mount_point: str):
        """
        验证 mount point 是否真的只读。
        
        在 mount 配置阶段调用，防止配置错误导致安全漏洞。
        """
        mount_config = self.fs.get_mount_config(mount_point)
        
        if mount_config.mode == "ro":
            # 实际测试写入（临时文件）
            test_path = f"{mount_point}/.write_test_{uuid.uuid4()}"
            try:
                self.fs.upper.open(test_path, "w")
                # 如果成功，说明违反只读约束
                raise SecurityError(
                    f"Mount {mount_point} configured as RO but write succeeded"
                )
            except PermissionError:
                # 预期的行为：写入被拒绝
                pass
```

### 3. 凭证安全管理

**风险描述**:
- S3 密钥泄露到日志
- 配置文件中的密钥被提交到 Git
- 内存中的密钥被 core dump 捕获

**最佳实践**:

```python
# security/credential_manager.py
import os
import re
from typing import Optional

class CredentialManager:
    """
    安全凭证管理。
    
    原则：
    1. 密钥不持久化到日志
    2. 密钥不存储在配置文件
    3. 密钥在内存中加密或隔离
    """
    
    # 敏感键名模式
    SENSITIVE_KEYS = [
        'password', 'secret', 'key', 'token', 'credential',
        'aws_access_key_id', 'aws_secret_access_key'
    ]
    
    def __init__(self):
        self._secure_store: dict[str, str] = {}
    
    def load_from_env(self, var_name: str) -> Optional[str]:
        """从环境变量加载"""
        value = os.environ.get(var_name)
        if value:
            self._secure_store[var_name] = value
        return value
    
    def get_credential(self, key: str) -> Optional[str]:
        """获取凭证（仅内部使用）"""
        return self._secure_store.get(key)
    
    @staticmethod
    def mask_sensitive_data(data: dict) -> dict:
        """
        遮蔽敏感数据用于日志记录。
        
        将敏感字段替换为 ***MASKED***
        """
        masked = {}
        for key, value in data.items():
            if any(s in key.lower() for s in CredentialManager.SENSITIVE_KEYS):
                masked[key] = "***MASKED***"
            elif isinstance(value, dict):
                masked[key] = CredentialManager.mask_sensitive_data(value)
            else:
                masked[key] = value
        return masked
    
    @staticmethod
    def sanitize_log_message(message: str) -> str:
        """
        清理日志消息中的敏感信息。
        
        使用正则表达式移除可能意外泄露的密钥。
        """
        # 匹配常见的密钥格式
        patterns = [
            (r'AKIA[0-9A-Z]{16}', 'AKIA***REDACTED***'),  # AWS Access Key
            (r'[0-9a-zA-Z/+]{40}', '***SECRET_REDACTED***'),  # Generic 40-char secret
            (r'eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*', '***JWT_REDACTED***'),  # JWT token
        ]
        
        result = message
        for pattern, replacement in patterns:
            result = re.sub(pattern, replacement, result)
        
        return result


# 配置模板（仅含占位符）
SAFE_CONFIG_TEMPLATE = """
overlay:
  mounts:
    - name: s3_data
      source: s3://bucket/data
      options:
        # 使用环境变量引用，实际值从环境获取
        aws_access_key_id: ${AWS_ACCESS_KEY_ID}
        aws_secret_access_key: ${AWS_SECRET_ACCESS_KEY}
        # 不从配置文件读取
"""
```

**安全日志示例**:

```python
# logging_config.py
import logging

class SecurityFilter(logging.Filter):
    """过滤敏感信息的日志过滤器"""
    
    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = CredentialManager.sanitize_log_message(record.msg)
        if record.args:
            record.args = tuple(
                CredentialManager.sanitize_log_message(str(arg)) 
                if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True

# 应用到所有 handler
logger = logging.getLogger("scratchpad")
logger.addFilter(SecurityFilter())
```

### 4. 资源限制与 DoS 防护

```python
# security/resource_limits.py

class ResourceLimiter:
    """
    资源限制与 DoS 防护。
    """
    
    def __init__(self):
        self._session_limits: dict[str, SessionLimits] = {}
    
    def check_file_size_limit(
        self,
        session_id: str,
        file_size: int,
        max_size: int = 5 * 1024 * 1024 * 1024  # 5GB default
    ):
        """检查文件大小限制"""
        if file_size > max_size:
            raise ResourceLimitError(
                f"File size {file_size} exceeds limit {max_size}"
            )
    
    def check_session_quota(
        self,
        session_id: str,
        file_count: int = 0,
        total_size: int = 0
    ):
        """检查 session 配额"""
        limits = self._session_limits.get(session_id, SessionLimits())
        
        if file_count > limits.max_files:
            raise ResourceLimitError(
                f"File count {file_count} exceeds limit {limits.max_files}"
            )
        
        if total_size > limits.max_size:
            raise ResourceLimitError(
                f"Total size {total_size} exceeds limit {limits.max_size}"
            )

@dataclass
class SessionLimits:
    max_files: int = 10000
    max_size: int = 5 * 1024 * 1024 * 1024  # 5GB
    max_concurrent_operations: int = 10

class ResourceLimitError(Exception):
    pass
```

### 5. 安全审计与监控

```python
# security/auditing.py

class SecurityAuditor:
    """安全审计日志"""
    
    def __init__(self):
        self.audit_logger = logging.getLogger("scratchpad.audit")
    
    def log_file_access(
        self,
        session_id: str,
        path: str,
        operation: str,  # read, write, delete
        success: bool
    ):
        """记录文件访问日志"""
        self.audit_logger.info(
            f"FILE_ACCESS: session={session_id}, path={path}, "
            f"operation={operation}, success={success}"
        )
    
    def log_path_traversal_attempt(
        self,
        session_id: str,
        attempted_path: str,
        resolved_path: str
    ):
        """记录路径遍历尝试"""
        self.audit_logger.warning(
            f"PATH_TRAVERSAL_ATTEMPT: session={session_id}, "
            f"attempted={attempted_path}, resolved={resolved_path}"
        )
    
    def log_credential_access(
        self,
        credential_type: str,
        accessor: str
    ):
        """记录凭证访问"""
        self.audit_logger.info(
            f"CREDENTIAL_ACCESS: type={credential_type}, accessor={accessor}"
        )
```

### 6. 安全清单

部署前检查：

```markdown
## Pre-Deployment Security Checklist

- [ ] 路径遍历测试通过（包含 .. null 字节等攻击）
- [ ] Session 隔离验证通过（Session A 无法读取 Session B）
- [ ] 只读 mount 写入测试失败（确认不可写）
- [ ] 日志中无敏感信息泄露（密钥、密码）
- [ ] 配置文件中无硬编码密钥
- [ ] 资源限制生效（大文件、文件数限制）
- [ ] 审计日志正常记录
- [ ] 异常访问被正确拦截和记录
```

---

## Appendix

### A. 新增依赖

为实现多模态文件支持，需要添加以下依赖：

```toml
# pyproject.toml additions
[project.dependencies]
# ... existing dependencies ...
"Pillow>=10.0.0"  # Image processing for thumbnails

[project.optional-dependencies]
# For S3 support
s3 = [
    "s3fs>=2024.1.0",
]
# For full multi-modal support
multimodal = [
    "Pillow>=10.0.0",
]
```

依赖说明：
- **Pillow**: 用于图片处理和缩略图生成（~3MB）
- **s3fs**: 用于 S3 后端支持（可选）

### B. 术语表

| Term | Definition |
|------|------------|
| **fsspec** | Python 文件系统规范库，提供统一文件系统抽象 |
| **Overlay FS** | 联合文件系统，将多个目录合并为单一视图 |
| **Upperdir** | Overlay 文件系统中的可写层 |
| **Lowerdir** | Overlay 文件系统中的只读层 |
| **COW** | Copy-on-Write，写时复制机制 |
| **Mount Point** | 文件系统中挂载其他目录的接入点 |
| **MCP** | Model Context Protocol，模型上下文协议 |
| **Resource** | MCP 中声明式的内容源，通过 URI 访问 |
| **Session** | 一次独立的上下文隔离空间，有唯一 ID |

### C. 参考文档

- [fsspec Documentation](https://filesystem-spec.readthedocs.io/)
- [MCP Resources Specification](https://modelcontextprotocol.io/specification/2025-06-18/server/resources)
- [Docker OverlayFS Storage Driver](https://docs.docker.com/engine/storage/drivers/overlayfs-driver/)
- [Linux Kernel OverlayFS Documentation](https://docs.kernel.org/filesystems/overlayfs.html)
- [fsspec-union Library](https://github.com/1kbgz/fsspec-union)
- [Pillow Documentation](https://pillow.readthedocs.io/)

### D. 性能基准参考

**基础文件操作**:

| Operation | Current (Local FS) | Target (Overlay FS) | Acceptable |
|-----------|-------------------|---------------------|------------|
| Read 1MB | 10ms | < 50ms | < 100ms |
| Write 1MB | 15ms | < 50ms | < 100ms |
| List 1000 files | 50ms | < 100ms | < 200ms |
| Session creation | 5ms | < 20ms | < 50ms |

**多模态文件操作**:

| Operation | Target | Acceptable | Notes |
|-----------|--------|------------|-------|
| Read image < 512KB | < 100ms | < 200ms | Inline base64 |
| Generate thumbnail (128x128) | < 50ms | < 100ms | Pillow processing |
| Gallery view (20 images) | < 500ms | < 1000ms | Batch thumbnail |
| Read large image preview | < 200ms | < 500ms | First 100KB |
| PDF preview (first 1KB) | < 100ms | < 200ms | Metadata + preview |
---

## Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-03-19 | MCP Team | Initial draft |
| 2026-03-19 | MCP Team | Post-Metis Review: Added 6 required fixes |
| | | - [Security] Added Security Considerations section (path traversal, credential handling) |
| | | - [XML] Standardized all XML examples to flattened format |
| | | - [XML] Added error response schema with error codes |
| | | - [Whiteout] Added complete lifecycle documentation |
| | | - [Config] Added configuration validation logic |
| | | - [Cache] Added comprehensive cache invalidation strategy |
| | | - [Timeline] Extended from 4-week to 5-week plan |

