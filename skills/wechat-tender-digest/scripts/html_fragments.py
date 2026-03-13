#!/usr/bin/env python3
from __future__ import annotations

from bid_parser import AWARD, TENDER, BidRecord
from html_assets import (
    COLOR_BORDER,
    COLOR_CTA,
    COLOR_MUTED,
    COLOR_MUTED_2,
    COLOR_PANEL_BG,
    COLOR_PRIMARY,
    COLOR_PRIMARY_SOFT,
    COLOR_TEXT,
    FIELD_CHINESE,
    FONT_STACK,
    RADIUS_CARD,
    RADIUS_PANEL,
)


PANEL_STYLE = f"width:100%;background:{COLOR_PANEL_BG};border:1px solid {COLOR_BORDER};border-radius:{RADIUS_PANEL};"
CARD_STYLE = f"width:100%;background:{COLOR_PANEL_BG};border:1px solid {COLOR_BORDER};border-radius:{RADIUS_CARD};"
CTA_LINK_STYLE = (
    f"display:inline-block;padding:8px 12px;background:{COLOR_PRIMARY};"
    f"color:#ffffff;text-decoration:none;border-radius:10px;font-size:12px;line-height:16px;font-weight:700;"
)


def render_hero(
    job_title: str,
    summary: str,
    records: list[BidRecord],
    *,
    tender_records: list[BidRecord],
    award_records: list[BidRecord],
    badge_label: str,
) -> str:
    stats = (("有效项目总数", len(records)), ("招标信息", len(tender_records)), ("中标信息", len(award_records)))
    cells = []
    for label, value in stats:
        cells.append(
            f"""
            <td class="m-stack m-stat" style="width:33.33%;padding:0 6px 12px 6px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="{CARD_STYLE}">
                <tr><td style="padding:18px 16px;">
                  <div style="font-family:{FONT_STACK};font-size:26px;line-height:30px;font-weight:800;color:{COLOR_TEXT};">{value}</div>
                  <div style="padding-top:6px;font-family:{FONT_STACK};font-size:12px;line-height:18px;color:{COLOR_MUTED};">{label}</div>
                </td></tr>
              </table>
            </td>
            """
        )
    return f"""
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="{PANEL_STYLE}">
      <tr><td class="m-px" style="padding:22px 22px 8px 22px;">
        <span style="display:inline-block;padding:6px 12px;border-radius:999px;background:{COLOR_PRIMARY_SOFT};color:{COLOR_PRIMARY};font-family:{FONT_STACK};font-size:12px;line-height:18px;font-weight:800;">{badge_label}</span>
      </td></tr>
      <tr><td class="m-px m-title" style="padding:0 22px 8px 22px;font-family:{FONT_STACK};font-size:28px;line-height:36px;font-weight:800;color:{COLOR_TEXT};word-break:break-word;">{job_title}</td></tr>
      <tr><td class="m-px" style="padding:0 22px 16px 22px;font-family:{FONT_STACK};font-size:13px;line-height:22px;color:{COLOR_MUTED};word-break:break-word;">{summary}</td></tr>
      <tr><td style="padding:0 16px 10px 16px;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr>{''.join(cells)}</tr></table></td></tr>
    </table>
    """


def render_hybrid_section(
    title: str,
    records: list[BidRecord],
    *,
    note: str,
    fields: tuple[str, ...],
    keywords: tuple[str, ...],
) -> str:
    cards = "".join(render_record(record, fields) for record in records) or render_empty_state(title, keywords)
    return f"""
    <tr>
      <td style="padding-top:18px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="{PANEL_STYLE}">
          <tr><td class="m-px" style="padding:20px 20px 6px 20px;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr><td style="font-family:{FONT_STACK};font-size:20px;line-height:28px;font-weight:800;color:{COLOR_TEXT};">{title}信息</td><td align="right" style="font-family:{FONT_STACK};font-size:12px;line-height:18px;color:{COLOR_MUTED};">{len(records)} 条</td></tr></table></td></tr>
          <tr><td style="padding:8px 20px 6px 20px;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">{cards}</table></td></tr>
          <tr><td class="m-px" style="padding:0 20px 20px 20px;font-family:{FONT_STACK};font-size:12px;line-height:18px;color:{COLOR_MUTED_2};">{note}</td></tr>
        </table>
      </td>
    </tr>
    """


def render_card_section(title: str, records: list[BidRecord], *, fields: tuple[str, ...], keywords: tuple[str, ...]) -> str:
    cards = "".join(render_record(record, fields) for record in records) or render_empty_state(title, keywords)
    return f"""
    <tr>
      <td style="padding-top:18px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr><td style="padding:0 4px 12px 4px;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr><td style="font-family:{FONT_STACK};font-size:20px;line-height:28px;font-weight:800;color:{COLOR_TEXT};">{title}信息</td><td align="right" style="font-family:{FONT_STACK};font-size:12px;line-height:18px;color:{COLOR_MUTED};">{len(records)} 条</td></tr></table></td></tr>
          <tr><td><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">{cards}</table></td></tr>
        </table>
      </td>
    </tr>
    """


