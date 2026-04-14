# Overlay Filesystem 与工具链说明

## 1. 文档目标

本文档用于完整说明当前 `mcp-scratchpad` 中 overlay filesystem 的工作机制、文件工具的行为语义，以及“跨 session 共享记忆”应如何设计与实现。

重点回答以下问题：

- 当前 session overlay 模型到底是什么
- `list`、`read`、`write`、`edit`、`multiedit`、`patch`、`remove` 这些工具各自如何与 upper / lower layer 交互
- lower layer 为什么默认不能直接写
- 如果要做跨 session 共享记忆，应该怎么选型
- 推荐的 `publish_memory` 方案到底在发布什么、如何发布、其他 session 如何消费

---

## 2. 核心结论

当前系统的核心模型不是“一个可直接修改的共享文件系统”，而是：

- 每个 session 有一份独立的可写 `upper layer`
- 所有 session 共享一组只读 `lower layers`
- 所有文件工具都面向“session 视图”工作
- 工具不会直接决定读写哪一层
- overlay filesystem 负责决定：
  - 读取来自 upper 还是 lower
  - 是否触发 copy-on-write
  - 删除是否变成 whiteout

因此，当前设计天然适合：

- session 内私有工作记忆
- 基于共享模板 / 共享知识库的派生编辑
- 多 session 并行工作互不污染
- 共享内容通过“发布”进入 lower 对应的持久化来源

而它**不适合**：

- 直接把 lower 当成协同写存储层
- 让任意 session 直接修改公共知识库
- 把“共享记忆”直接建在 session upper 上

---

## 3. 当前 overlay 模型

### 3.1 session 创建时发生了什么

每次创建一个 session，系统都会创建一套独立的 overlay 视图：

- 一个新的 `MemoryFileSystem` 作为当前 session 的 `upper layer`
- 一组来自 YAML `mounts` 配置的 lower filesystems
- 一个 `OverlayFileSystem(upper, lowers)` 作为当前 session 的文件系统视图

也就是说：

- session A 有自己的 upper
- session B 有自己的 upper
- A 和 B 可以共享 lower
- A 和 B 的 upper 默认互相不可见

这也是为什么当前系统**默认不支持跨 session 直接共享 upper memory**。

### 3.2 upper / lower 的职责

#### upper layer

upper 是当前 session 的工作层，用来承载：

- 新建文件
- 编辑结果
- patch 结果
- 删除产生的 whiteout 标记
- 当前 session 的中间草稿和推理副产物

当前实现中 upper 是内存层，因此非常适合作为“工作内存”。

#### lower layers

lower 是共享基线层，典型内容包括：

- `/templates`
- `/kb`
- `/skills`
- `/data`
- `/memory`（如果后续引入共享记忆挂载）

lower 可以被 `list/read/info`，但不应该被普通文件工具直接改写。

### 3.3 层级优先级

overlay 的可见性优先级是：

1. whiteout
2. upper
3. lower（按 priority 从高到低）

因此：

- 同一路径 upper 存在时，upper 覆盖 lower
- whiteout 存在时，即使 lower 有文件，也会被隐藏
- lower 之间如果有同名路径，以 priority 更高者为准

---

## 4. overlay 的关键机制

### 4.1 读取解析

overlay 在读取路径时会做统一解析：

1. 检查这个路径是否被 whiteout 隐藏
2. 查 upper 是否存在
3. 如果 upper 不存在，再按顺序查 lowers

因此：

- `exists`、`isfile`、`isdir`
- `info`
- `ls`
- 只读模式的 `open`

本质上都基于这套解析规则。

### 4.2 Copy-on-Write

如果一个文件只存在于 lower，而当前 session 试图修改它：

1. 先从 lower 读取原文件
2. 拷贝到 upper
3. 修改后的结果写入 upper

最终效果是：

- 当前 session 看起来像“改了这个文件”
- 共享 lower 并未被修改

这就是 copy-on-write。

### 4.3 Whiteout

如果某个文件只存在于 lower，而当前 session 调用了删除：

- 系统不会删 lower 中的真实文件
- 而是在 upper 里创建 `.wh.<filename>` 标记

这个 whiteout 的语义是：

- 对当前 session 来说，这个 lower 文件已经“逻辑删除”
- 对其他 session 来说，这个 lower 文件仍然存在

---

## 5. 当前文件工具的语义

这里必须强调：**工具操作的是 session 视图，不是物理层。**

