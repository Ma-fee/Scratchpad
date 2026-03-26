from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from fastmcp.tools.tool import ToolResult
from mcp.types import CallToolResult, TextContent


def normalize_path(path: str) -> str:
    """规范化路径，支持绝对路径和相对路径，但禁止目录穿越。"""
    if not path or len(path) > 256:
        raise ValueError("INVALID_FILE_NAME: path is empty or too long")

    # 检查目录穿越攻击（对绝对路径和相对路径都进行检查）
    # 对于绝对路径，我们需要更仔细地处理
    if path.startswith("/"):
        # Unix/Linux 绝对路径
        path_parts = path.split("/")
        if ".." in path_parts:
            raise ValueError("INVALID_FILE_NAME: path traversal not allowed")

        return path.replace("\\", "/").lstrip("/")
    elif re.match(r"^[A-Za-z]:", path):
        # Windows 绝对路径
        path_parts = path.replace("\\", "/").split("/")
        if ".." in path_parts:
            raise ValueError("INVALID_FILE_NAME: path traversal not allowed")
        return path.replace("\\", "/")
    else:
        # 相对路径
        if ".." in path.split("/"):
            raise ValueError("INVALID_FILE_NAME: path traversal not allowed")
        return path.replace("\\", "/")


def mcp_error(code: str, detail: str, suggestion: str | None = None) -> CallToolResult:
    """生成标准 MCP 错误响应，可附带解决建议。"""
    suggestion_text = f"\n建议解决方案: {suggestion}" if suggestion else ""
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=f"错误: {code} {detail}{suggestion_text}",
            )
        ],
        isError=True,
    )


def mcp_text_summary(lines: list[str]) -> str:
    """简单地将多行文本合并，供摘要输出使用。"""
    return "\n".join(lines)


def build_file_block(
    path: str, text: str, start_line: int | None = None, end_line: int | None = None
) -> str:
    """把文件内容包装成 <file> 块，便于前端渲染。"""
    range_attr = ""
    if start_line or end_line:
        start = start_line or 1
        end = end_line or start + text.count("\n")
        range_attr = f' lines="{start}-{end}"'
    return f"<file>\n<path>{path}</path>\n<content{range_attr}>\n{text}\n</content>\n</file>"


