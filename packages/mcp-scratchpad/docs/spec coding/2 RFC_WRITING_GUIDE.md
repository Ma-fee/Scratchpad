# RFC 编写指南

> **文档版本**: 1.0.1  
> **创建日期**: 2026-03-25  
> **状态**: Active  
> **基于实例**: RFC-0001 Overlay Filesystem Architecture

---

## 📖 概述

RFC (Request for Comments) 是架构设计规范文档，用于在实现前详细描述技术方案、决策过程和实施计划。本文档基于 [`RFC-0001`](../../rfcs/draft/RFC-0001-scratchpad-overlay-fs.md) 的实际编写经验，总结出一套完整的 RFC 编写流程。

### 文档依据

本文档所有内容均基于实际文档归纳：
- **业务场景收集**：参考 [`RFC-0001` 第 61-201 行](../../rfcs/draft/RFC-0001-scratchpad-overlay-fs.md:61) "业务场景与需求驱动"
- **技术调研方法**：参考 [`RFC-0001` 第 203-243 行](../../rfcs/draft/RFC-0001-scratchpad-overlay-fs.md:203) "技术背景"
- **方案对比格式**：参考 [`RFC-0001` 第 328-471 行](../../rfcs/draft/RFC-0001-scratchpad-overlay-fs.md:328) "Options Analysis"
- **实施计划生成**：参考 [`.sisyphus/plans/overlay-fs-rfc-0001.md`](../../../../.sisyphus/plans/overlay-fs-rfc-0001.md) "Context → Research Findings"

---

## 为什么需要 RFC

| 原因 | 说明 | RFC-0001 实例 |
|------|------|---------------|
| **规范驱动开发** | 在编码前先设计，避免返工 | RFC 定义了 5 个业务场景和 3 种方案对比 |
| **决策透明化** | 记录技术决策的背景、理由和后果 | 第 9 章 "Decision Record" 记录了 9 个决策 |
| **团队协作** | 让所有利益相关者理解方案并参与讨论 | 第 1 章 Metadata 包含 Reviewers 字段 |
| **知识沉淀** | 作为项目的技术档案长期维护 | 文档状态流转：DRAFT → REVIEW → ACCEPTED |

---

## RFC 编写流程

### 阶段 1：准备与调研

#### 1.1 确定 RFC ID 和元数据

**依据**：[`RFC-0001` 第 5-18 行](../../rfcs/draft/RFC-0001-scratchpad-overlay-fs.md:5)

```markdown
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
```

**元数据字段说明**：
| 字段 | 说明 | 示例 |
|------|------|------|
| `RFC ID` | 唯一标识符，按顺序递增 | RFC-0001, RFC-0002 |
| `Title` | 简短描述核心内容 | "Overlay Filesystem Architecture" |
| `Status` | 文档状态 | DRAFT → REVIEW → ACCEPTED → IMPLEMENTED |
| `Author` | 主要作者 | 个人或团队 |
| `Reviewers` | 评审人 | TBD 或具体人员 |
| `Created` | 创建日期 | YYYY-MM-DD |
| `Last Updated` | 最后更新日期 | YYYY-MM-DD |
| `Decision Date` | 决策日期 | 接受或拒绝的日期 |

#### 1.2 收集业务场景

**依据**：[`RFC-0001` 第 61-201 行](../../rfcs/draft/RFC-0001-scratchpad-overlay-fs.md:61) "业务场景与需求驱动"

业务场景是 RFC 的核心驱动力，必须具体、可量化。RFC-0001 收集了 **5 个业务场景**：

```markdown
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
[Lower 层 - 只读共享]
  ├─ .claude/skills/        # 所有 session 共享的 skills
  └─ templates/notepad/     # Notepad 基础模板

[Upper 层 - Session 可写]
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
```

**业务场景编写要点**（基于 RFC-0001 归纳）：

| 要素 | 说明 | RFC-0001 实例 |
|------|------|---------------|
| **背景** | 描述业务上下文 | ".claude/skills 目录包含共享的 Agent skills 定义" |
| **当前痛点** | 列出具体问题，用 bullet points | "Skills 需要在每个 session 中重复复制，浪费存储" |
| **需要的能力** | 用图示或伪代码说明期望 | 三层架构图（Lower/Upper/Merged） |
| **示例** | 具体操作流程，步骤化 | "1. Session 启动... 2. Agent 读取..." |

