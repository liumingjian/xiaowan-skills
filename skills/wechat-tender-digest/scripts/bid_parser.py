#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


NOT_DISCLOSED = "未披露"
TENDER = "招标"
AWARD = "中标"
FIELD_LABELS = (
    "项目名称",
    "预算金额",
    "预算总金额",
    "采购预算",
    "项目编号",
    "采购编号",
    "招标编号",
    "招标项目编号",
    "采购人",
    "招标人",
    "采购单位",
    "招标单位",
    "中标金额",
    "成交金额",
    "投标报价",
    "中标单位",
    "中标供应商",
    "第一中标人",
    "成交供应商",
    "供应商名称",
    "获取采购文件",
    "获取采购文件时间",
    "投标截止时间",
    "响应文件提交截止时间",
    "开标时间",
    "开标日期",
    "公示期",
    "公示结束时间",
    "合同履行期限",
    "合同履约期限",
    "服务期",
    "维保",
    "项目概述",
    "项目概况",
)
DATE_PATTERN = re.compile(r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?")
GENERIC_LABEL_BOUNDARY = re.compile(r"\s*[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9（）()—\\-、，·]{1,19}\s*[:：]")

TENDER_INDICATORS = ("招标公告", "采购公告", "磋商公告", "询价公告", "竞争性谈判", "招标信息")
AWARD_INDICATORS = ("中标公告", "成交公告", "结果公示", "中标信息", "中标候选人")

CHINESE_ORDINALS = re.compile(r"\n\s*[一二三四五六七八九十]+\s*[、.]\s*\n")
PAREN_ORDINALS = re.compile(r"\n\s*[（(]\s*\d+\s*[）)]\s*\n")
NUMERIC_ORDINALS = re.compile(r"\n+\s*\d+\s*\n+")


@dataclass(frozen=True)
class BidRecord:
    category: str
    project_id: str
    project_name: str
    amount: str
    procurer: str
    winner: str
    publish_date: str
    deadline: str
    source_name: str
    source_url: str


def build_raw_article(article: dict, *, account_name: str, html_content: str, text_content: str) -> dict:
    return {
        "title": str(article.get("title") or "未知标题"),
        "url": str(article.get("url") or article.get("link") or ""),
        "account": account_name,
        "create_time": str(article.get("create_time") or ""),
        "html": html_content,
        "content": text_content,
    }


def collect_records(
    raw_articles: list[dict], keywords: tuple[str, ...], categories: tuple[str, ...], *, sort_by: str
) -> list[BidRecord]:
    records: list[BidRecord] = []
    category_map = {"tender": TENDER, "award": AWARD}
    allowed = {category_map.get(cat, cat) for cat in categories}
    for article in raw_articles:
        content = str(article["content"])
        for block in split_blocks(content):
            record = build_record(article, block)
            if record.category not in allowed:
                continue
            if any(keyword in record.project_name for keyword in keywords):
                records.append(record)
    reverse = sort_by == "publish_date_desc"
    return sorted(records, key=lambda item: (item.publish_date, item.project_name), reverse=reverse)


def records_to_json(records: list[BidRecord], job_name: str, *, from_date: str, to_date: str) -> dict:
    return {
        "job_name": job_name,
        "from_date": from_date,
        "to_date": to_date,
        "record_count": len(records),
        "tender_count": sum(record.category == TENDER for record in records),
        "award_count": sum(record.category == AWARD for record in records),
        "records": [asdict(record) for record in records],
    }


def safe_filename(value: str, max_length: int = 80) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "", value)
    compact = re.sub(r"\s+", "_", cleaned).strip("_.")
    return (compact[:max_length] if len(compact) > max_length else compact) or "untitled"


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_text_from_html(html_content: str) -> str:
    match = re.search(r'<div[^>]+id="js_content"[^>]*>(.*?)</div>', html_content, flags=re.S)
    if not match:
        match = re.search(r'<div[^>]+class="rich_media_content"[^>]*>(.*?)</div>', html_content, flags=re.S)
    content = match.group(1) if match else html_content
    text = re.sub(r"<(script|style|noscript).*?>.*?</\1>", "", content, flags=re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|li|tr|section|blockquote|h[1-6])>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def split_blocks(content: str) -> list[str]:
    trimmed = trim_article_content(content)
    parts = NUMERIC_ORDINALS.split(trimmed)
    if len(parts) <= 1:
        parts = CHINESE_ORDINALS.split(trimmed)
    if len(parts) <= 1:
        parts = PAREN_ORDINALS.split(trimmed)
    return [part.strip() for part in parts if part.strip()]