### 5.1 `list`

`list` 返回的是当前 session 的合并后可见文件树：

- 会看到 upper 中的内容
- 会看到未被覆盖的 lower 内容
- 会隐藏被 whiteout 的 lower 文件

因此它列出来的是“当前 session 真实看到的世界”，不是单独的 upper，也不是裸 lower。

### 5.2 `read`

`read` 返回当前 session 能看到的最终版本：

- upper 有则读 upper
- upper 没有但 lower 有，则读 lower
- 都没有则报错

### 5.3 `write`

`write` 一定不会直接修改 lower：

- 如果目标已经在 upper，则覆盖 upper
- 如果目标只在 lower，则触发 copy-up，最终写入 upper
- 如果目标在任何层都不存在，则直接在 upper 新建

### 5.4 `edit`

`edit` 的逻辑是：

1. 读当前可见内容
2. 在内存中做一次替换
3. 把替换后的结果写回 session

如果原文件来自 lower，那么最终落地到 upper。

### 5.5 `multiedit`

`multiedit` 与 `edit` 相同，只是顺序执行多次替换，最后一次性持久化到 upper。

### 5.6 `patch`

`patch` 的逻辑是：

1. 读取当前可见文件
2. 应用 unified diff
3. 将结果写入 upper

如果目标原来在 lower，就等价于“copy-up 后 patch”。

### 5.7 `remove`

`remove` 的行为取决于文件来源：

- 文件在 upper：直接从 upper 删除
- 文件只在 lower：创建 whiteout
- 文件不存在：报错

因此 `remove` 对 lower 文件是“逻辑删除”，不是物理删除。

---

## 6. 业务场景穷举

## 7. `publish_memory` 的当前实现状态

现在仓库里已经新增了显式的 `publish_memory` 路径，语义是：

- 输入必须是当前 session 可见文件
- 服务先通过 `UnifiedSessionFSAdapter` 读取当前 session 视图中的源内容
- 然后根据 `memory.publish.namespaces.<namespace>` 配置解析共享 backend
- 当前仅支持 `file` backend
- 发布结果会把正文写到配置的 namespace 根目录下，并额外生成 `.meta.json` sidecar
- 其他 session 通过 `/memory/<namespace>/...` 只读 lower mount 看到该内容

默认约束仍然保持不变：

- 普通文件工具不会直接写 lower mount
- session 后续对 `/memory/...` 的编辑必须经过 overlay copy-on-write，结果只留在本 session upper layer
- overwrite 语义只由 `publish_memory` 控制，不应由普通 `write/edit/patch` 绕过

### 7.1 配置约定

推荐同时配置两部分：

- `memory.publish.namespaces`
  - 决定 `publish_memory` 把某个 namespace 发布到哪里
- `mounts`
  - 把对应目录以只读方式挂到 `/memory/<namespace>`

例如 `users` namespace：

- `memory.publish.namespaces.users.root = /tmp/mcp-scratchpad/shared-memory/users`
- `mounts[*].mount_point = /memory/users`

这样发布和消费才会对齐到同一份底层目录。

### 场景 1：共享模板，session 私有改写

假设 lower 中有 `/templates/report.md`。

session A：

1. `read("/templates/report.md")`
2. `edit("/templates/report.md", ...)`

结果：

- A 在 upper 中得到一份改写后的版本
- lower 模板保持不变
- session B 仍然看到原模板

这是 overlay 最典型的使用方式。

### 场景 2：共享知识只读，工作结果写到 `/workspace`

假设 lower 中有 `/kb/specs/rfc-1.md`。

session A：

1. `read("/kb/specs/rfc-1.md")`
2. `write("/workspace/summary.md", ...)`

结果：

- `/kb/...` 仍然是共享只读知识
- `/workspace/summary.md` 只属于 session A 的 upper

### 场景 3：在当前 session 中屏蔽某个共享文件

假设 lower 中有 `/skills/python/skill.md`。

session A：

1. `remove("/skills/python/skill.md")`

结果：

- 当前 session 看不到它
- lower 中原文件仍在
- session B 依然可以看到

### 场景 4：对 lower 文件打补丁

假设 lower 中有 `/templates/base.txt`。

session A：

1. `patch("/templates/base.txt", diff=...)`

结果：

- 文件从 lower 被 copy-up 到 upper
- patch 结果只存在于当前 session

### 场景 5：创建新文件再删除

session A：