**5 个业务场景总结**（RFC-0001）：
1. **Agent Skills 共享与模板 COW** - 写时复制共享
2. **多模态内容引用与溯源** - URI 溯源机制
3. **实时文档变更通知** - MCP 订阅模式
4. **跨会话资源共享与协作** - 多 session 协作流程
5. **混合存储后端支持** - S3/Local/Memory 混合

#### 1.3 技术调研

**依据**：[`RFC-0001` 第 203-243 行](../../rfcs/draft/RFC-0001-scratchpad-overlay-fs.md:203) "技术背景"

技术调研为方案选择提供依据，需要调研相关技术和现有方案。

```markdown
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
- **资源模板**: RFC 6570 URI 模板用于参数化资源
- **订阅通知**: `resources/subscribe` 支持变更推送
- **分页查询**: `resources/list` 支持游标分页
```

**技术调研要点**（基于 RFC-0001 归纳）：

| 调研内容 | 说明 | 输出形式 |
|----------|------|----------|
| **相关库/框架** | 列出可用的技术栈 | 表格（后端类型、类名、用途） |
| **参考架构** | 类似系统的架构设计 | 架构图 + 关键概念说明 |
| **协议/规范** | 相关标准协议 | 特性列表 |

---

### 谁来做：人与 LLM 的分工

**依据**：[`.sisyphus/plans/overlay-fs-rfc-0001.md` 第 27-38 行](../../../../.sisyphus/plans/overlay-fs-rfc-0001.md:27) "Interview Summary → Research Findings"

从实施计划文档可以看出，RFC 编写过程中人和 LLM 的分工如下：

#### 人（User）负责

| 任务 | 说明 | 实例 |
|------|------|------|
| **提供原始需求** | 描述业务痛点和期望 | "需要支持多 session 共享 skills" |
| **提供 RFC 文档** | 将需求整理成 RFC 格式 | User 提供了完整的 RFC-0001 文档 |
| **明确开发方法** | 指定使用 TDD 等 | "Explicitly requested TDD approach" |
| **最终决策** | 在多个方案中选择 | 选择 Option 3 (Hybrid Approach) |

#### LLM (Agent) 负责

| 任务 | 说明 | 实例 |
|------|------|------|
| **代码调研** | 分析现有代码库 | "Current codebase uses FileSystemStore with local filesystem only" |
| **技术调研** | 查找相关库和方案 | "No current fsspec dependency (needs to be added)" |
| **Gap 分析** | 识别实现中的问题 | "Metis Review: Identified Gaps" |
| **计划生成** | 将 RFC 分解为可执行任务 | 生成 5 阶段 40+ 任务的实施计划 |
| **TDD 执行** | 自动写测试、写实现、验证 | RED→GREEN→REFACTOR 循环 |

**关键证据**：从 [`.sisyphus/plans/overlay-fs-rfc-0001.md`](../../../../.sisyphus/plans/overlay-fs-rfc-0001.md:27) 可以看出：

```markdown
### Interview Summary
**Key Discussions**:
- User provided comprehensive RFC document at `/packages/mcp-scratchpad/docs/rfcs/draft/RFC-0001-scratchpad-overlay-fs.md`
- Explicitly requested TDD (Test-Driven Development) approach
- Implementation aligns with existing FastMCP-based mcp-scratchpad service

**Research Findings**:  # ← LLM 做的调研
- Current codebase uses FileSystemStore with local filesystem only  # ← 代码分析
- pytest testing infrastructure already exists  # ← 基础设施分析
- Pydantic models for request validation in place  # ← 现有代码分析
- FastMCP framework for MCP server implementation  # ← 框架分析
- No current fsspec dependency (needs to be added)  # ← 依赖分析
```

**总结**：
- **RFC 编写本身**：主要由人完成，LLM 可以提供建议
- **技术调研**：LLM 负责代码库分析，人负责业务场景定义
- **方案选择**：人做最终决策，LLM 提供对比分析
- **实施计划**：LLM 根据 RFC 自动生成任务分解
- **TDD 执行**：完全由 LLM 自动执行（"ZERO HUMAN INTERVENTION"）

---

### 阶段 2：问题定义与目标

#### 2.1 问题陈述

**依据**：[`RFC-0001` 第 246-275 行](../../rfcs/draft/RFC-0001-scratchpad-overlay-fs.md:246)

