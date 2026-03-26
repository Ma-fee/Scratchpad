# Spec+TDD 开发流程完整指南

> **文档版本**: 1.0.0  
> **创建日期**: 2026-03-25  
> **状态**: Active  
> **适用项目**: MCP Scratchpad Overlay Filesystem

---

## 📖 目录

1. [概述](#概述)
2. [流程架构](#流程架构)
3. [阶段一：RFC 规范定义](#阶段一-rfc-规范定义)
4. [阶段二：实施计划分解](#阶段二实施计划分解)
5. [阶段三：TDD 执行循环](#阶段三-tdd-执行循环)
6. [阶段四：证据记录与验证](#阶段四证据记录与验证)
7. [文档体系结构](#文档体系结构)
8. [完整流程示例](#完整流程示例)
9. [最佳实践](#最佳实践)
10. [附录](#附录)

---

## 概述

本文档详细描述了 MCP Scratchpad 项目采用的 **Spec+TDD（规范驱动 + 测试驱动开发）** 开发流程。该流程将架构规范、任务分解、测试驱动开发和证据记录有机结合，确保开发过程的可追溯性、质量和自动化程度。

### 核心原则

| 原则 | 说明 |
|------|------|
| **规范驱动** | RFC 文档定义"做什么" - 架构、场景、接受标准 |
| **计划分解** | 实施计划定义"怎么做" - 任务、优先级、依赖 |
| **测试先行** | TDD 循环：RED→GREEN→REFACTOR |
| **零人工干预** | 所有 QA 由 agent 自动执行和验证 |
| **证据追踪** | 每个任务有独立的证据文件记录验证结果 |
| **持续学习** | notepads 记录关键决策和经验教训 |

### 适用场景

- 大型架构重构（如 RFC-0001 Overlay Filesystem）
- 核心组件开发
- 安全关键功能实现
- 多模块集成项目

---

## 流程架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Spec+TDD 开发流程全景图                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             │
│   │  阶段一      │    │  阶段二      │    │  阶段三      │             │
│   │  RFC 规范    │───▶│  计划分解    │───▶│  TDD 执行     │             │
│   │              │    │              │    │              │             │
│   │  • 业务场景  │    │  • 任务分解  │    │  • RED       │             │
│   │  • 架构设计  │    │  • 优先级    │    │  • GREEN     │             │
│   │  • 接受标准  │    │  • 依赖关系  │    │  • REFACTOR  │             │
│   └──────────────┘    └──────────────┘    └──────────────┘             │
│          │                   │                   │                      │
│          ▼                   ▼                   ▼                      │
│   ┌──────────────────────────────────────────────────────────┐         │
│   │                    文档产出物                             │         │
│   │  RFC-0001.md    plans/overlay-fs-*.md   evidence/*.txt   │         │
│   └──────────────────────────────────────────────────────────┘         │
│                                                                          │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             │
│   │  阶段四      │    │  持续学习    │    │  质量保障    │             │
│   │  证据记录    │◀──▶│  notepads    │◀──▶│  覆盖率检查  │             │
│   └──────────────┘    └──────────────┘    └──────────────┘             │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 阶段一：RFC 规范定义

### 目标

RFC（Request for Comments）文档是项目的**最高层级规范**，定义：
- 业务背景和驱动需求
- 架构设计方案
- 核心组件和接口
- 接受标准和验收条件

### 文档位置

```
docs/rfcs/draft/RFC-0001-scratchpad-overlay-fs.md
```

### RFC 文档结构

```markdown
# RFC-XXXX: 标题

## Metadata (元数据)
| Field | Value |
|-------|-------|
| RFC ID | RFC-0001 |
| Title | MCP Scratchpad Overlay Filesystem Architecture |
| Status | DRAFT/ACCEPTED/IMPLEMENTED |
| Author | MCP Scratchpad Team |
| Created | 2026-03-19 |

## Overview (概述)
- 核心目标
- 预期成果

## Background & Context (背景与上下文)
### 当前系统状态
- 现有架构分析
- 限制与痛点

### 业务场景与需求驱动
#### 场景 1: [场景名称]
- 背景
- 当前痛点
- 需要的能力
- 示例/图示

#### 场景 2: [场景名称]
...

## Architecture Design (架构设计)
### 核心组件
- 组件 1: 职责、接口
- 组件 2: 职责、接口

### 数据流
- 流程图
- 关键路径

### 接口定义
- API 规范
- 数据模型

## Acceptance Criteria (接受标准)
### 功能需求
- [ ] 需求 1
- [ ] 需求 2

### 性能指标
- 吞吐量：> X req/s
- 延迟：< Y ms

### 安全要求
- 路径遍历保护
- 会话隔离

## Implementation Roadmap (实施路线)
- Phase 1: Foundation
- Phase 2: Core Features
- Phase 3: Integration

## Out of Scope (范围外)
- 明确排除的功能
- 未来 RFC 考虑的内容
```

### RFC 文档关键要素

#### 1. 业务场景驱动

RFC 必须包含具体的业务场景，确保开发方向正确：

```markdown
#### 场景 1: Agent Skills 共享与模板 COW

**背景**: .claude/skills 目录包含共享的 Agent skills 定义

**当前痛点**:
- Skills 需要在每个 session 中重复复制，浪费存储
- 模板初始化需要基础模板 + session 本地修改

**需要的 Overlay 能力**:
```
[Lower 层 - 只读共享]
  ├─ .claude/skills/        # 所有 session 共享
  └─ templates/notepad/     # 基础模板

[Upper 层 - Session 可写]
  └─ workspace/             # Agent 实际编辑内容

[Merged View]
  ├─ .claude/skills/        # 可读取，不可修改
  └─ workspace/             # Agent 自由编辑
```
```

#### 2. 架构设计清晰

```markdown
## Architecture Design

### 核心组件

1. **SessionFileSystemManager**
   - 职责：管理 per-session 的文件系统实例
   - 接口：create_session(), get_filesystem(), cleanup_session()

2. **OverlayFileSystem**
   - 职责：实现多层 overlay 语义
   - 接口：read(), write(), delete(), ls()
   - 特性：COW, whiteout

3. **MountConfig**
   - 职责：配置驱动的路径挂载
   - 字段：name, source, mount_point, mode
```

#### 3. 接受标准可验证

```markdown
## Acceptance Criteria

### Phase 1: Foundation
- [ ] 配置文件可解析并验证
- [ ] SessionManager 可创建/销毁 session
- [ ] 每 session 有独立的 MemoryFileSystem
- [ ] 单元测试覆盖率 > 90%
```

---

## 阶段二：实施计划分解

### 目标

将 RFC 规范转化为可执行的**任务列表**，定义：
- 任务分解和粒度
- 执行优先级和依赖
- 并行执行策略（Waves）
- 每个任务的验收标准

### 文档位置

```
.sisyphus/plans/overlay-fs-rfc-0001.md
```

### 计划文档结构

```markdown
# RFC-0001: Overlay Filesystem Architecture Implementation

## TL;DR
> **快速摘要**: 一句话描述项目目标
> **交付物**: 列出核心交付物
> **估计工作量**: 5 weeks, 5 phases
> **关键路径**: Config → SessionManager → OverlayFS → Resources

## Context
### Original Request
### Interview Summary
### Research Findings
### Metis Review (Gap Analysis)

## Work Objectives
### Core Objective
### Concrete Deliverables
### Definition of Done
### Must Have (In Scope)
### Must NOT Have (Guardrails)

## Verification Strategy
### Test Strategy (TDD)
### Test Categories
### Coverage Requirements

## Execution Strategy

### Phase 1: Foundation (Week 1)

#### Wave 1: Foundation Layer (Parallel)
- Task 1: Add fsspec dependencies [quick]
- Task 2: MountConfig Pydantic models [quick]
- Task 3: OverlayConfig validation [quick]
- Task 4: SessionFileSystemManager skeleton [quick]
- Task 5: Configuration loader with env var [quick]

#### Wave 2: Core Manager (Parallel)
- Task 6: Session lifecycle management [medium]
- Task 7: Per-session MemoryFileSystem [medium]
- Task 8: Shared mount COW support [medium]
- Task 9: Session cleanup and resource mgmt [medium]

#### Wave 3: Cache Foundation
- Task 10: Directory index cache with TTL [medium]
- Task 11: Cache invalidation strategy [medium]
- Task 12: Memory management for cache [quick]

#### Wave FINAL: Phase 1 Verification
- Task F1.1: Unit tests for all components [deep]
- Task F1.2: Integration tests for SessionManager [deep]

### Phase 2: Overlay FS Core (Week 2)
...

### Phase 2b: Extended Overlay (Week 3)
...

### Phase 3: MCP Resources (Week 4)
...

### Phase 4: Integration & Hardening (Week 5)
...

## Risk Management
### Technical Risks
### Mitigation Strategies
```

### 任务分解原则

#### 1. 粒度控制

| 任务规模 | 预计时间 | 适用场景 |
|----------|----------|----------|
| quick | < 2 小时 | 简单配置、骨架代码 |
| medium | 2-8 小时 | 核心功能实现 |
| deep | 1-2 天 | 复杂算法、核心架构 |

#### 2. 并行执行策略

```
Wave 1 (Foundation Layer - All Parallel)
├── Task 1: 依赖添加 (独立)
├── Task 2: 配置模型 (独立)
├── Task 3: 配置验证 (依赖 Task 2)
├── Task 4: Manager 骨架 (独立)
└── Task 5: 配置加载器 (依赖 Task 2,3)
```

#### 3. 依赖管理

```
Task 1 (fsspec) ──┐
                  ├──▶ Task 13 (OverlayFS skeleton)
Task 4 (Manager) ─┘              │
                                 ▼
                          Task 14 (Path resolution)
```

### 任务定义模板

每个任务应有明确的定义：

```markdown
## Task N: 任务名称

### 目标
描述任务要完成的具体功能

### 输入
- 依赖的任务/组件
- 输入数据/配置

### 输出
- 产出的代码文件
- 测试文件
- 文档更新

### 验收标准
- [ ] 标准 1
- [ ] 标准 2
- [ ] 测试通过

### 实现提示
- 关键技术点
- 注意事项
```

---

## 阶段三：TDD 执行循环

### 目标

通过 **RED → GREEN → REFACTOR** 循环，确保：
- 代码质量
- 测试覆盖率
- 可维护性

### TDD 循环详解

```
┌─────────────────────────────────────────────────────────────┐
│                    TDD 执行循环                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   ┌─────────┐     ┌─────────┐     ┌─────────┐              │
│   │  RED    │────▶│  GREEN  │────▶│ REFACTOR│              │
│   │         │     │         │     │         │              │
│   │ 写测试  │     │ 写实现  │     │ 优化代码│              │
│   │ 测试失败│     │ 测试通过│     │ 保持通过│              │
│   └─────────┘     └─────────┘     └─────────┘              │
│        ▲                              │                      │
│        └──────────────────────────────┘                      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 步骤 1: RED (写测试)

**目标**: 编写描述预期行为的测试，确认测试失败

```python
# tests/unit/fs/test_overlay.py

class TestOverlayFileSystemSkeleton:
    """测试 OverlayFileSystem 骨架"""
    
    def test_protocol_defined(self):
        """测试：protocol 应定义为 'overlay'"""
        from fsspec.implementations.memory import MemoryFileSystem
        from mcp_scratchpad.fs.overlay import OverlayFileSystem
        
        upper = MemoryFileSystem()
        lowers = [MemoryFileSystem()]
        overlay = OverlayFileSystem(upper, lowers)
        
        # 预期：protocol == "overlay"
        assert overlay.protocol == "overlay"
    
    def test_cachable_false(self):
        """测试：cachable 应为 False"""
        from fsspec.implementations.memory import MemoryFileSystem
        from mcp_scratchpad.fs.overlay import OverlayFileSystem
        
        overlay = OverlayFileSystem(MemoryFileSystem(), [MemoryFileSystem()])
        
        assert overlay.cachable == False
```

**运行测试确认失败**:
```bash
$ pytest tests/unit/fs/test_overlay.py::TestOverlayFileSystemSkeleton::test_protocol_defined -v
FAILED - AttributeError: 'OverlayFileSystem' object has no attribute 'protocol'
```

### 步骤 2: GREEN (写实现)

**目标**: 编写最少代码让测试通过

```python
# src/mcp_scratchpad/fs/overlay.py

from fsspec.spec import AbstractFileSystem

class OverlayFileSystem(AbstractFileSystem):
    """Overlay 文件系统，实现多层覆盖语义"""
    
    protocol = "overlay"
    cachable = False
    
    def __init__(self, upper, lowers):
        """
        初始化 OverlayFileSystem
        
        Args:
            upper: 读写层 (read-write layer)
            lowers: 只读层列表，按优先级排序 (read-only layers)
        """
        super().__init__()
        self._upper = upper
        self._lowers = list(lowers)
```

**运行测试确认通过**:
```bash
$ pytest tests/unit/fs/test_overlay.py::TestOverlayFileSystemSkeleton::test_protocol_defined -v
PASSED
```

### 步骤 3: REFACTOR (重构)

**目标**: 优化代码结构，保持测试通过

```python
# src/mcp_scratchpad/fs/overlay.py

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fsspec.spec import AbstractFileSystem

class OverlayFileSystem(AbstractFileSystem):
    """
    Overlay 文件系统实现
    
    支持多层覆盖语义：
    - upper: 可读写层，存储 session 本地修改
    - lowers: 只读层列表，按优先级从高到低
    
    特性:
    - Copy-on-Write (COW): 修改下层文件时复制到上层
    - Whiteout: 删除文件时创建隐藏标记
    - 透明路径解析: 自动从正确层读取文件
    """
    
    protocol = "overlay"
    cachable = False
    
    def __init__(
        self,
        upper: AbstractFileSystem,
        lowers: List[AbstractFileSystem]
    ) -> None:
        """
        初始化 OverlayFileSystem
        
        Args:
            upper: 读写层 (read-write layer)
            lowers: 只读层列表，按优先级排序 (read-only layers)
        """
        super().__init__()
        self._upper: AbstractFileSystem = upper
        self._lowers: List[AbstractFileSystem] = list(lowers)
    
    @property
    def upper(self) -> AbstractFileSystem:
        """获取上层文件系统"""
        return self._upper
    
    @property
    def lowers(self) -> List[AbstractFileSystem]:
        """获取下层文件系统列表"""
        return self._lowers
```

**运行所有测试确认重构未破坏功能**:
```bash
$ pytest tests/unit/fs/test_overlay.py -v
PASSED - 8/8 tests passed
```

### TDD 测试层次

```
tests/
├── unit/                    # 单元测试 (快速、隔离)
│   ├── fs/
│   │   ├── test_overlay.py      # OverlayFileSystem 测试
│   │   ├── test_backends.py     # 后端测试
│   │   └── test_cache.py        # 缓存测试
│   ├── resources/
│   └── security/
│
├── integration/             # 集成测试 (组件交互)
│   ├── test_session_manager.py
│   └── test_resource_e2e.py
│
├── performance/             # 性能测试
│   └── test_benchmarks.py
│
└── security/                # 安全测试
    ├── test_path_traversal.py
    └── test_session_isolation.py
```

### 覆盖率要求

| Phase | 行覆盖率要求 | 分支覆盖率要求 |
|-------|-------------|---------------|
| Phase 1 | > 90% | > 85% |
| Phase 2 | > 85% | > 80% |
| Phase 2b | > 85% | > 80% |
| Phase 3+ | > 80% | > 75% |

**运行覆盖率检查**:
```bash
$ pytest --cov=mcp_scratchpad --cov-report=term-missing
Name                                    Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
mcp_scratchpad/fs/overlay.py              150     15    90%   120-130
-----------------------------------------------------------------------
TOTAL                                    2500    250    90%
```

---

## 阶段四：证据记录与验证

### 目标

为每个任务创建**证据文件**，记录：
- 任务完成情况
- 测试验证结果
- 文件修改清单
- 关键实现细节

### 证据文件位置

```
.sisyphus/evidence/task-N-task-name.txt
```

### 证据文件格式

```markdown
================================================================================
Task N: 任务名称
================================================================================

DATE: YYYY-MM-DD

================================================================================
1. FILES MODIFIED
================================================================================

1. path/to/file1.py
   - 修改内容描述
   - 新增方法/类

2. path/to/file2.py (new)
   - 文件用途
   - 主要功能

================================================================================
2. IMPLEMENTATION DETAILS
================================================================================

2.1 method_name()
-----------------

Signature:
    def method_name(self, param1: type, param2: type) -> return_type

Features:
    - 特性 1
    - 特性 2
    - 特性 3

Parameters:
    - param1: 参数说明
    - param2: 参数说明

Behavior:
    - 行为描述
    - 边界情况处理

================================================================================
3. QA SCENARIOS
================================================================================

3.1 场景名称
-----------

Steps:
    1. 步骤 1
    2. 步骤 2
    3. 步骤 3

Expected Result:
    预期结果描述

Actual Result:
    实际结果 (应匹配预期)

Verification:
    ✅ Check 1: True
    ✅ Check 2: True

================================================================================
4. TEST RESULTS
================================================================================

$ pytest tests/unit/path/to/test_file.py -v
tests/.../test_file.py::TestClass::test_case_1 PASSED
tests/.../test_file.py::TestClass::test_case_2 PASSED

X passed, Y failed

================================================================================
5. COMPLETION CHECKLIST
================================================================================

✅ Files created: file1.py, file2.py
✅ Files modified: file3.py
✅ Feature implemented: 功能描述
✅ Tests passing: X/X
✅ Evidence file created

================================================================================
```

### 证据文件示例

**文件**: `.sisyphus/evidence/task-13-skeleton.txt`

```markdown
=== QA Scenario: OverlayFS instantiation ===

1. from fsspec.implementations.memory import MemoryFileSystem
2. upper = MemoryFileSystem()
3. lowers = [MemoryFileSystem()]
4. overlay = OverlayFileSystem(upper, lowers)
5. print(overlay.protocol)

Result: protocol == "overlay" ✅

Verification:
  - protocol == "overlay": True ✅
  - cachable == False: True ✅
  - extends AbstractFileSystem: True ✅
  - upper stored correctly: True ✅
  - lowers stored correctly: True ✅

RESULT: SUCCESS - All checks passed!

=== Files Created ===
1. src/mcp_scratchpad/fs/overlay.py
   - OverlayFileSystem class extending AbstractFileSystem
   - protocol = "overlay"
   - cachable = False
   - __init__(self, upper, lowers) with proper type hints

2. tests/unit/fs/test_overlay.py
   - TestOverlayFileSystemSkeleton class
   - TestOverlayFileSystemInstantiation class
   - 8 test cases covering skeleton functionality

3. fs/__init__.py updated to export OverlayFileSystem
   - Added to __all__: "OverlayFileSystem"

=== Completion Checklist ===
✅ Files created: src/mcp_scratchpad/fs/overlay.py
✅ Files created: tests/unit/fs/test_overlay.py
✅ OverlayFileSystem extends AbstractFileSystem
✅ Constructor accepts upper and lowers parameters
✅ protocol defined as "overlay"
✅ cachable defined as False
✅ Type hints for all parameters
✅ Evidence file created
```

---

## 文档体系结构

### 完整文档树

```
项目文档结构
├── docs/                              # 用户文档
│   ├── rfcs/
│   │   └── draft/
│   │       └── RFC-0001-scratchpad-overlay-fs.md   # RFC 规范
│   ├── config-guide.md               # 配置指南
│   ├── fastmcp-architecture-design.md
│   ├── fastmcp-implementation-spec.md
│   └── SCRATCHPAD_PROMPT.md          # 工具使用指南
│
├── .sisyphus/                         # 开发过程文档
│   ├── plans/
│   │   └── overlay-fs-rfc-0001.md    # 实施计划
│   ├── evidence/
│   │   ├── task-1-fsspec-import.txt
│   │   ├── task-13-skeleton.txt
│   │   ├── task-24-whiteout-lifecycle.txt
│   │   └── ... (40+ 任务证据文件)
│   └── notepads/
│       ├── fs-cache/learnings.md
│       ├── mcp-resources/learnings.md
│       └── overlay-fs-rfc-0001/
│           ├── decisions.md          # 架构决策
│           ├── issues.md             # 问题记录
│           └── learnings.md          # 经验教训
│
└── SPEC_TDD_DEVELOPMENT_FLOW.md      # 本文档
```

### 文档关系图

```
┌─────────────────────────────────────────────────────────────────┐
│                        文档关系图                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │              RFC-0001 (规范层)                          │  │
│   │  • 业务场景  • 架构设计  • 接受标准  • 实施路线         │  │
│   └────────────────────────┬────────────────────────────────┘  │
│                            │ 定义 "做什么"                      │
│                            ▼                                    │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │           overlay-fs-rfc-0001.md (计划层)               │  │
│   │  • 任务分解  • 优先级  • 依赖  • 验收标准               │  │
│   └────────────────────────┬────────────────────────────────┘  │
│                            │ 定义 "怎么做"                      │
│                            ▼                                    │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │              代码实现层                                  │  │
│   │  • src/  • tests/  • 测试执行                           │  │
│   └────────────────────────┬────────────────────────────────┘  │
│                            │ 产出 "可验证结果"                  │
│                            ▼                                    │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │              evidence/*.txt (证据层)                     │  │
│   │  • 测试结果  • 文件清单  • 完成检查                      │  │
│   └─────────────────────────────────────────────────────────┘  │
│                                                                  │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │              notepads/ (学习层)                          │  │
│   │  • decisions.md  • issues.md  • learnings.md            │  │
│   └─────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 完整流程示例

### 示例：Task 24 - Whiteout 生命周期

#### Step 1: 从 RFC 理解需求

**RFC-0001 相关章节**:
```markdown
### Whiteout 机制

当删除文件时：
- 如果文件在 upper layer: 直接删除
- 如果文件在 lower layer: 创建 `.wh.<filename>` 标记

当删除目录时：
- 如果目录为空：直接删除
- 如果目录有内容：递归删除或创建 whiteout
```

#### Step 2: 从计划获取任务定义

**计划中的 Task 24**:
```markdown
## Task 24: Complete Whiteout Lifecycle

### 目标
实现完整的 whiteout 生命周期管理

### 验收标准
- [ ] rmdir() 支持 whiteout
- [ ] rm(recursive=True) 处理目录删除
- [ ] clean_whiteout() 清理过期标记
- [ ] is_whited_out() 检查 whiteout 状态

### 依赖
- Task 20: 基础 whiteout 实现
```

#### Step 3: TDD 执行

**RED - 编写测试**:
```python
# tests/unit/fs/test_overlay.py

class TestWhiteoutLifecycle:
    def test_rmdir_creates_whiteout_for_lower_layer(self):
        """测试：删除下层目录应创建 whiteout"""
        # Setup: 下层有目录，上层为空
        lower = MemoryFileSystem()
        lower.mkdir("/lower_dir")
        
        upper = MemoryFileSystem()
        overlay = OverlayFileSystem(upper, [lower])
        
        # Action: 删除下层目录
        overlay.rmdir("/lower_dir")
        
        # Assert: 下层目录仍在，upper 有 whiteout
        assert lower.exists("/lower_dir")  # 下层未变
        assert upper.exists("/.wh.lower_dir")  # whiteout 已创建
```

**GREEN - 实现代码**:
```python
# src/mcp_scratchpad/fs/overlay.py

def rmdir(self, path: str, **kwargs) -> None:
    """删除目录"""
    # 检查是否在 upper
    if self._upper.exists(path):
        if not self._upper.ls(path):  # 空目录
            self._upper.rm(path)
        else:
            raise OSError(f"Directory not empty: {path}")
    else:
        # 下层目录，创建 whiteout
        whiteout_path = f"/.wh.{path.lstrip('/')}"
        self._upper.touch(whiteout_path)
```

**REFACTOR - 优化代码**:
```python
def rmdir(self, path: str, **kwargs) -> None:
    """
    删除目录，支持 whiteout 语义
    
    Args:
        path: 目录路径
        **kwargs: 传递给底层文件系统的参数
    
    Raises:
        OSError: 目录非空时
        NotADirectoryError: 路径是文件时
    """
    path = self._strip_protocol(path)
    
    # 检查是否为目录
    if not self.isdir(path):
        raise NotADirectoryError(f"Not a directory: {path}")
    
    # 检查是否在 upper
    if self._is_in_upper(path):
        self._delete_from_upper(path)
    else:
        self._create_whiteout(path)
```

#### Step 4: 运行测试验证

```bash
$ pytest tests/unit/fs/test_overlay.py::TestWhiteoutLifecycle -v
============================= test session starts =============================
tests/unit/fs/test_overlay.py::TestWhiteoutLifecycle::test_rmdir_creates_whiteout PASSED
tests/unit/fs/test_overlay.py::TestWhiteoutLifecycle::test_rm_recursive PASSED
tests/unit/fs/test_overlay.py::TestWhiteoutLifecycle::test_clean_whiteout PASSED
tests/unit/fs/test_overlay.py::TestWhiteoutLifecycle::test_is_whited_out PASSED

4 passed in 0.12s
```

#### Step 5: 创建证据文件

**文件**: `.sisyphus/evidence/task-24-whiteout-lifecycle.txt`

```markdown
# Task 24: Complete Whiteout Lifecycle for OverlayFileSystem

## Implementation Summary

This task implements the complete whiteout lifecycle for the OverlayFileSystem.

## Files Modified

- `src/mcp_scratchpad/fs/overlay.py` - Main implementation file

## Methods Implemented

### 1. rmdir(path, **kwargs) - Remove Directory with Whiteout Support

- Removes empty directories from upper layer directly
- Creates whiteout marker (`.wh.<dirname>`) for lower layer directories
- Raises `OSError` if directory is not empty
- Idempotent: succeeds if already whited-out

### 2. Enhanced rm(path, recursive=False, **kwargs)

- Added `recursive` parameter (default: False)
- When `recursive=True`: recursively removes directory and all contents
- Maintains proper overlay semantics throughout

### 3. clean_whiteout(path=None, expired_only=True, dry_run=False, **kwargs)

- Removes whiteout markers that are no longer needed
- Returns list of whiteout paths that were removed

### 4. is_whited_out(path, include_expired=False, **kwargs)

- Public API to check if a path has a whiteout marker

## Test Results

$ pytest tests/unit/fs/test_overlay.py::TestWhiteoutLifecycle -v
4 passed in 0.12s

## Completion Checklist

✅ rmdir() implemented with whiteout support
✅ rm(recursive=True) handles directory deletion
✅ clean_whiteout() removes stale whiteouts
✅ is_whited_out() public API available
✅ All tests passing
✅ Evidence file created
```

---

## 最佳实践

### 1. RFC 编写最佳实践

- **场景驱动**: 用具体场景说明需求，避免抽象描述
- **图示辅助**: 使用 ASCII 图或流程图说明架构
- **明确边界**: 清楚定义 In Scope 和 Out of Scope
- **可验证标准**: 接受标准应可量化、可测试

### 2. 计划分解最佳实践

- **合理粒度**: 任务应在 0.5-8 小时范围内
- **依赖清晰**: 明确任务间的依赖关系
- **并行机会**: 识别可并行执行的 Wave
- **缓冲时间**: 为复杂任务预留 buffer

### 3. TDD 执行最佳实践

- **小步快跑**: 每次只改一行代码
- **测试先行**: 先写测试，再写实现
- **保持绿色**: 确保测试始终通过
- **及时重构**: 代码异味立即重构

### 4. 证据记录最佳实践

- **实时记录**: 完成任务后立即记录
- **包含命令**: 记录执行的命令和输出
- **截图验证**: 复杂场景可附加截图
- **检查清单**: 使用 checklist 确保完整

### 5. 文档维护最佳实践

- **单一来源**: 每个信息只在一个地方定义
- **版本控制**: 文档随代码一起版本化
- **链接完整**: 文档间使用完整链接
- **定期更新**: 实现变更时同步更新文档

---

## 附录

### A. 文档模板

#### RFC 模板
```markdown
# RFC-XXXX: 标题

## Metadata
| Field | Value |
|-------|-------|
| RFC ID | RFC-XXXX |
| Title | 标题 |
| Status | DRAFT/ACCEPTED/IMPLEMENTED |
| Author | 作者 |
| Created | YYYY-MM-DD |

## Overview
## Background & Context
## Architecture Design
## Acceptance Criteria
## Implementation Roadmap
## Out of Scope
```

#### 任务证据模板
```markdown
# Task N: 任务名称

## Implementation Summary
## Files Modified
## Methods Implemented
## Test Results
## Completion Checklist
```

### B. 工具链

| 工具 | 用途 |
|------|------|
| pytest | 测试框架 |
| pytest-cov | 覆盖率报告 |
| uv | 依赖管理 |
| fsspec | 文件系统抽象 |

### C. 参考文档

- [RFC-0001](docs/rfcs/draft/RFC-0001-scratchpad-overlay-fs.md)
- [实施计划](.sisyphus/plans/overlay-fs-rfc-0001.md)
- [配置指南](docs/config-guide.md)
- [FastMCP 规范](docs/fastmcp-implementation-spec.md)

---

**文档结束**
