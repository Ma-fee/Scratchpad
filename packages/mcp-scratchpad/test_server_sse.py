#!/usr/bin/env python3
"""
测试脚本 - 用于调试 main_sse() 函数
解决相对导入问题
"""

import sys
from pathlib import Path

# 添加 src 目录到 Python 路径
# 这样可以正确导入 mcp_scratchpad 包
project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

# 现在可以导入 server 模块
from mcp_scratchpad.server import create_server, main_sse, setup_logging  # noqa: F401


def test_create_server():
    """测试创建服务器实例"""
    print("=" * 60)
    print("测试 1: 创建服务器实例")
    print("=" * 60)

    try:
        # 设置日志
        setup_logging()

        # 创建临时测试目录
        test_base_dir = project_root / "test_data"
        test_base_dir.mkdir(exist_ok=True)

        # 创建服务器
        mcp = create_server(base_dir=test_base_dir)

        print("✓ 服务器创建成功")
        print(f"  - 服务器名称: {mcp.name}")
        print(f"  - 基础目录: {test_base_dir}")
        print(f"  - 服务器类型: {type(mcp).__name__}")

        return mcp

    except Exception as e:
        print(f"✗ 创建服务器失败: {e}")
        import traceback

        traceback.print_exc()
        return None


def test_main_sse():
    """测试 main_sse() 函数"""
    print("\n" + "=" * 60)
    print("测试 2: 运行 main_sse()")
    print("=" * 60)
    print("注意: 此函数会启动 SSE 服务器，需要手动停止 (Ctrl+C)")
    print("服务器将在 http://0.0.0.0:8891 上运行")
    print()

    try:
        # 设置临时测试目录
        test_base_dir = project_root / "test_data"
        test_base_dir.mkdir(exist_ok=True)

        # 修改 sys.argv 以使用测试目录
        sys.argv = [
            sys.argv[0],
            "--transport",
            "sse",
            "--host",
            "0.0.0.0",
            "--port",
            "8891",
            "--base-dir",
            str(test_base_dir),
        ]

        print(f"启动参数: {' '.join(sys.argv)}")
        print(f"测试目录: {test_base_dir}")
        print("\n正在启动服务器...")
        print("-" * 60)

        # 运行 main_sse
        main_sse()

    except KeyboardInterrupt:
        print("\n\n服务器已停止")
    except Exception as e:
        print(f"\n✗ 运行失败: {e}")
        import traceback

        traceback.print_exc()


def test_imports():
    """测试所有导入是否正常"""
    print("=" * 60)
    print("测试 0: 验证导入")
    print("=" * 60)

    try:
        from mcp_scratchpad.config import config  # noqa: F401
        from mcp_scratchpad.server import (  # noqa: F401
            create_server,
            main_sse,
            setup_logging,
        )
        from mcp_scratchpad.storage import (  # noqa: F401
            FileSystemStore,
            set_store,
        )
        from mcp_scratchpad.tools.file_tools import (  # noqa: F401
            register_file_tools,
        )
        from mcp_scratchpad.tools.health_tools import (  # noqa: F401
            register_health_tools,
        )

        print("✓ 所有导入成功")
        print(f"  - 配置基础目录: {config.base_dir}")
        print(f"  - 配置传输方式: {config.transport}")
        print(f"  - 配置主机: {config.host}")
        print(f"  - 配置端口: {config.port}")
        return True

    except ImportError as e:
        print(f"✗ 导入失败: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("MCP Scratchpad SSE 服务器测试脚本")
    print("=" * 60)
    print(f"项目根目录: {project_root}")
    print(f"源代码路径: {src_path}")
    print(f"Python 路径: {sys.path[:3]}")
    print()

    # 测试导入
    if not test_imports():
        print("\n导入测试失败，请检查 Python 路径配置")
        sys.exit(1)

    # 测试创建服务器
    mcp = test_create_server()

    if mcp:
        print("\n" + "=" * 60)
        print("测试选项:")
        print("=" * 60)
        print("1. 仅测试服务器创建 (已完成)")
        print("2. 启动 SSE 服务器进行完整测试")
        print()

        choice = input("是否启动 SSE 服务器? (y/n): ").strip().lower()

        if choice == "y" or choice == "yes":
            test_main_sse()
        else:
            print("\n测试完成")
    else:
        print("\n服务器创建失败，跳过 SSE 测试")
