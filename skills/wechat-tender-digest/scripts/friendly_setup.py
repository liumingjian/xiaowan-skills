#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Optional

from project_paths import get_default_job_path

DEFAULT_KEYWORDS = ("信创", "国产化", "自主可控", "操作系统", "数据库", "中间件", "云平台", "服务器", "存储", "网络设备", "软件", "硬件")
DEFAULT_SUBJECT = "每次招中标信息汇总"
DEFAULT_OUTPUT_ROOT = "wechat-bid-digest"
EMAIL_LAYOUTS = ("table", "hybrid", "card")


def default_job_candidates(cwd: Optional[Path] = None) -> tuple[Path]:
    return (get_default_job_path(cwd),)


def resolve_job_path(explicit_job: Optional[str], cwd: Optional[Path] = None) -> Optional[Path]:
    if explicit_job:
        return Path(explicit_job)
    project_path = default_job_candidates(cwd)[0]
    if project_path.exists():
        return project_path
    return None


def create_default_job(
    accounts: tuple[str, ...],
    *,
    recipients: tuple[str, ...] = (),
    keywords: tuple[str, ...] = DEFAULT_KEYWORDS,
    job_name: str = "daily-bid",
    description: str = "",
    window_days: str = "3",
    email_layout: str = "table",
    send_on_empty: bool = False,
    subject: str = DEFAULT_SUBJECT,
    output_root: str = DEFAULT_OUTPUT_ROOT,
    report_filename: str = "",
    save_location: str = "project",
    visible_fields: tuple[str, ...] = (),
    cwd: Optional[Path] = None,
) -> Path:
    """Create a job YAML file programmatically (no interactive input)."""
    if save_location != "project":
        raise ValueError("仅支持保存到当前项目 .wechat-bid-digest/jobs/")
    target_path = default_job_candidates(cwd)[0]
    if not description:
        description = f"{accounts[0]}招中标日报" if accounts else "招中标日报"
    if not report_filename:
        report_filename = f"{slugify(job_name)}-report.html"
    email_enabled = bool(recipients)
    yaml_text = render_job_yaml(
        job_name=slugify(job_name),
        description=description,
        window_days=window_days,
        accounts=accounts,
        keywords=keywords,
        recipients=recipients,
        email_enabled=email_enabled,
        email_layout=email_layout,
        send_on_empty=send_on_empty,
        subject=subject,
        output_root=output_root,
        report_filename=report_filename,
        visible_fields=visible_fields,
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(yaml_text, encoding="utf-8")
    return target_path


def render_job_yaml(**values: object) -> str:
    recipients = values["recipients"]
    recipient_block = "\n".join(f"    - {yaml_quote(item)}" for item in recipients)
    keyword_lines = "\n".join(f"    - {yaml_quote(item)}" for item in values["keywords"])
    account_lines = "\n".join(f"    - {yaml_quote(item)}" for item in values["accounts"])
    email_to = f"  to:\n{recipient_block}" if recipients else "  to: []"
    visible = values.get("visible_fields", ())
    visible_block = ""
    if visible:
        visible_lines = "\n".join(f"    - {yaml_quote(item)}" for item in visible)
        visible_block = f"\n  visible_fields:\n{visible_lines}"
    return f"""job:
  name: {yaml_quote(values["job_name"])}
  description: {yaml_quote(values["description"])}
  window_days: {values["window_days"]}

source:
  accounts:
{account_lines}
  limit_per_account: 10

filters:
  keywords:
{keyword_lines}
  categories:
    - "招标"
    - "中标"
  sort_by: "publish_date_desc"

output:
  root_dir: {yaml_quote(values["output_root"])}
  keep_raw: true
  keep_parsed: true
  keep_report: true
  report_filename: {yaml_quote(values["report_filename"])}

email:
  enabled: {str(values["email_enabled"]).lower()}
  send_on_empty: {str(values["send_on_empty"]).lower()}
  layout: {yaml_quote(values["email_layout"])}
  subject: {yaml_quote(values["subject"])}
{email_to}{visible_block}
"""


def parse_csv(value: str) -> tuple[str, ...]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    return tuple(items)


def parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"true", "yes", "y", "1"}:
        return True
    if lowered in {"false", "no", "n", "0"}:
        return False
    raise ValueError("布尔值仅支持 true/false")


def parse_choice(value: str, allowed: tuple[str, ...], label: str) -> str:
    lowered = value.strip().lower()
    if lowered not in allowed:
        raise ValueError(f"{label} 仅支持: {', '.join(allowed)}")
    return lowered


def slugify(value: str) -> str:
    text = value.strip().lower().replace(" ", "-").replace("_", "-")
    compact = "".join(ch for ch in text if ch.isalnum() or ch == "-")
    return compact or "daily-bid"


def yaml_quote(value: object) -> str:
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'
