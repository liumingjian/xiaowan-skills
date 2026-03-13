#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    name: str
    description: str
    keywords: tuple[str, ...]
    categories: tuple[str, ...]
    layout: str
    window_days: int


PRESETS: dict[str, Preset] = {
    "xinc": Preset(
        name="xinc",
        description="信创招标日报",
        keywords=("信创", "国产化", "自主可控", "操作系统", "数据库", "中间件", "云平台"),
        categories=("招标", "中标"),
        layout="hybrid",
        window_days=3,
    ),
    "hardware": Preset(
        name="hardware",
        description="硬件维保日报",
        keywords=("维保", "服务器", "存储", "网络设备", "UPS", "硬件", "机房"),
        categories=("招标", "中标"),
        layout="table",
        window_days=3,
    ),
    "software": Preset(
        name="software",
        description="软件采购日报",
        keywords=("软件", "许可", "License", "OA", "ERP", "CRM", "办公软件"),
        categories=("招标", "中标"),
        layout="table",
        window_days=3,
    ),
    "engineering": Preset(
        name="engineering",
        description="工程基建日报",
        keywords=("工程", "施工", "基建", "装修", "弱电", "综合布线"),
        categories=("招标", "中标"),
        layout="hybrid",
        window_days=5,
    ),
}

# Preset aliases for alternative names
PRESET_ALIASES: dict[str, str] = {
    "it-xinc": "xinc",
    "hardware-device": "hardware",
    "software-purchase": "software",
}


def get_preset(name: str) -> Preset:
    # Resolve alias to actual preset name
    resolved_name = PRESET_ALIASES.get(name, name)

    if resolved_name not in PRESETS:
        available = ", ".join(PRESETS.keys())
        raise ValueError(f"未知预设: {name}。可用预设: {available}")
    return PRESETS[resolved_name]


def list_presets() -> list[Preset]:
    return list(PRESETS.values())
