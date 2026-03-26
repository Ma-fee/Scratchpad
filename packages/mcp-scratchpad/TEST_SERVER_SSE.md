# SSE 服务器测试脚本使用说明

## 概述

`test_server_sse.py` 是一个用于调试和测试 `main_sse()` 函数的独立测试脚本。它解决了直接运行 `server.py` 时可能出现的相对导入问题。

## 文件位置

```
packages/mcp-scratchpad/test_server_sse.py
```

## 功能特性

1. **自动配置 Python 路径**：自动将 `src` 目录添加到 Python 路径，解决相对导入问题
2. **导入验证**：测试所有必要的模块导入是否正常
3. **服务器创建测试**：验证服务器实例是否能够正确创建
4. **SSE 服务器运行**：支持启动完整的 SSE 服务器进行集成测试

## 使用方法

### 方法 1: 直接运行测试脚本

```bash
cd packages/mcp-scratchpad
python test_server_sse.py
```

### 方法 2: 使用 Python 模块方式运行

```bash
cd packages/mcp-scratchpad
python -m test_server_sse
```

### 方法 3: 添加执行权限后运行

```bash
chmod +x packages/mcp-scratchpad/test_server_sse.py
./packages/mcp-scratchpad/test_server_sse.py
```

## 测试流程

脚本会按顺序执行以下测试：

### 测试 0: 验证导入
- 检查所有必要的模块是否能够正确导入
- 显示配置信息（基础目录、传输方式、主机、端口等）

### 测试 1: 创建服务器实例
- 创建 FastMCP 服务器实例
- 使用临时测试目录（`test_data/`）
- 显示服务器基本信息

### 测试 2: 运行 main_sse()（可选）
- 启动 SSE 服务器
- 在 `http://0.0.0.0:8891` 上运行
- 需要手动停止（Ctrl+C）

## 输出示例

```
============================================================
MCP Scratchpad SSE 服务器测试脚本
============================================================
项目根目录: /path/to/packages/mcp-scratchpad
源代码路径: /path/to/packages/mcp-scratchpad/src
Python 路径: ['/path/to/packages/mcp-scratchpad/src', ...]

============================================================
测试 0: 验证导入
============================================================
✓ 所有导入成功
  - 配置基础目录: /path/to/files
  - 配置传输方式: stdio
  - 配置主机: 0.0.0.0
  - 配置端口: 8891

============================================================
测试 1: 创建服务器实例
============================================================
✓ 服务器创建成功
  - 服务器名称: MCP Scratchpad
  - 基础目录: /path/to/packages/mcp-scratchpad/test_data
  - 服务器类型: FastMCP

============================================================
测试选项:
============================================================
1. 仅测试服务器创建 (已完成)
2. 启动 SSE 服务器进行完整测试

是否启动 SSE 服务器? (y/n):
```

## 配置选项

脚本使用以下默认配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--transport` | `sse` | 传输方式 |
| `--host` | `0.0.0.0` | 监听地址 |
| `--port` | `8891` | 监听端口 |
| `--base-dir` | `test_data/` | 测试数据目录 |

## 故障排除

### 问题 1: 导入错误

**错误信息**:
```
ModuleNotFoundError: No module named 'mcp_scratchpad'
```

**解决方案**:
- 确保在 `packages/mcp-scratchpad` 目录下运行脚本
- 检查 `src` 目录是否存在

### 问题 2: 端口已被占用

**错误信息**:
```
OSError: [Errno 48] Address already in use
```

**解决方案**:
- 修改脚本中的端口号（第 127 行）
- 或者停止占用 8891 端口的进程：
  ```bash
  lsof -ti:8891 | xargs kill -9
  ```

### 问题 3: 依赖缺失

**错误信息**:
```
ModuleNotFoundError: No module named 'fastmcp'
```

**解决方案**:
- 安装项目依赖：
  ```bash
  cd packages/mcp-scratchpad
  pip install -e .
  ```

## 与直接运行 server.py 的区别

| 特性 | 直接运行 server.py | 使用 test_server_sse.py |
|------|-------------------|------------------------|
| 相对导入问题 | ❌ 可能失败 | ✅ 自动解决 |
| 路径配置 | 需要手动设置 | 自动配置 |
| 测试数据目录 | 使用默认配置 | 使用临时测试目录 |
| 交互式测试 | ❌ 不支持 | ✅ 支持 |
| 导入验证 | ❌ 不支持 | ✅ 支持 |

## 注意事项

1. **测试数据目录**：脚本会在 `test_data/` 目录下创建测试文件，可以安全删除
2. **服务器停止**：SSE 服务器需要使用 `Ctrl+C` 手动停止
3. **端口占用**：确保 8891 端口未被其他服务占用
4. **Python 版本**：需要 Python 3.10 或更高版本

## 扩展使用

### 自定义配置

修改 `test_main_sse()` 函数中的参数：

```python
sys.argv = [
    sys.argv[0],
    "--transport", "sse",
    "--host", "127.0.0.1",  # 修改监听地址
    "--port", "9000",       # 修改端口
    "--base-dir", "/custom/path"  # 修改基础目录
]
```

### 添加更多测试

在脚本中添加新的测试函数：

```python
def test_custom_feature():
    """自定义测试"""
    print("测试自定义功能...")
    # 你的测试代码
```

然后在 `if __name__ == "__main__":` 部分调用它。

## 相关文件

- [`server.py`](src/mcp_scratchpad/server.py) - 主服务器实现
- [`config/settings.py`](src/mcp_scratchpad/config/settings.py) - 配置设置
- [`storage.py`](src/mcp_scratchpad/storage.py) - 存储实现
- [`tools/file_tools.py`](src/mcp_scratchpad/tools/file_tools.py) - 文件工具
