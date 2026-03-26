# 工具返回格式重新设计

## 概述

本文档描述了对 `create_tool_result_xml` 和 `build_file_content_xml` 函数的重新设计，以支持多个独立的 XML 内容输出。

## 当前问题

1. `create_tool_result_xml` 只支持单个 `xml_content` 输入
2. `build_file_content_xml` 返回包含 XML 头部的完整 XML 文档
3. 多个文件的内容被合并到一个 XML 结构中，不够灵活

## 新的设计方案

### 1. `create_tool_result_xml` 函数重新设计

#### 新的函数签名

```python
def create_tool_result_xml(
    xml_contents: list[str] | str, 
    structured_data: dict[str, Any] | None = None
) -> ToolResult:
    """
    创建包含一个或多个 XML 内容的 ToolResult
    每个 xml_content 将作为独立的 TextContent 返回
    
    Args:
        xml_contents: XML 内容字符串或字符串列表
        structured_data: 结构化数据（可选）
    
    Returns:
        ToolResult: 包含一个或多个 TextContent 的结果
    """
```

#### 实现逻辑

- 如果传入单个字符串，保持向后兼容，创建单个 TextContent
- 如果传入字符串列表，为每个字符串创建独立的 TextContent
- 所有 TextContent 都包装在一个 ToolResult 中返回

### 2. `build_file_content_xml` 函数重新设计

#### 新的函数签名

```python
def build_file_content_xml(
    files: list[dict[str, Any]], 
    metadata: dict[str, Any] | None = None
) -> list[str]:
    """
    为每个文件构建独立的 XML 内容片段
    返回 list[str]，每个字符串是一个文件的独立XML内容（不含XML头部）
    
    Args:
        files: 文件数据列表
        metadata: 元数据（可选）
    
    Returns:
        list[str]: 每个文件的独立 XML 内容片段列表
    """
```

#### 实现逻辑

- 为每个文件创建独立的 XML 片段
- 不包含 XML 声明头部（`<?xml version="1.0" encoding="UTF-8"?>`）
- 每个文件片段包含完整的文件信息和内容
- 返回字符串列表，每个字符串对应一个文件

### 3. XML 片段格式设计

#### 单个文件的 XML 片段格式

```xml
<file>
    <path>文件路径</path>
    <name>文件名</name>
    <size>文件大小</size>
    <version>版本号</version>
    <permission>权限</permission>
    <persistent>是否持久化</persistent>
    <created_at>创建时间</created_at>
    <updated_at>更新时间</updated_at>
    <content_block>
        文件内容块（如果有）
    </content_block>
</file>
```

## 调用代码更新

### 1. `_read_file_tool` 函数更新

#### 当前实现

```python
# 转换为 XML
xml_content = build_file_content_xml(structured_files, metadata)

# 创建并返回 ToolResult
return create_tool_result_xml(
    xml_content=xml_content,
    structured_data=metadata
)
```

#### 新的实现

```python
# 为每个文件生成独立的 XML 片段
xml_contents = build_file_content_xml(structured_files, metadata)

# 创建并返回 ToolResult，每个文件作为独立的 TextContent
return create_tool_result_xml(
    xml_contents=xml_contents,
    structured_data=metadata
)
```

### 2. 其他调用点的更新

所有使用这两个函数的地方都需要相应更新：

- `_list_files_tool` - 保持现有实现（因为不涉及多文件内容）
- `_write_file_tool` - 保持现有实现（单个文件操作）
- `_remove_file_tool` - 保持现有实现（单个文件操作）
- 异常处理函数 - 保持现有实现（错误信息通常是单个）

## 向后兼容性

### `create_tool_result_xml` 向后兼容

- 继续支持传入单个字符串参数
- 现有的单内容调用无需修改

### `build_file_content_xml` 破坏性变更

- 返回类型从 `str` 改为 `list[str]`
- 所有调用点都需要更新

## 实施步骤

1. 修改 `create_tool_result_xml` 函数实现
2. 修改 `build_file_content_xml` 函数实现
3. 更新 `_read_file_tool` 中的调用代码
4. 更新其他相关调用代码（如果需要）
5. 测试验证功能正常工作

## 预期效果

1. 多个文件读取时，每个文件内容作为独立的 TextContent 返回
2. 更好的内容组织和展示
3. 保持向后兼容性
4. 更灵活的 XML 内容处理

## 风险评估

1. **向后兼容性风险**：`build_file_content_xml` 返回类型变更可能影响现有代码
2. **测试覆盖**：需要确保所有场景都被正确测试
3. **性能影响**：多个 TextContent 可能略微增加内存使用

## 缓解措施

1. 逐步实施，先修改函数实现，再更新调用点
2. 保持 `create_tool_result_xml` 的向后兼容性
3. 充分测试各种场景
