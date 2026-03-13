#!/usr/bin/env python3
"""依赖检测和自动安装"""
import subprocess
import sys


REQUIRED_DEPS = {
    "requests": "requests",
    "PIL": "Pillow",
}


def check_dependency(module_name: str) -> bool:
    """检查单个依赖是否已安装"""
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def install_dependency(package_name: str) -> bool:
    """尝试安装单个依赖"""
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", package_name],
        )
        return True
    except subprocess.CalledProcessError:
        return False


def ensure_dependencies(auto_install: bool = True) -> tuple[bool, list[str]]:
    """确保所有依赖已安装

    Returns:
        (all_installed, missing_deps)
    """
    missing = []

    for module_name, package_name in REQUIRED_DEPS.items():
        if not check_dependency(module_name):
            missing.append(package_name)

    if not missing:
        return True, []

    if auto_install:
        print(f"检测到缺失依赖，正在自动安装: {', '.join(missing)}", file=sys.stderr)
        failed = []
        for pkg in missing:
            if not install_dependency(pkg):
                failed.append(pkg)

        if not failed:
            print("✓ 依赖安装完成", file=sys.stderr)
            return True, []
        else:
            return False, failed

    return False, missing
