#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from yaml_subset import parse_yaml_subset


@dataclass(frozen=True)
class JobSection:
    name: str
    description: str
    window_days: int


@dataclass(frozen=True)
class SourceSection:
    accounts: tuple[str, ...]
    limit_per_account: int


@dataclass(frozen=True)
class FilterSection:
    keywords: tuple[str, ...]
    categories: tuple[str, ...]
    sort_by: str


@dataclass(frozen=True)
class OutputSection:
    root_dir: str
    keep_raw: bool
    keep_parsed: bool
    keep_report: bool
    report_filename: str


@dataclass(frozen=True)
class EmailSection:
    enabled: bool
    send_on_empty: bool
    layout: str
    subject: str
    to: tuple[str, ...]
    visible_fields: tuple[str, ...]


@dataclass(frozen=True)
class JobConfig:
    job: JobSection
    source: SourceSection
    filters: FilterSection
    output: OutputSection
    email: EmailSection


def load_job_config(path: str) -> JobConfig:
    payload = parse_yaml_subset(Path(path).read_text(encoding="utf-8"))
    email_enabled = require_bool(payload, "email.enabled")

    # Backward compatibility: warn about deprecated gateway fields
    _deprecated = ("gateway_mode", "base_url_env", "default_base_url", "base_url",
                    "docker_compose_path", "auto_start_docker")
    source_block = payload.get("source", {})
    if isinstance(source_block, dict):
        for field in _deprecated:
            if field in source_block:
                import sys
                print(f"[deprecation] source.{field} 已废弃，将被忽略。"
                      f"微信文章获取现在直接调用 WeChat MP API。", file=sys.stderr)

    return JobConfig(
        job=JobSection(
            name=require_text(payload, "job.name"),
            description=require_text(payload, "job.description"),
            window_days=require_int(payload, "job.window_days", minimum=1),
        ),
        source=SourceSection(
            accounts=require_text_list(payload, "source.accounts"),
            limit_per_account=require_int(payload, "source.limit_per_account", minimum=1),
        ),
        filters=FilterSection(
            keywords=require_text_list(payload, "filters.keywords"),
            categories=require_text_list(payload, "filters.categories"),
            sort_by=require_choice(payload, "filters.sort_by", ("publish_date_desc", "publish_date_asc")),
        ),
        output=OutputSection(
            root_dir=require_text(payload, "output.root_dir"),
            keep_raw=require_bool(payload, "output.keep_raw"),
            keep_parsed=require_bool(payload, "output.keep_parsed"),
            keep_report=require_bool(payload, "output.keep_report"),
            report_filename=require_text(payload, "output.report_filename"),
        ),
        email=EmailSection(
            enabled=email_enabled,
            send_on_empty=require_bool(payload, "email.send_on_empty"),
            layout=optional_choice(payload, "email.layout", ("table", "hybrid", "card"), default="table"),
            subject=require_text(payload, "email.subject"),
            to=require_text_list(payload, "email.to", allow_empty=not email_enabled),
            visible_fields=optional_text_list(payload, "email.visible_fields"),
        ),
    )


def require_text(payload: dict, path: str) -> str:
    value = get_path(payload, path)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def require_int(payload: dict, path: str, minimum: int) -> int:
    value = get_path(payload, path)
    if not isinstance(value, int) or value < minimum:
        raise ValueError(f"{path} must be an integer >= {minimum}")
    return value


def require_bool(payload: dict, path: str) -> bool:
    value = get_path(payload, path)
    if not isinstance(value, bool):
        raise ValueError(f"{path} must be true or false")
    return value


def require_text_list(payload: dict, path: str, allow_empty: bool = False) -> tuple[str, ...]:
    value = get_path(payload, path)
    if not isinstance(value, list) or (not value and not allow_empty):
        suffix = "a list" if allow_empty else "a non-empty list"
        raise ValueError(f"{path} must be {suffix}")
    items = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(f"{path} must only contain non-empty strings")
        items.append(entry.strip())
    return tuple(items)


def require_choice(payload: dict, path: str, allowed: tuple[str, ...]) -> str:
    value = require_text(payload, path)
    if value not in allowed:
        raise ValueError(f"{path} must be one of {', '.join(allowed)}")
    return value


def optional_text(payload: dict, path: str, default: str = "") -> str:
    try:
        value = get_path(payload, path)
    except ValueError:
        return default
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string")
    return value.strip()


def optional_bool(payload: dict, path: str, default: bool) -> bool:
    try:
        value = get_path(payload, path)
    except ValueError:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{path} must be true or false")
    return value


def optional_text_list(payload: dict, path: str) -> tuple[str, ...]:
    try:
        value = get_path(payload, path)
    except ValueError:
        return ()
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list")
    items = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(f"{path} must only contain non-empty strings")
        items.append(entry.strip())
    return tuple(items)


def optional_choice(payload: dict, path: str, allowed: tuple[str, ...], *, default: str) -> str:
    value = optional_text(payload, path, default)
    if value not in allowed:
        raise ValueError(f"{path} must be one of {', '.join(allowed)}")
    return value


def get_path(payload: dict, path: str) -> object:
    current: object = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"Missing required config: {path}")
        current = current[part]
    return current
