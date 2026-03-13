#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Optional


APP_DIR_NAME = ".wechat-bid-digest"
EXTEND_FILENAME = "EXTEND.md"
DEFAULT_SMTP_ENV_FILENAME = "smtp-default.env"
DEFAULT_JOB_FILENAME = "default.yaml"
WECOM_STATE_FILENAME = "notify_state.json"
QRCODE_FILENAME = "qrcode.png"
AUTH_STATE_FILENAME = "state.json"


def get_project_root(cwd: Optional[Path] = None) -> Path:
    return cwd or Path.cwd()


def get_project_app_dir(cwd: Optional[Path] = None) -> Path:
    return get_project_root(cwd) / APP_DIR_NAME


def get_extend_md_path(cwd: Optional[Path] = None) -> Path:
    return get_project_app_dir(cwd) / EXTEND_FILENAME


def get_jobs_dir(cwd: Optional[Path] = None) -> Path:
    return get_project_app_dir(cwd) / "jobs"


def get_default_job_path(cwd: Optional[Path] = None) -> Path:
    return get_jobs_dir(cwd) / DEFAULT_JOB_FILENAME


def get_auth_dir(cwd: Optional[Path] = None) -> Path:
    return get_project_app_dir(cwd) / "auth"


def get_auth_state_file(cwd: Optional[Path] = None) -> Path:
    return get_auth_dir(cwd) / AUTH_STATE_FILENAME


def get_auth_qrcode_path(cwd: Optional[Path] = None) -> Path:
    return get_auth_dir(cwd) / QRCODE_FILENAME


def get_wecom_state_file(cwd: Optional[Path] = None) -> Path:
    return get_project_app_dir(cwd) / "wecom" / WECOM_STATE_FILENAME


def get_default_smtp_env_path(cwd: Optional[Path] = None) -> Path:
    return get_project_app_dir(cwd) / DEFAULT_SMTP_ENV_FILENAME


def ensure_project_app_dirs(cwd: Optional[Path] = None) -> Path:
    app_dir = get_project_app_dir(cwd)
    app_dir.mkdir(parents=True, exist_ok=True)
    get_jobs_dir(cwd).mkdir(parents=True, exist_ok=True)
    get_auth_dir(cwd).mkdir(parents=True, exist_ok=True)
    get_wecom_state_file(cwd).parent.mkdir(parents=True, exist_ok=True)
    return app_dir
