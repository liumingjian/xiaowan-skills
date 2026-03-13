#!/usr/bin/env python3
"""初始化工作目录结构"""
import os
from pathlib import Path

from project_paths import ensure_project_app_dirs


OUTPUT_DIR = os.environ.get("WECHAT_BID_OUTPUT_DIR", "wechat-bid-digest")


def init_workspace() -> Path:
    """初始化项目级输出与配置目录。"""
    output_dir = Path.cwd() / OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    ensure_project_app_dirs()
    return output_dir


def get_workspace_dir() -> Path:
    """获取输出目录路径（当前工作目录下）"""
    return Path.cwd() / OUTPUT_DIR


if __name__ == "__main__":
    workspace = init_workspace()
    print(f"工作目录已初始化: {workspace.absolute()}")