def trim_article_content(content: str) -> str:
    text = content.replace("\r", "").strip()
    text = re.sub(r"^(招\s*标\s*信\s*息|中\s*标\s*信\s*息)\s*", "", text, count=1)
    return re.split(r"小蝌蚪报告每日中标信息|欢迎扫码关注", text)[0].strip()


def extract_project_name_from_title(title: str) -> str:
    cleaned = re.sub(r"^【[^】]+】", "", title)
    cleaned = re.sub(r"^\d+[\d.,万亿元]+[！!]?", "", cleaned)
    return cleaned.strip() or NOT_DISCLOSED


def build_record(article: dict, block: str) -> BidRecord:
    category = detect_category(str(article["content"]), block)
    amount_labels = ("预算总金额", "预算金额", "采购预算") if category == TENDER else ("中标金额", "成交金额", "投标报价")
    winner_labels = ("中标单位", "中标供应商", "第一中标人", "成交供应商", "供应商名称")
    project_name = find_field(block, ("项目名称",))
    if project_name == NOT_DISCLOSED:
        project_name = extract_project_name_from_title(str(article.get("title", "")))
    return BidRecord(
        category=category,
        project_id=find_field(block, ("项目编号", "采购编号", "招标编号", "招标项目编号")),
        project_name=project_name,
        amount=find_amount(block, amount_labels),
        procurer=find_field(block, ("采购人", "招标人", "采购单位", "招标单位")),
        winner=find_field(block, winner_labels) if category == AWARD else NOT_DISCLOSED,
        publish_date=normalize_publish_date(str(article["create_time"])),
        deadline=extract_deadline(block),
        source_name=str(article["account"]),
        source_url=str(article["url"]),
    )


def detect_category(content: str, block: str) -> str:
    normalized = re.sub(r"\s+", "", content[:80] + block[:80])
    for indicator in AWARD_INDICATORS:
        if indicator in normalized:
            return AWARD
    for indicator in TENDER_INDICATORS:
        if indicator in normalized:
            return TENDER
    return TENDER


def find_field(block: str, labels: tuple[str, ...]) -> str:
    normalized_block = normalize_field_spaces(block)
    current = "|".join(re.escape(label) for label in labels)
    pattern = rf"(?:{current})\s*[:：]\s*(.*)"
    match = re.search(pattern, normalized_block, flags=re.S)
    if not match:
        return NOT_DISCLOSED
    return compact_text(truncate_field_value(match.group(1)))


def truncate_field_value(value: str) -> str:
    candidates = []
    for sep in ("\n", "。", "；", ";"):
        idx = value.find(sep)
        if idx != -1:
            candidates.append(idx)
    label_match = GENERIC_LABEL_BOUNDARY.search(value)
    if label_match:
        candidates.append(label_match.start())
    end = min(candidates) if candidates else len(value)
    return value[:end].strip()


def find_amount(block: str, labels: tuple[str, ...]) -> str:
    normalized_block = normalize_field_spaces(block)
    for label in labels:
        pattern = rf"{re.escape(label)}\s*[:：]?\s*[^0-9¥￥]{{0,12}}([¥￥]?\s*[\d,]+(?:\.\d+)?\s*(?:万元|万|元)?)"
        match = re.search(pattern, normalized_block)
        if match:
            return compact_text(match.group(1))
    return NOT_DISCLOSED


def normalize_field_spaces(block: str) -> str:
    result = block
    for label in FIELD_LABELS:
        spaced = r"\s*".join(re.escape(ch) for ch in label)
        result = re.sub(spaced, label, result)
    return result


def extract_deadline(block: str) -> str:
    priorities = (
        ("投标截止时间",),
        ("响应文件提交截止时间",),
        ("公示结束时间",),
        ("公示期",),
        ("开标时间", "开标日期"),
        ("获取采购文件时间", "获取采购文件"),
    )
    for labels in priorities:
        value = find_field(block, labels)
        if value == NOT_DISCLOSED:
            continue
        dates = DATE_PATTERN.findall(value)
        if not dates:
            return value
        year, month, day = dates[-1]
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return NOT_DISCLOSED


def normalize_publish_date(create_time: str) -> str:
    raw = create_time.strip()
    if raw.isdigit():
        return datetime.fromtimestamp(int(raw)).strftime("%Y-%m-%d")
    return normalize_date(raw) if DATE_PATTERN.search(raw) else raw[:10]


def normalize_date(text: str) -> str:
    match = DATE_PATTERN.search(text)
    if not match:
        return NOT_DISCLOSED
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def compact_text(value: str) -> str:
    flattened = re.sub(r"\s+", " ", value.replace("\u3000", " ")).strip()
    flattened = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", flattened)
    return flattened or NOT_DISCLOSED
