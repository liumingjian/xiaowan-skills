from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def make_config():
    from bid_parser import AWARD, TENDER
    from job_config import EmailSection, FilterSection, JobConfig, JobSection, OutputSection, SourceSection

    return JobConfig(
        job=JobSection(name="demo", description="演示日报", window_days=3),
        source=SourceSection(accounts=("七小服",), limit_per_account=10),
        filters=FilterSection(keywords=("维保", "服务器", "数据库"), categories=(TENDER, AWARD), sort_by="publish_date_desc"),
        output=OutputSection(root_dir="wechat-bid-digest", keep_raw=True, keep_parsed=True, keep_report=True, report_filename="demo.html"),
        email=EmailSection(enabled=True, send_on_empty=False, layout="table", subject="测试", to=("test@example.com",), visible_fields=()),
    )


def make_tender_record():
    from bid_parser import BidRecord, NOT_DISCLOSED, TENDER

    return BidRecord(
        category=TENDER,
        project_id="TEST-001",
        project_name="维保项目测试",
        amount="50万",
        procurer="测试单位",
        winner=NOT_DISCLOSED,
        publish_date="2026-03-10",
        deadline="2026-03-20",
        source_name="测试公众号",
        source_url="https://example.com/test",
    )


def article(*, title: str, content: str, create_time: str = "1773193871") -> dict:
    return {
        "title": title,
        "url": "https://mp.weixin.qq.com/s/demo",
        "account": "七小服",
        "create_time": create_time,
        "html": "<div id='js_content'></div>",
        "content": content,
    }
