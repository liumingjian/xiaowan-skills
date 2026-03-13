#!/usr/bin/env python3
from __future__ import annotations


FONT_STACK = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, "
    "'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif"
)

# Color system (optimized for email clients: high-contrast, light background)
COLOR_TEXT = "#0F172A"
COLOR_MUTED = "#475569"
COLOR_MUTED_2 = "#64748B"
COLOR_BORDER = "#DCE7F1"
COLOR_PANEL_BG = "#FFFFFF"
COLOR_BG = "#F0F9FF"

COLOR_PRIMARY = "#0369A1"
COLOR_PRIMARY_SOFT = "#DFF4FB"
COLOR_CTA = "#F97316"

RADIUS_PANEL = "18px"
RADIUS_CARD = "16px"

ALL_FIELDS = (
    "project_id",
    "project_name",
    "amount",
    "procurer",
    "winner",
    "publish_date",
    "deadline",
    "source_name",
    "source_url",
)

FIELD_CHINESE = {
    "project_id": "项目编号",
    "project_name": "项目名",
    "amount": "金额",
    "procurer": "招标单位",
    "winner": "中标单位（第一中标人）",
    "publish_date": "发布时间",
    "deadline": "截止时间",
    "source_name": "来源渠道",
    "source_url": "来源地址",
}

COMMON_CSS = """
    body { margin: 0; padding: 0; }
    table { border-collapse: collapse; }
    img { border: 0; outline: none; text-decoration: none; }
    a { color: inherit; }
    @media screen and (max-width: 640px) {
      .m-stack { display: block !important; width: 100% !important; }
      .m-center { text-align: center !important; }
      .m-px { padding-left: 16px !important; padding-right: 16px !important; }
      .m-title { font-size: 24px !important; line-height: 32px !important; }
      .m-stat { padding: 0 0 12px 0 !important; }
    }
"""

TABLE_CSS = """
    /* Table layout tweaks (optional; base styles are inline for email clients). */
"""

HYBRID_CSS = """
    /* Hybrid layout specific tweaks (optional). */
"""

CARD_CSS = """
    /* Card layout specific tweaks (optional). */
"""