def dict_to_xml(data: dict[str, Any], root_tag: str = "result") -> str:
    """将字典转换为纯 XML 格式"""

    def _convert(obj, key):
        if isinstance(obj, dict):
            items = []
            for k, v in obj.items():
                # 清理键名，确保是有效的 XML 标签名
                clean_key = str(k).replace(" ", "_").replace("-", "_")
                if clean_key.isdigit():
                    clean_key = f"item_{clean_key}"
                items.append(_convert(v, clean_key))
            return f"<{key}>{''.join(items)}</{key}>"
        elif isinstance(obj, list):
            items = []
            for _i, item in enumerate(obj):
                # 使用单数形式作为键名
                item_key = key.rstrip("s") if key.endswith("s") else f"{key}_item"
                items.append(_convert(item, item_key))
            return "".join(items)
        elif isinstance(obj, bool):
            return f"<{key}>{str(obj).lower()}</{key}>"
        elif obj is None:
            return f"<{key}></{key}>"
        else:
            # 转义 XML 特殊字符
            escaped = (
                str(obj).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            return f"<{key}>{escaped}</{key}>"

    return f'<?xml version="1.0" encoding="UTF-8"?>\n{_convert(data, root_tag)}'


def build_file_list_xml(
    files: list[dict[str, Any]], metadata: dict[str, Any]
) -> list[str]:
    """
    为每个文件构建独立的 XML 列表片段
    返回 list[str]，每个字符串是一个文件的独立XML内容（不含XML头部）

    Args:
        files: 文件数据列表
        metadata: 元数据

    Returns:
        list[str]: 每个文件的独立 XML 内容片段列表
    """
    xml_contents = []

    # 首先添加元数据作为一个独立的 XML 片段
    metadata_elem = ET.Element("file_list_metadata")
    for key, value in metadata.items():
        elem = ET.SubElement(metadata_elem, key)
        elem.text = str(value)

    metadata_xml = ET.tostring(metadata_elem, encoding="unicode", xml_declaration=False)
    xml_contents.append(metadata_xml)

    # 为每个文件创建独立的 XML 片段
    for file_data in files:
        file_elem = ET.Element("file")

        for key, value in file_data.items():
            elem = ET.SubElement(file_elem, key)
            if isinstance(value, str):
                elem.text = value
            elif isinstance(value, bool):
                elem.text = str(value).lower()
            elif value is not None:
                elem.text = str(value)
            # 如果 value 是 None，不设置 text（保持空元素）

        # 转换为字符串，不包含 XML 声明
        xml_string = ET.tostring(file_elem, encoding="unicode", xml_declaration=False)
        xml_contents.append(xml_string)

    return xml_contents


def build_file_content_xml(
    files: list[dict[str, Any]], metadata: dict[str, Any] | None = None
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
    xml_contents = []

    # 如果有元数据，首先添加元数据作为一个独立的 XML 片段
    # if metadata:
    #     metadata_elem = ET.Element("file_content_metadata")
    #     for key, value in metadata.items():
    #         elem = ET.SubElement(metadata_elem, key)
    #         elem.text = str(value)
    #     metadata_xml = ET.tostring(
    #         metadata_elem, encoding="unicode", xml_declaration=False
    #     )
    #     xml_contents.append(metadata_xml)

    for file_data in files:
        # 为每个文件创建独立的 XML 片段
        file_elem = ET.Element("file")

        # 添加文件的所有属性
        for key, value in file_data.items():
            if key == "content":
                # content 特殊处理，保持原始格式
                content_elem = ET.SubElement(file_elem, "content")
                content_elem.text = str(value) if value is not None else ""
            else:
                elem = ET.SubElement(file_elem, key)
                if isinstance(value, str):
                    elem.text = value
                elif isinstance(value, bool):
                    elem.text = str(value).lower()
                elif value is not None:
                    elem.text = str(value)
                # 如果 value 是 None，不设置 text（保持空元素）

        # 转换为字符串，不包含 XML 声明
        xml_string = ET.tostring(file_elem, encoding="unicode", xml_declaration=False)
        xml_contents.append(xml_string)

    return xml_contents


def build_file_operation_xml(
    operation_data: dict[str, Any], operation_type: str
) -> str:
    """构建文件操作结果的 XML"""
    root = ET.Element(f"{operation_type}_result")

    for key, value in operation_data.items():
        elem = ET.SubElement(root, key)
        elem.text = str(value)

    return ET.tostring(root, encoding="unicode", xml_declaration=False)


def build_error_xml(
    error_message: str, tool_name: str = "", error_code: str = "ERROR"
) -> str:
    """构建错误信息的 XML"""
    root = ET.Element("error")

    # 添加错误代码
    code_elem = ET.SubElement(root, "code")
    code_elem.text = error_code

    # 添加工具名称
    if tool_name:
        tool_elem = ET.SubElement(root, "tool")
        tool_elem.text = tool_name

    # 添加错误消息
    message_elem = ET.SubElement(root, "message")
    message_elem.text = error_message

    return ET.tostring(root, encoding="unicode", xml_declaration=False)


def create_tool_result_xml(
    xml_contents: list[str] | str, structured_data: dict[str, Any] | None = None
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
    # 处理向后兼容性：如果传入单个字符串，转换为列表
    if isinstance(xml_contents, str):
        xml_contents = [xml_contents]

    # 为每个 XML 内容创建独立的 TextContent
    content_list = [
        TextContent(type="text", text=xml_content) for xml_content in xml_contents
    ]

    return ToolResult(content=content_list, structured_content=structured_data or {})