清晰描述当前面临的挑战：

```markdown
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
```

#### 2.2 目标与非目标

**依据**：[`RFC-0001` 第 279-302 行](../../rfcs/draft/RFC-0001-scratchpad-overlay-fs.md:279)

使用表格明确范围边界：

```markdown
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
```

#### 2.3 评估标准

**依据**：[`RFC-0001` 第 304-326 行](../../rfcs/draft/RFC-0001-scratchpad-overlay-fs.md:304)

定义技术和业务评估维度：

```markdown
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
```

---

### 阶段 3：方案设计与对比

#### 3.1 提出多个方案

**依据**：[`RFC-0001` 第 328-471 行](../../rfcs/draft/RFC-0001-scratchpad-overlay-fs.md:328) "Options Analysis"

至少提出 2-3 个可行方案进行对比：

```markdown
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
```

#### 3.2 推荐方案

**依据**：[`RFC-0001` 第 474-492 行](../../rfcs/draft/RFC-0001-scratchpad-overlay-fs.md:474)

明确推荐哪个方案并说明理由：

```markdown
## Recommendation

### 推荐方案：Option 3 - Hybrid Approach

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
```

---

## 完整 RFC 文档结构

基于 RFC-0001 的实际结构，完整的 RFC 文档包含以下章节：

```markdown
# RFC-XXXX: 标题

## Metadata (元数据)
| Field | Value |
|-------|-------|
| RFC ID | ... |
| Title | ... |
| Status | ... |
| Author | ... |
| Created | ... |

## Overview (概述)
- 核心目标
- 预期成果

## Background & Context (背景与上下文)
### 当前系统状态
### 业务场景与需求驱动 (5 个场景)
### 技术背景 (fsspec, Docker Overlay2, MCP Resources)

## Problem Statement (问题陈述)
### 当前面临的挑战
### 不解决的限制

## Goals & Non-Goals (目标与非目标)
| Goals | Non-Goals |
|-------|-----------|

## Evaluation Criteria (评估标准)
### 技术评估维度
### 业务评估维度

## Options Analysis (方案选项分析)
### Option 1: ...
### Option 2: ...
### Option 3: ...
### Comparative Summary

## Recommendation (推荐方案)

## Technical Design (技术设计)
### 系统架构
### 核心组件设计
### MCP 集成设计

## Implementation Plan (实施计划)
### Phase 1: ...
### Phase 2: ...

## Configuration Schema (配置规范)

## Open Questions (开放问题)
### 已决策问题
### 未解决问题

## Decision Record (决策记录)
### Decision 1: ...
### Decision 2: ...

## Security Considerations (安全考虑)

## Appendix (附录)
### A. 新增依赖
### B. 术语表
### C. 参考文档
### D. 性能基准参考

## Change Log (变更日志)
```

---

## RFC 状态流转

```
┌─────────┐    Review    ┌──────────┐    Accept    ┌───────────┐
│  DRAFT  │ ───────────> │  REVIEW  │ ───────────> │ ACCEPTED  │
└─────────┘              └──────────┘              └───────────┘
     ^                        |                         |
     |                        | Reject                  | Implement
     |                        v                         v
     |                   ┌──────────┐            ┌───────────┐
     └───────────────────│ REJECTED │            │IMPLEMENTED│
                         └──────────┘            └───────────┘
```

### 状态说明

1. **DRAFT**: 草稿状态，作者正在编写
2. **REVIEW**: 评审状态，等待团队评审
3. **ACCEPTED**: 已接受，可以开始实现
4. **IMPLEMENTED**: 已实现，功能已完成
5. **REJECTED**: 已拒绝，方案不被采纳
6. **SUPERSEDED**: 已取代，被更新的 RFC 取代

---

## 相关文档

- [`SPEC_TDD_DEVELOPMENT_FLOW.md`](../SPEC_TDD_DEVELOPMENT_FLOW.md) - Spec+TDD 开发流程
- [`RFC-0001-scratchpad-overlay-fs.md`](../../rfcs/draft/RFC-0001-scratchpad-overlay-fs.md) - 实际 RFC 示例
- [`.sisyphus/plans/overlay-fs-rfc-0001.md`](../../../../.sisyphus/plans/overlay-fs-rfc-0001.md) - 实施计划
