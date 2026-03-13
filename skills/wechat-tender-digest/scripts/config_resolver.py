#!/usr/bin/env python3
from __future__ import annotations

import argparse
from typing import Tuple

from friendly_setup import parse_csv, resolve_job_path
from init_workspace import get_workspace_dir
from job_config import EmailSection, FilterSection, JobConfig, JobSection, OutputSection, SourceSection, load_job_config
from presets import get_preset
from visible_fields import VisibleFieldOptions, resolve_visible_fields


DEFAULT_ACCOUNTS = ("七小服", "天下观查", "银标Daily", "A信创圈俱乐部")
DEFAULT_KEYWORDS = (
    "信创",
    "国产化",
    "自主可控",
    "操作系统",
    "数据库",
    "中间件",
    "云平台",
    "服务器",
    "存储",
    "网络设备",
    "软件",
    "硬件",
)
DEFAULT_CATEGORIES = ("招标", "中标")
DEFAULT_LAYOUT = "hybrid"
DEFAULT_WINDOW_DAYS = 3
DEFAULT_REPORT_FILENAME = "daily-bid-report.html"


def resolve_config(args: argparse.Namespace) -> JobConfig:
    if args.job:
        return apply_cli_overrides(load_job_config(args.job), args)
    if args.preset:
        return build_config_from_preset(args)
    job_path = resolve_job_path(None)
    if job_path:
        return apply_cli_overrides(load_job_config(str(job_path)), args)
    if args.accounts or args.keywords or args.to:
        return build_config_from_cli(args)
    raise ValueError(
        "未找到任务配置。请使用以下方式之一：\n"
        "  --job <path>        指定 YAML 配置文件\n"
        "  --preset <name>     使用预设 (xinc, hardware, software, engineering)\n"
        "  --accounts <names>  直接指定公众号（使用默认配置）\n"
        "  --create-job        创建默认配置文件"
    )


def build_config_from_preset(args: argparse.Namespace) -> JobConfig:
    preset = get_preset(args.preset)
    accounts = parse_csv(args.accounts) if args.accounts else ()
    if not accounts:
        raise ValueError("使用预设时必须通过 --accounts 指定公众号名称")

    recipients = parse_csv(args.to) if args.to else ()
    keywords = tuple(parse_csv(args.keywords)) if args.keywords else preset.keywords
    categories = tuple(parse_csv(args.categories)) if args.categories else preset.categories
    window_days = int(args.window_days) if args.window_days else preset.window_days
    layout = args.layout or preset.layout
    visible_fields = resolve_visible_fields(
        VisibleFieldOptions(
            field_set=getattr(args, "field_set", None),
            visible_fields_csv=getattr(args, "visible_fields", None),
        )
    )

    root_dir = str(get_workspace_dir())
    report_filename = f"{preset.name}-report.html"

    return JobConfig(
        job=JobSection(name=f"{preset.name}-digest", description=preset.description, window_days=window_days),
        source=SourceSection(accounts=accounts, limit_per_account=10),
        filters=FilterSection(keywords=keywords, categories=categories, sort_by="publish_date_desc"),
        output=OutputSection(root_dir=root_dir, keep_raw=True, keep_parsed=True, keep_report=True, report_filename=report_filename),
        email=EmailSection(
            enabled=bool(recipients),
            send_on_empty=False,
            layout=layout,
            subject=f"{preset.description} - 每日汇总",
            to=recipients,
            visible_fields=visible_fields,
        ),
    )


