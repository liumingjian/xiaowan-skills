#!/usr/bin/env python3
"""初始化工作目录结构"""
import os
from pathlib import Path


OUTPUT_DIR = os.environ.get("WECHAT_BID_OUTPUT_DIR", "wechat-bid-digest")


def get_user_config_dir() -> Path:
    """获取用户配置目录，支持XDG标准"""
    xdg_config = os.environ.get("XDG_CONFIG_HOME", "")
    if xdg_config:
        return Path(xdg_config) / "wechat-bid-digest"
    return Path.home() / ".wechat-bid-digest"


USER_CONFIG_DIR = get_user_config_dir()


def init_workspace() -> Path:
    """初始化输出目录（在当前工作目录下）"""
    output_dir = Path.cwd() / OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)
    return output_dir


def init_user_config() -> Path:
    """初始化用户级配置目录"""
    USER_CONFIG_DIR.mkdir(exist_ok=True)
    (USER_CONFIG_DIR / "config").mkdir(exist_ok=True)
    (USER_CONFIG_DIR / "jobs").mkdir(exist_ok=True)
    return USER_CONFIG_DIR


def init_auth_dir() -> Path:
    """初始化认证目录 ~/.wechat-bid-digest/auth/"""
    auth_dir = USER_CONFIG_DIR / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    return auth_dir


def get_workspace_dir() -> Path:
    """获取输出目录路径（当前工作目录下）"""
    return Path.cwd() / OUTPUT_DIR

if __name__ == "__main__":
    workspace = init_workspace()
    print(f"工作目录已初始化: {workspace.absolute()}")
