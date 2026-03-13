#!/usr/bin/env python3
from __future__ import annotations

import unittest

from support import article
from bid_parser import AWARD, TENDER, NOT_DISCLOSED, collect_records, detect_category, find_field, split_blocks


class ParserTests(unittest.TestCase):
    def test_collect_records_parses_tender_and_award(self) -> None:
        raw_articles = [
            article(
                title="招标日报",
                content=(
                    "招 标 信 息\n\n1\n\n项目名称：数据库软件维保项目\n"
                    "预算金额：30万元\n项目编号：A-1\n采购人：甲公司\n"
                    "投标截止时间：2026年3月16日\n"
                ),
            ),
            article(
                title="中标日报",
                content=(
                    "中 标 信 息\n\n1\n\n项目名称：服务器采购项目\n"
                    "项目编号：B-2\n中标金额：120万元\n采购人：乙公司\n"
                    "中标供应商：丙公司\n公示结束时间：2026年3月18日\n"
                ),
                create_time="1773281179",
            ),
        ]
        records = collect_records(raw_articles, ("维保", "服务器"), (TENDER, AWARD), sort_by="publish_date_desc")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].category, AWARD)
        self.assertEqual(records[1].category, TENDER)
        self.assertEqual(records[0].winner, "丙公司")
        self.assertEqual(records[1].amount, "30万元")

    def test_deadline_priority_and_missing_fields(self) -> None:
        raw_articles = [
            article(
                title="中标日报",
                content=(
                    "中 标 信 息\n\n1\n\n项目名称：信创数据库项目\n"
                    "采购人：甲方\n获取采购文件：2026年3月10日－2026年3月12日\n"
                    "开标时间：2026年3月14日\n公示结束时间：2026年3月20日\n"
                ),
            )
        ]
        records = collect_records(raw_articles, ("数据库",), (AWARD,), sort_by="publish_date_desc")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].deadline, "2026-03-20")
        self.assertEqual(records[0].project_id, NOT_DISCLOSED)
        self.assertEqual(records[0].winner, NOT_DISCLOSED)

    def test_summary_style_fields_truncate_and_amount_without_colon(self) -> None:
        raw_articles = [
            article(
                title="采购意向汇总",
                content=(
                    "招 标 信 息\n\n1\n\n"
                    "项目名称：2026年XC服务器、操作系统、数据库采购项目（政府采购意向）。采购需求：标的1 XC服务器，数量49，预算金额¥7,260,500.00元；"
                    "标的2 XC服务器操作系统，数量46，预算金额¥379,500.00元；标的3 信创数据库，数量9，预算金额¥450,000.00元。"
                    "预算总金额¥8,090,000.00元，预计采购时间2026年3月。\n"
                    "采购人：桐庐县数据资源管理局 信创产品、服务与数量：XC服务器49台（预算726.05万元）。公告信息：\n"
                ),
                create_time="1773281179",
            )
        ]
        records = collect_records(raw_articles, ("XC服务器",), (TENDER,), sort_by="publish_date_desc")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].project_name, "2026年XC服务器、操作系统、数据库采购项目（政府采购意向）")
        self.assertEqual(records[0].procurer, "桐庐县数据资源管理局")
        self.assertEqual(records[0].amount, "¥8,090,000.00元")

    def test_find_field_stops_before_following_labels(self) -> None:
        raw_articles = [
            article(
                title="OS中标｜北京农商银行采购麒麟操作系统",
                content=(
                    "北京农商银行信创服务器操作系统和中间件软件采购项目签约结果公告\n\n"
                    "招标项目名称： 北京农商银行信创服务器操作系统和中间件软件采购项目\n"
                    "招标编号： GXCZ-C-26080009\n"
                    "招标项目编号： Z11010003FJ023332001\n"
                    "招标单位： 北京农村商业银行股份有限公司\n"
                    "招标代理： 国信招标集团股份有限公司\n"
                    "发布时间： 2026-03-06\n"
                ),
            )
        ]
        records = collect_records(raw_articles, ("操作系统",), (TENDER,), sort_by="publish_date_desc")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].project_id, "GXCZ-C-26080009")
        self.assertEqual(records[0].procurer, "北京农村商业银行股份有限公司")

    def test_split_blocks_chinese_ordinals(self) -> None:
        content = "一、\n项目名称：项目A\n预算金额：10万\n\n二、\n项目名称：项目B\n预算金额：20万"
        blocks = split_blocks(content)
        self.assertGreaterEqual(len(blocks), 2)

    def test_detect_category_expanded(self) -> None:
        self.assertEqual(detect_category("中标公告", "项目名称：测试"), AWARD)
        self.assertEqual(detect_category("成交公告", "项目名称：测试"), AWARD)
        self.assertEqual(detect_category("结果公示", "项目名称：测试"), AWARD)
        self.assertEqual(detect_category("招标公告", "项目名称：测试"), TENDER)
        self.assertEqual(detect_category("采购公告", "项目名称：测试"), TENDER)

    def test_find_field_with_spaced_labels(self) -> None:
        block = "项 目 名 称：测试项目ABC\n预算金额：100万"
        result = find_field(block, ("项目名称",))
        self.assertEqual(result, "测试项目ABC")


if __name__ == "__main__":
    unittest.main()
