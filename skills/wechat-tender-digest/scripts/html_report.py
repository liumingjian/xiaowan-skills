#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime

from bid_parser import AWARD, TENDER, BidRecord
from html_assets import ALL_FIELDS, CARD_CSS, COLOR_BG, COLOR_MUTED_2, COLOR_TEXT, COMMON_CSS, FONT_STACK, HYBRID_CSS, TABLE_CSS
from html_fragments import render_card_section, render_hero, render_hybrid_section, render_table_section


def build_html(
    job_title: str,
    records: list[BidRecord],
    *,
    from_date: str,
    to_date: str,
    keywords: tuple[str, ...],
    layout: str = "table",
    visible_fields: tuple[str, ...] = (),
) -> str:
    fields = visible_fields if visible_fields else ALL_FIELDS
    summary = (
        f"统计范围：{from_date} 至 {to_date}。排序按发布时间倒序；"
        f"仅保留项目名命中关键词：{' / '.join(keywords)}；字段仅取原文明确披露内容，不做猜测补全。"
    )
    tender_records, award_records = split_records(records)
    if layout == "card":
        return build_card_html(
            job_title,
            summary,
            records,
            from_date=from_date,
            to_date=to_date,
            tender_records=tender_records,
            award_records=award_records,
            fields=fields,
            keywords=keywords,
        )
    if layout == "hybrid":
        return build_hybrid_html(
            job_title,
            summary,
            records,
            from_date=from_date,
            to_date=to_date,
            tender_records=tender_records,
            award_records=award_records,
            fields=fields,
            keywords=keywords,
        )
    return build_table_html(
        job_title,
        summary,
        records,
        from_date=from_date,
        to_date=to_date,
        tender_records=tender_records,
        award_records=award_records,
        fields=fields,
        keywords=keywords,
    )


def split_records(records: list[BidRecord]) -> tuple[list[BidRecord], list[BidRecord]]:
    tender_records = [record for record in records if record.category == TENDER]
    award_records = [record for record in records if record.category == AWARD]
    return tender_records, award_records


def build_page(css_extra: str, bg_color: str, body: str, *, preheader: str, max_width: int = 680) -> str:
    hidden_preheader = (
        f'<div style="display:none;font-size:1px;line-height:1px;max-height:0px;max-width:0px;opacity:0;overflow:hidden;'
        f"mso-hide:all;\">{preheader}</div>"
        if preheader
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="x-ua-compatible" content="IE=edge" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="color-scheme" content="light" />
  <style>{COMMON_CSS}{css_extra}</style>
</head>
<body style="margin:0;padding:0;background:{bg_color};-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
  {hidden_preheader}
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="{bg_color}" style="width:100%;background:{bg_color};">
    <tr><td align="center" style="padding:24px 12px;">
      <!--[if (gte mso 9)|(IE)]>
      <table role="presentation" width="{max_width}" align="center" cellspacing="0" cellpadding="0" border="0">
        <tr><td>
      <![endif]-->
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;max-width:{max_width}px;font-family:{FONT_STACK};color:{COLOR_TEXT};">
{body}
      </table>
      <!--[if (gte mso 9)|(IE)]>
        </td></tr>
      </table>
      <![endif]-->
    </td></tr>
  </table>
  <div style="padding:16px 0 0 0;text-align:center;font-family:{FONT_STACK};font-size:11px;line-height:16px;color:{COLOR_MUTED_2};">
    字段来自原文内容抽取，可能存在遗漏或格式差异，请以原文链接为准。
  </div>
</body>
</html>
"""


def build_hybrid_html(
    job_title: str,
    summary: str,
    records: list[BidRecord],
    *,
    from_date: str,
    to_date: str,
    tender_records: list[BidRecord],
    award_records: list[BidRecord],
    fields: tuple[str, ...],
    keywords: tuple[str, ...],
) -> str:
    tender_note = "截止时间优先取文中明确截止/开标/公示日期；若无，则取获取采购文件区间的截止日。"
    award_note = "若原文未披露第一中标人或中标金额，表格中保留为未披露。"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    hero = render_hero(
        job_title,
        summary,
        records,
        tender_records=tender_records,
        award_records=award_records,
        badge_label="邮件正文版日报",
    )
    tender_section = render_hybrid_section(TENDER, tender_records, note=tender_note, fields=fields, keywords=keywords)
    award_section = render_hybrid_section(AWARD, award_records, note=award_note, fields=fields, keywords=keywords)
    body = f"""        <tr><td>{hero}</td></tr>
	        {tender_section}
	        {award_section}
	        <tr><td align="center" style="padding:16px 8px 0 8px;font-size:12px;line-height:18px;color:#64748b;">生成时间：{now} · 邮件格式：hybrid</td></tr>"""
    preheader = f"{job_title} | {from_date}~{to_date} | 招标{len(tender_records)} 中标{len(award_records)}"
    return build_page(HYBRID_CSS, COLOR_BG, body, preheader=preheader)


def build_table_html(
    job_title: str,
    summary: str,
    records: list[BidRecord],
    *,
    from_date: str,
    to_date: str,
    tender_records: list[BidRecord],
    award_records: list[BidRecord],
    fields: tuple[str, ...],
    keywords: tuple[str, ...],
) -> str:
    body = f"""        <tr><td>{render_hero(job_title, summary, records, tender_records=tender_records, award_records=award_records, badge_label="表格版邮件正文")}</td></tr>
	        {render_table_section(TENDER, tender_records, fields=fields, keywords=keywords)}
	        {render_table_section(AWARD, award_records, fields=fields, keywords=keywords)}
	        <tr><td align="center" style="padding:16px 8px 0 8px;font-size:12px;line-height:18px;color:#64748b;">生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M")} · 邮件格式：table</td></tr>"""
    preheader = f"{job_title} | {from_date}~{to_date} | 招标{len(tender_records)} 中标{len(award_records)}"
    return build_page(TABLE_CSS, COLOR_BG, body, preheader=preheader)


def build_card_html(
    job_title: str,
    summary: str,
    records: list[BidRecord],
    *,
    from_date: str,
    to_date: str,
    tender_records: list[BidRecord],
    award_records: list[BidRecord],
    fields: tuple[str, ...],
    keywords: tuple[str, ...],
) -> str:
    body = f"""        <tr><td>{render_hero(job_title, summary, records, tender_records=tender_records, award_records=award_records, badge_label="卡片版日报")}</td></tr>
	        {render_card_section(TENDER, tender_records, fields=fields, keywords=keywords)}
	        {render_card_section(AWARD, award_records, fields=fields, keywords=keywords)}
	        <tr><td align="center" style="padding:16px 8px 0 8px;font-size:12px;line-height:18px;color:#64748b;">生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M")} · 邮件格式：card</td></tr>"""
    preheader = f"{job_title} | {from_date}~{to_date} | 招标{len(tender_records)} 中标{len(award_records)}"
    return build_page(CARD_CSS, COLOR_BG, body, preheader=preheader)