1. `write("/workspace/note.txt", ...)`
2. `remove("/workspace/note.txt")`

结果：

- 文件在 upper 中创建
- 后续直接从 upper 删除
- 不涉及 whiteout

### 场景 6：删除 lower 文件后又重新创建

假设 lower 中有 `/kb/a.txt`。

session A：

1. `remove("/kb/a.txt")`
2. `write("/kb/a.txt", "replacement")`

结果：

- 第一步创建 whiteout
- 第二步移除 whiteout 并在 upper 中生成同路径新文件
- 当前 session 看到的是新 upper 版本
- lower 原版仍然存在

---

## 7. 当前系统对“跨 session 共享记忆”的真实支持情况

### 7.1 不能直接共享 upper

当前系统**不能**让 session A 的 upper 直接成为 session B 的可见工作层。

原因：

- 每个 session 都独立创建 `MemoryFileSystem`
- upper 是严格的 session 私有工作层
- 工具只对当前 session 生效

因此，A 在 upper 中写出的草稿、摘要、补丁，默认只有 A 自己能看到。

### 7.2 可以共享 lower 对应的基线记忆

当前系统**已经支持**跨 session 共享只读记忆，方式是：

- 把共享记忆存进 lower 对应的真实数据源
- 通过 `file://` 或 `s3://` 挂成 lower mount
- 所有 session 都从这个 lower 读取

换句话说：

- 当前架构支持“共享可读记忆”
- 不支持“共享可写 upper”

---

## 8. 记忆分层设计建议

最合理的做法不是问“能不能共享”，而是把记忆分成三类。

### 8.1 Working Memory

工作记忆，位置在 session upper。

特点：

- 只属于当前 session
- 可频繁修改
- 可以是中间推理结果
- 不适合作为长期共享知识

### 8.2 Shared Read Memory

共享只读记忆，位置在 lower mounts。

特点：

- 所有 session 可读
- 普通工具不直接写
- 适合作为公共知识与长期沉淀

### 8.3 Durable Personal / Agent Memory

可持久化的按用户或按 agent 组织的长期记忆。

建议存储为共享 lower 来源的一部分，例如：

- `/memory/users/<user_id>/...`
- `/memory/agents/<agent_id>/...`
- `/memory/teams/<team_id>/...`

这样它可以跨多个 session 复用，但仍然保持只读基线语义。

---

## 9. 为什么不建议让普通工具直接写 lower

这是一个关键选型问题。

从直觉上看，让 `write/edit/patch/remove` 直接修改共享 lower，好像能立刻实现“共享记忆”。但从架构上看，这会把系统从“session overlay”变成“协同写共享存储”，代价很大。

如果普通工具允许直写 lower，会立刻出现这些问题：

- 谁拥有共享记忆的写权限
- 多 session 同时写时如何解决冲突
- 删除 lower 文件时 whiteout 还是否成立
- 一个 agent 的草稿是否会污染所有 session
- 写入失败时如何回滚
- S3 / file backend 的一致性如何保证

因此，当前更合理的选型是：

- 普通文件工具只写 upper
- lower 保持共享只读基线
- 共享记忆通过显式“发布”动作写入 lower 对应的真实数据源

---

## 10. 推荐方案：显式发布共享记忆

### 10.1 方案概念

推荐引入一类显式工具，例如：

```python
publish_memory(
    session_id="...",
    source_path="/workspace/summary.md",
    target_namespace="users",
    target_key="user-42/summary.md",
)
```

这个动作的真正含义不是：

- “把 upper 的地址挂到 lower”

而是：

- 从当前 session 读取 `source_path` 的内容
- 把内容写入共享记忆的真实底层存储
- 使其成为所有 session 都能通过 lower 读取的共享文件

因此，发布的是**内容实体**，不是指针，也不是引用地址。

### 10.2 发布后其他 session 看到什么

假设：

- 当前 session upper 中有 `/workspace/summary.md`
- 发布目标是共享 memory

发布后，底层会真实生成一个共享文件，例如：

- 本地目录：`/shared-memory/users/user-42/summary.md`
- 或 S3：`s3://shared-memory/users/user-42/summary.md`

然后通过 lower mount 暴露成：

- `/memory/users/user-42/summary.md`

其他 session 看到的是这个共享文件本身，而不是发布者 upper 的地址。

### 10.3 发布后何时副本化

其他 agent / session：