def build_config_from_cli(args: argparse.Namespace) -> JobConfig:
    prefs = _load_default_preferences()
    accounts = _resolve_default_accounts(args, prefs)
    keywords = _resolve_default_keywords(args, prefs)
    categories = tuple(parse_csv(args.categories)) if args.categories else DEFAULT_CATEGORIES
    window_days = int(args.window_days) if args.window_days else int(prefs.get("default_window_days", str(DEFAULT_WINDOW_DAYS)))
    recipients = parse_csv(args.to) if args.to else ()
    layout = args.layout or prefs.get("default_layout", DEFAULT_LAYOUT)
    visible_fields = resolve_visible_fields(
        VisibleFieldOptions(
            field_set=getattr(args, "field_set", None),
            visible_fields_csv=getattr(args, "visible_fields", None),
        )
    )

    return JobConfig(
        job=JobSection(name="default-digest", description="招投标信息日报", window_days=window_days),
        source=SourceSection(accounts=accounts, limit_per_account=10),
        filters=FilterSection(keywords=keywords, categories=categories, sort_by="publish_date_desc"),
        output=OutputSection(
            root_dir=str(get_workspace_dir()),
            keep_raw=True,
            keep_parsed=True,
            keep_report=True,
            report_filename=DEFAULT_REPORT_FILENAME,
        ),
        email=EmailSection(
            enabled=bool(recipients),
            send_on_empty=False,
            layout=layout,
            subject="招投标信息日报",
            to=recipients,
            visible_fields=visible_fields,
        ),
    )


def apply_cli_overrides(config: JobConfig, args: argparse.Namespace) -> JobConfig:
    accounts = parse_csv(args.accounts) if args.accounts else config.source.accounts
    keywords = tuple(parse_csv(args.keywords)) if args.keywords else config.filters.keywords
    categories = tuple(parse_csv(args.categories)) if args.categories else config.filters.categories
    window_days = int(args.window_days) if args.window_days else config.job.window_days
    recipients, email_enabled = _resolve_email_overrides(config, args)
    layout = args.layout or config.email.layout
    visible_fields = _resolve_visible_fields_overrides(config, args)

    source = SourceSection(accounts=accounts, limit_per_account=config.source.limit_per_account)
    filters = FilterSection(keywords=keywords, categories=categories, sort_by=config.filters.sort_by)
    job = JobSection(name=config.job.name, description=config.job.description, window_days=window_days)
    email = EmailSection(
        enabled=email_enabled,
        send_on_empty=config.email.send_on_empty,
        layout=layout,
        subject=config.email.subject,
        to=recipients,
        visible_fields=visible_fields,
    )
    return JobConfig(job=job, source=source, filters=filters, output=config.output, email=email)


def _resolve_visible_fields_overrides(config: JobConfig, args: argparse.Namespace) -> Tuple[str, ...]:
    if getattr(args, "visible_fields", None) or getattr(args, "field_set", None):
        return resolve_visible_fields(
            VisibleFieldOptions(
                field_set=getattr(args, "field_set", None),
                visible_fields_csv=getattr(args, "visible_fields", None),
            )
        )
    return config.email.visible_fields


def _resolve_email_overrides(config: JobConfig, args: argparse.Namespace) -> Tuple[Tuple[str, ...], bool]:
    if not args.to:
        return config.email.to, config.email.enabled
    recipients = parse_csv(args.to)
    return recipients, bool(recipients)


def _load_default_preferences() -> dict:
    try:
        from preferences import get_default_preferences
        return get_default_preferences()
    except Exception:
        return {}


def _resolve_default_accounts(args: argparse.Namespace, prefs: dict) -> Tuple[str, ...]:
    if args.accounts:
        return parse_csv(args.accounts)
    default_accounts_str = str(prefs.get("default_accounts", "")).strip()
    if default_accounts_str:
        return tuple(a.strip() for a in default_accounts_str.split(",") if a.strip())
    return DEFAULT_ACCOUNTS


def _resolve_default_keywords(args: argparse.Namespace, prefs: dict) -> Tuple[str, ...]:
    if args.keywords:
        return tuple(parse_csv(args.keywords))
    default_keywords_str = str(prefs.get("default_keywords", "")).strip()
    if default_keywords_str:
        return tuple(k.strip() for k in default_keywords_str.split(",") if k.strip())
    return DEFAULT_KEYWORDS
