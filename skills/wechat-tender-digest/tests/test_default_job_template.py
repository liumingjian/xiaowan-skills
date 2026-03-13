#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

import support  # noqa: F401  # adds scripts/ to sys.path

from job_config import load_job_config


class DefaultJobTemplateTests(unittest.TestCase):
    def test_default_job_template_loads(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = root / "config" / "jobs" / "default.job.yaml"
        self.assertTrue(path.exists(), f"missing job template: {path}")

        config = load_job_config(str(path))
        self.assertEqual(config.job.name, "daily-bid")
        self.assertTrue(config.source.accounts)
        self.assertFalse(config.email.enabled)
        self.assertEqual(config.email.to, ())


if __name__ == "__main__":
    raise SystemExit(unittest.main())