- 如果只是 `read`，直接读 lower
- 如果后续 `edit/write/patch` 这个共享文件，则触发 copy-on-write
- 修改结果会进入各自 upper

因此正确理解是：

- 发布 = 形成共享基线
- 消费 = 大家都能读
- 再加工 = 谁改谁副本化到自己的 upper

---

## 11. 发布方案的技术实现

### 11.1 推荐发布流程

推荐的实现流程是：

1. 使用当前 session 读取 `source_path`
2. 校验目标 namespace / key 是否合法
3. 根据 namespace 映射到共享 memory backend
4. 把内容写入共享 backend
5. 返回 canonical path / URI / metadata

### 11.2 发布目标不是 overlay lower 本身，而是 lower 的真实来源

这点必须讲清楚。

当前 lower 是只读挂载视图，因此“发布到 lower”在技术上应该理解成：

- 写入 lower 对应的真实数据源
- 而不是试图直接操作 overlay lower 对象

例如：

#### file 后端

- lower mount: `/memory`
- source: `file:///shared-memory`

那么 publish 实际写的是：

- `/shared-memory/...`

然后所有 session 通过 lower 读取 `/memory/...`

#### s3 后端

- lower mount: `/memory`
- source: `s3://shared-memory`

那么 publish 实际写的是：

- `s3://shared-memory/...`

然后所有 session 通过 lower 读取 `/memory/...`

### 11.3 为什么这样设计更好

这种方案有几个好处：

- session 工作层与共享基线边界清楚
- 可以在发布前做审核、清洗、去重
- 不破坏 overlay 原有语义
- 不把普通编辑工具变成共享写工具
- 更容易做权限和命名空间控制

---

## 12. 共享记忆的几种选型

### 12.1 方案 A：共享 KB 挂载

做法：

- 把长期共享记忆放到本地目录或对象存储
- 挂成 lower，比如 `/kb` 或 `/memory`

优点：

- 当前架构原生支持
- 所有 session 都能读
- 运营和审计简单

缺点：

- 写入需要外部发布流程
- 不适合高频实时协同写

适合：

- FAQ
- 用户画像摘要
- 已审核结论
- 团队知识库

### 12.2 方案 B：session 结果显式 promote / publish

做法：

- session 内先在 upper 工作
- 选中的结果显式发布到共享 memory 源

优点：

- 最符合当前 overlay 架构
- 草稿与共享记忆边界清楚
- 安全性高

缺点：

- 需要增加发布工具或流程

适合：

- 会话总结
- 已确认用户偏好
- 结构化长期记忆

### 12.3 方案 C：按用户 / agent / team 分层的共享 memory

做法：

- 在 lower 中增加 `/memory`
- 再按 namespace 划分：
  - `/memory/users/...`
  - `/memory/agents/...`
  - `/memory/teams/...`

优点：

- 跨 session 可复用
- 组织清晰
- 容易做权限边界

缺点：

- 需要规范命名与发布策略

### 12.4 方案 D：直接共享 upper

当前不推荐。

原因：

- 会破坏 session 隔离
- 会引入并发写冲突
- 会让普通工具语义变复杂
- 会把当前系统变成协同写系统

如果真的要做，那已经不是简单扩展 overlay，而是另一条架构路线。

---

## 13. 现阶段推荐落地方案

如果目标是“跨 session 共享记忆”，建议按下面路线落地：

### 配置层

新增一个共享 lower mount，例如：

- `/memory/users`
- `/memory/agents`
- `/memory/teams`

底层来源可选：

- `file://` 本地目录
- `s3://` / MinIO

### 运行时层

保持现有文件工具只写 session upper：

- `write`
- `edit`
- `multiedit`
- `patch`
- `remove`

都不直写 lower。

### 发布层

增加显式工具或后台流程，例如：

- `publish_memory`
- `promote_file`
- `commit_to_shared_memory`

让 session 内选中的结果进入共享持久层。

### 消费层

其他 session 通过 lower mount 读取共享记忆。

如果他们继续修改共享文件，copy-on-write 到各自 upper。

---

## 14. 缓存与发布可见性

发布完成后，其他 session 什么时候能看到共享记忆，还与底层 backend 的缓存有关。

当前 YAML 中常见选项：

- `use_listings_cache`
- `listings_expiry_time`

因此：

- 如果共享记忆要求较快可见，应降低共享 memory mount 的 cache TTL
- 对极端追求实时性的共享区，可以考虑关闭 listings cache

否则会出现：

