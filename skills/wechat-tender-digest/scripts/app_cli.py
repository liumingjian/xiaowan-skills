#!/usr/bin/env python3
from __future__ import annotations

import argparse
from typing import Optional, Sequence


STAGES = ("fetch", "parse", "render", "send")
FIELD_SETS = ("full", "core", "minimal")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a WeChat bid digest job.")
    parser.add_argument("--job", help="Path to YAML job file.")
    parser.add_argument("--preset", help="Use a built-in preset (xinc, hardware, software, engineering).")
    parser.add_argument("--accounts", help="Comma-separated WeChat account names.")
    parser.add_argument("--keywords", help="Comma-separated keywords for filtering.")
    parser.add_argument("--categories", help="Comma-separated categories (招标,中标).")
    parser.add_argument("--to", help="Comma-separated recipient email addresses.")
    parser.add_argument("--layout", help="Email layout: table, hybrid, or card.")
    parser.add_argument("--field-set", choices=FIELD_SETS, help="Field visibility preset: full, core, or minimal.")
    parser.add_argument("--visible-fields", help="Comma-separated field keys overriding --field-set (e.g. project_name,amount).")
    parser.add_argument("--window-days", type=int, help="Number of days to look back.")
    parser.add_argument("--create-job", action="store_true", help="Create a job file from preset/params and exit.")
    parser.add_argument("--doctor", action="store_true", help="Print environment diagnostics.")
    parser.add_argument("--login", action="store_true", help="Trigger QR code login manually.")
    parser.add_argument("--auth-daemon", action="store_true", help="Run auth daemon: periodically check token health and refresh via QR login.")
    parser.add_argument("--auth-check-interval-seconds", type=int, help="Auth daemon check interval in seconds.")
    parser.add_argument("--until", choices=STAGES, default="send", help="Stop after a specific stage.")
    parser.add_argument("--from-date", help="Override start date in YYYY-MM-DD format.")
    parser.add_argument("--to-date", help="Override end date in YYYY-MM-DD format.")
    return parser.parse_args(list(argv) if argv is not None else None)