def render_table_section(title: str, records: list[BidRecord], *, fields: tuple[str, ...], keywords: tuple[str, ...]) -> str:
    rows = "".join(render_table_record_row(record, fields) for record in records)
    content = (
        render_empty_state(title, keywords)
        if not rows
        else f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;table-layout:fixed;border-collapse:collapse;">{render_table_header(title, fields)}<tbody>{rows}</tbody></table>'
    )
    return f"""
    <tr>
      <td style="padding-top:18px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="{PANEL_STYLE}">
          <tr><td class="m-px" style="padding:20px 20px 12px 20px;font-family:{FONT_STACK};font-size:20px;line-height:28px;font-weight:800;color:{COLOR_TEXT};">{title}信息</td></tr>
          <tr><td style="padding:0 20px 20px 20px;">{content}</td></tr>
        </table>
      </td>
    </tr>
    """


def render_table_header(title: str, fields: tuple[str, ...]) -> str:
    headers = []
    for field in fields:
        if field == "winner" and title != AWARD:
            continue
        label = FIELD_CHINESE.get(field, field)
        if field == "amount":
            label = "中标金额" if title == AWARD else "预算"
        headers.append(
            f'<th style="background:{COLOR_PRIMARY_SOFT};color:{COLOR_PRIMARY};font-family:{FONT_STACK};font-size:12px;line-height:18px;text-align:left;padding:10px 12px;border-bottom:1px solid {COLOR_BORDER};vertical-align:top;word-break:break-word;">{label}</th>'
        )
    return f"<thead><tr>{''.join(headers)}</tr></thead>"


def render_table_record_row(record: BidRecord, fields: tuple[str, ...]) -> str:
    cells = []
    for field in fields:
        if field == "winner" and record.category != AWARD:
            continue
        value = getattr(record, field, "")
        if field == "source_url":
            value = f'<a href=\"{record.source_url}\" style=\"{CTA_LINK_STYLE}\">查看原文</a>'
        cells.append(
            f'<td style="font-family:{FONT_STACK};font-size:13px;line-height:20px;color:{COLOR_TEXT};padding:10px 12px;border-bottom:1px solid {COLOR_BORDER};vertical-align:top;word-break:break-word;">{value}</td>'
        )
    return "<tr>" + "".join(cells) + "</tr>"


def render_record(record: BidRecord, fields: tuple[str, ...]) -> str:
    badge_bg = COLOR_PRIMARY_SOFT if record.category == TENDER else "#FFF7ED"
    badge_fg = COLOR_PRIMARY if record.category == TENDER else COLOR_CTA
    rows_html = ""
    for field in fields:
        if field == "project_name":
            continue
        if field == "winner" and record.category != AWARD:
            continue
        label = FIELD_CHINESE.get(field, field)
        if field == "amount":
            label = "预算" if record.category == TENDER else "中标金额"
        value = getattr(record, field, "")
        if field == "source_url":
            value = f'<a href=\"{record.source_url}\" style=\"{CTA_LINK_STYLE}\">查看原文</a>'
        rows_html += row(label, value)
    return f"""
    <tr>
      <td style="padding:0 0 14px 0;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="{CARD_STYLE}">
          <tr><td style="padding:18px 18px 10px 18px;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr><td style="font-family:{FONT_STACK};font-size:17px;line-height:26px;font-weight:800;color:{COLOR_TEXT};word-break:break-word;">{record.project_name}</td><td align="right" style="padding-left:12px;vertical-align:top;"><span style="display:inline-block;padding:6px 12px;border-radius:999px;background:{badge_bg};color:{badge_fg};font-family:{FONT_STACK};font-size:12px;line-height:18px;font-weight:800;">{record.category}</span></td></tr></table></td></tr>
          <tr><td style="padding:0 18px 18px 18px;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="border:1px solid {COLOR_BORDER};border-radius:14px;border-collapse:collapse;">{rows_html}</table></td></tr>
        </table>
      </td>
    </tr>
    """


def render_empty_state(title: str, keywords: tuple[str, ...]) -> str:
    keyword_text = "、".join(keywords) if keywords else "（无关键词）"
    return f"""
    <tr>
      <td>
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="{CARD_STYLE}">
          <tr><td style="padding:22px 18px;">
            <div style="font-family:{FONT_STACK};font-size:14px;line-height:22px;color:{COLOR_MUTED};font-weight:800;">未检索到{title}分类信息</div>
            <div style="padding-top:8px;font-family:{FONT_STACK};font-size:12px;line-height:18px;color:{COLOR_MUTED_2};">当前关键词：{keyword_text}</div>
            <div style="padding-top:4px;font-family:{FONT_STACK};font-size:12px;line-height:18px;color:{COLOR_MUTED_2};">建议：尝试扩大关键词范围或增加回溯天数</div>
          </td></tr>
        </table>
      </td>
    </tr>
    """


def row(label: str, value: str) -> str:
    return (
        "<tr>"
        f'<td style="width:116px;padding:10px 12px;border-bottom:1px solid {COLOR_BORDER};font-family:{FONT_STACK};font-size:12px;line-height:18px;color:{COLOR_MUTED};vertical-align:top;">{label}</td>'
        f'<td style="padding:10px 12px;border-bottom:1px solid {COLOR_BORDER};font-family:{FONT_STACK};font-size:13px;line-height:20px;color:{COLOR_TEXT};vertical-align:top;word-break:break-word;">{value}</td>'
        "</tr>"
    )