- 数据已经发布到底层源
- 但某些 session 的 `list` 短时间内仍看不到最新条目

这不是 overlay 语义错误，而是底层目录 / 对象存储缓存行为。

---

## 15. 常见误区

### 误区 1：RW mount 就等于工具会写入这个共享目录

不对。

当前 session overlay 模型下，普通文件工具写的是 session upper，而不是直接写 lower 来源。

### 误区 2：共享记忆就应该直接存到 lower

不完整。

更准确地说，应该：

- 把内容写到 lower 对应的真实持久化源
- 再通过 lower mount 暴露出来

### 误区 3：发布的是 session upper 文件地址

不对。

发布的是**文件内容进入共享存储后的共享实体**。

### 误区 4：其他 session 一看到共享文件就自动副本化

不对。

只有在其他 session 修改它时，才会 copy-up 到自己的 upper。

### 误区 5：让普通工具直接写 lower 会更简单

短期看像是更直接，长期看会破坏整个 session overlay 设计边界。

---

## 16. 最终建议

当前架构下，对“共享记忆”的最佳理解是：

- upper = 工作记忆
- lower = 共享基线记忆
- publish = 从工作记忆中显式沉淀到共享基线

推荐遵循以下原则：

1. 普通文件工具继续保持 session-local
2. lower 继续作为共享只读基线
3. 共享记忆通过显式发布进入 lower 来源
4. 其他 session 以 read-first、write-copy-up 的方式消费共享记忆

这条路线最符合当前代码实现，也最容易长期演进。

---

## 17. 发布流程时序图

下面用一个典型例子说明 `publish_memory` 的完整链路。

假设：

- session A 在 upper 中产出 `/workspace/summary.md`
- 目标是把它发布到共享记忆 `/memory/users/user-42/summary.md`
- lower mount 背后真实来源是：
  - 本地目录 `/shared-memory/users/user-42/summary.md`
  - 或 S3 `s3://shared-memory/users/user-42/summary.md`

### 17.1 逻辑时序

1. session A 使用 `write/edit/patch` 在 upper 中得到 `/workspace/summary.md`
2. `publish_memory` 读取 session A 当前可见版本
3. `publish_memory` 校验目标 namespace 和 target key
4. `publish_memory` 将内容写入共享 memory 的真实持久化源
5. lower mount 将这份共享文件暴露为 `/memory/users/user-42/summary.md`
6. session B 后续 `list/read("/memory/users/user-42/summary.md")`
7. 如果 session B 只读，则直接读 lower
8. 如果 session B 继续修改，则 copy-up 到 session B 的 upper

### 17.2 ASCII 时序图

```text
Session A Tools        Overlay View A        Publish Layer        Shared Backend        Lower Mount        Session B Tools
     |                      |                     |                    |                    |                    |
     | write/edit/patch     |                     |                    |                    |                    |
     |--------------------->|                     |                    |                    |                    |
     |                      | upper:/workspace/summary.md              |                    |                    |
     |                      |                     |                    |                    |                    |
     | publish_memory       |                     |                    |                    |                    |
     |--------------------->| read source_path    |                    |                    |                    |
     |                      |-------------------->| validate target    |                    |                    |
     |                      |                     |------------------->| write shared file  |                    |
     |                      |                     |                    |------------------->| visible as lower   |
     |                      |                     |                    |                    |                    |
     |                      |                     |                    |                    | list/read          |
     |                      |                     |                    |                    |<-------------------|
     |                      |                     |                    |                    | return lower file  |
     |                      |                     |                    |                    |------------------->|
```

### 17.3 关键语义

这张图里最重要的不是“拷贝了一份文件”，而是职责边界：

- session A 的 upper 仍然只是工作层
- 发布层负责把工作结果转成共享资产
- shared backend 才是共享记忆的真实存储位置
- lower mount 只是把 shared backend 映射到 session 可读视图

因此：

- 发布不是“开放 lower 可写”
- 发布是“写入 lower 对应的真实持久化源”

---

## 18. 共享记忆目录设计建议

如果后续要正式引入共享记忆，建议尽早把目录和命名空间设计好，不要让共享区变成一个无结构的大杂烩。

### 18.1 推荐根目录

建议统一挂为：

- `/memory`

再在其下做一级命名空间划分。

### 18.2 推荐一级分层

建议至少划分为：

- `/memory/shared`
- `/memory/users`
- `/memory/agents`
- `/memory/teams`

