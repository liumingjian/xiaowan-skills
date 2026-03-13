#!/usr/bin/env python3
"""自动安装skill所需依赖"""
import subprocess
import sys

DEPS = ["requests", "qrcode[pil]", "pyzbar"]

def install_deps():
    print("正在安装 wechat-tender-digest 依赖...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + DEPS)
        print("\n✓ 依赖安装完成！")
        return True
    except subprocess.CalledProcessError:
        print("\n✗ 依赖安装失败，请手动运行：")
        print(f"  pip install {' '.join(DEPS)}")
        return False

if __name__ == "__main__":
    sys.exit(0 if install_deps() else 1)
