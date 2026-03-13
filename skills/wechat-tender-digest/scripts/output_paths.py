#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path


MAX_DIRNAME_LENGTH = 80


def safe_dirname(value: str, *, max_length: int = MAX_DIRNAME_LENGTH) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "", value)
    compact = re.sub(r"\s+", "_", cleaned).strip("_.")
    safe = compact[:max_length] if len(compact) > max_length else compact
    return safe or "untitled"


def build_job_date_output_dir(*, root_dir: str, job_name: str, to_date: str) -> Path:
    job_dir = safe_dirname(job_name)
    return Path(root_dir) / job_dir / to_date
