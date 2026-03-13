#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from friendly_setup import create_default_job, parse_csv
from presets import get_preset
from visible_fields import VisibleFieldOptions, resolve_visible_fields


def handle_create_job(args: argparse.Namespace) -> Path:
    accounts = parse_csv(args.accounts) if args.accounts else ()
    if not accounts:
        raise ValueError("--create-job 需要通过 --accounts 指定公众号名称")
    recipients = parse_csv(args.to) if args.to else ()
    visible_fields = resolve_visible_fields(
        VisibleFieldOptions(
            field_set=getattr(args, "field_set", None),
            visible_fields_csv=getattr(args, "visible_fields", None),
        )
    )

    if args.preset:
        preset = get_preset(args.preset)
        return create_default_job(
            accounts,
            recipients=recipients,
            keywords=preset.keywords,
            job_name=f"{preset.name}-digest",
            description=preset.description,
            window_days=str(preset.window_days),
            email_layout=args.layout or preset.layout,
            output_root="wechat-bid-digest",
            visible_fields=visible_fields,
        )
    return create_default_job(
        accounts,
        recipients=recipients,
        email_layout=args.layout or "table",
        output_root="wechat-bid-digest",
        visible_fields=visible_fields,
    )