#### `/memory/shared`

适合全局共享、无明确归属主体的长期记忆：

- 产品术语表
- 常见问题总结
- 公共知识摘要
- 规范、规则、流程说明

#### `/memory/users`

适合按用户沉淀的长期记忆：

- 用户画像
- 用户偏好
- 用户历史总结
- 用户稳定事实

推荐结构：

- `/memory/users/<user_id>/profile.md`
- `/memory/users/<user_id>/preferences.json`
- `/memory/users/<user_id>/summaries/<date>.md`

#### `/memory/agents`

适合按 agent 身份沉淀的长期记忆：

- agent 常用上下文
- agent 的长期任务轨迹
- agent 的执行习惯或阶段性状态

推荐结构：

- `/memory/agents/<agent_id>/profile.md`
- `/memory/agents/<agent_id>/projects/<project_id>.json`
- `/memory/agents/<agent_id>/history/<date>.md`

#### `/memory/teams`

适合团队、项目组、租户级共享记忆：

- 项目背景
- 协作约定
- 团队级共享知识
- 环境说明

推荐结构：

- `/memory/teams/<team_id>/context.md`
- `/memory/teams/<team_id>/policies.json`
- `/memory/teams/<team_id>/projects/<project_id>/summary.md`

### 18.3 文件命名建议

建议遵守以下规则：

1. 路径稳定，避免频繁改名
2. 优先语义化命名，而不是随机 UUID 命名
3. 长期记忆优先使用可读文本格式：
   - `.md`
   - `.json`
   - `.yaml`
4. 如果需要机器消费和人工审阅兼容：
   - 用 `.json` 存结构化事实
   - 用 `.md` 存摘要和解释

### 18.4 推荐内容分层

同一个主体下，不建议把所有内容都放在一个文件里。建议分成：

- `profile.*`
- `preferences.*`
- `history/`
- `projects/`
- `summaries/`
- `facts/`

例如：

```text
/memory/users/user-42/
  profile.md
  preferences.json
  facts/
    locale.json
    product_focus.json
  summaries/
    2026-04-07.md
    2026-04-08.md
```

这样做的好处是：

- 可以按类别做发布策略
- 可以控制哪些内容允许覆盖、哪些只能追加
- 后续做检索、索引、清理都会更简单

---

## 19. `publish_memory` 的落地建议

如果后续真的实现 `publish_memory`，建议至少包含以下字段：

```python
publish_memory(
    session_id: str,
    source_path: str,
    target_namespace: str,
    target_key: str,
    content_type: str | None = None,
    overwrite: bool = False,
    metadata: dict[str, Any] | None = None,
)
```

### 19.1 字段建议

#### `session_id`

说明从哪个 session 读取源内容。

#### `source_path`

当前 session 中要发布的源文件路径，例如：

- `/workspace/summary.md`
- `/workspace/facts/user.json`

#### `target_namespace`

限定可写入的共享空间，例如：

- `shared`
- `users`
- `agents`
- `teams`

不要让调用方直接自由拼接根路径，避免绕过命名空间约束。

#### `target_key`

namespace 下的相对路径，例如：

- `user-42/summary.md`
- `researcher/project-x/history/2026-04-07.md`

#### `overwrite`

控制是否允许覆盖已有共享记忆。

建议默认 `False`，防止误覆盖。

#### `metadata`

可以附带：

- 来源 session
- 来源 agent
- 来源 user
- 发布时间
- 内容摘要
- 标签

便于后续审计、检索与治理。

### 19.2 实现边界建议

`publish_memory` 最好不要直接复用普通 `write` 工具逻辑，而应当单独实现一个发布服务层，负责：

- 读取 session 内容
- 校验路径
- 映射 namespace -> backend
- 写入共享源
- 生成 metadata
- 返回 canonical shared path / URI

这样可以把“普通工作写入”和“共享记忆发布”严格分离。

---

## 20. 推荐的下一步

如果后续要把这套方案继续落地，建议按这个顺序推进：

1. 先固定 `/memory` 命名空间设计
2. 再确定共享 backend：
   - 本地目录
   - S3 / MinIO
3. 再实现 `publish_memory`
4. 最后再考虑是否需要：
   - publish 审核
   - 版本控制
   - 冲突策略
   - 索引 / 检索能力

不要一开始就尝试让普通 `write/edit/remove/patch` 直接可写 lower。

那会把当前清晰的 session overlay 架构打乱。
