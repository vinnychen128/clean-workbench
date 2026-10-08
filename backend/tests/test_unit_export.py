# SPDX-License-Identifier: Apache-2.0
"""L1 单元测试：导出套件。

覆盖：CSV/XLSX/ODS/PDF 落盘 / 格式白名单 / 自动建目录 / 时间戳文件名。
"""
import os

import pytest

from app.export.exporter import (SUPPORTED_FORMATS, ExportError, export_csv, export_data, export_issues_csv,
                                 export_issues_summary_csv, export_json, export_ods, export_pdf, export_sql,
                                 export_template, export_xlsx)

COLS = ["id", "金额"]
ROWS = [["A001", 1200.0], ["A002", None]]


def test_supported_formats():
    assert SUPPORTED_FORMATS == ("csv", "xlsx", "ods", "pdf", "json", "sql", "template")


def test_export_csv(tmp_path):
    p = export_csv(COLS, ROWS, str(tmp_path), "orders")
    assert os.path.exists(p)
    assert p.endswith(".csv")
    with open(p, encoding="utf-8-sig") as f:
        head = f.readline().strip()
    assert head == "id,金额"


def test_export_xlsx(tmp_path):
    import openpyxl

    p = export_xlsx(COLS, ROWS, str(tmp_path), "orders")
    wb = openpyxl.load_workbook(p)
    ws = wb.active
    assert ws.cell(1, 1).value == "id"
    assert ws.cell(2, 2).value == 1200.0
    wb.close()


def test_export_ods(tmp_path):
    p = export_ods(COLS, ROWS, str(tmp_path), "orders")
    assert os.path.exists(p) and p.endswith(".ods")
    assert os.path.getsize(p) > 0


def test_export_pdf(tmp_path):
    p = export_pdf(COLS, ROWS, str(tmp_path), "orders", "# 报告")
    assert os.path.exists(p) and p.endswith(".pdf")
    assert os.path.getsize(p) > 0


def test_export_data_creates_dir(tmp_path):
    out = tmp_path / "a" / "b"
    p = export_data("csv", COLS, ROWS, str(out), "orders")
    assert os.path.exists(p)


def test_export_data_unsupported_format(tmp_path):
    with pytest.raises(ExportError) as ei:
        export_data("exe", COLS, ROWS, str(tmp_path), "orders")
    assert ei.value.code == "UNSUPPORTED_FORMAT"


def test_export_filenames_have_timestamp(tmp_path):
    import re

    p = export_csv(COLS, ROWS, str(tmp_path), "orders")
    assert re.search(r"orders_\d{8}_\d{6}\.csv$", os.path.basename(p))
    assert os.path.exists(p)


def test_export_no_overwrite_same_second(tmp_path):
    import time

    p1 = export_csv(COLS, ROWS, str(tmp_path), "orders")
    time.sleep(1.1)
    p2 = export_csv(COLS, ROWS, str(tmp_path), "orders")
    assert p1 != p2
    assert os.path.exists(p1) and os.path.exists(p2)


# ---------------------------------------------------------------------------
# JSON / SQL / 自定义模板 / 问题明细 / 问题汇总（套件）
# ---------------------------------------------------------------------------


def test_export_json_records(tmp_path):
    import json

    p = export_json(COLS, ROWS, str(tmp_path), "orders", meta={"thread_id": "t1"})
    assert p.endswith(".json")
    data = json.loads(open(p, encoding="utf-8").read())
    assert data["columns"] == COLS
    assert data["rows"][0] == {"id": "A001", "金额": 1200.0}
    assert data["meta"]["thread_id"] == "t1"


def test_export_sql_inserts(tmp_path):
    p = export_sql(COLS, ROWS, str(tmp_path), "orders", table_name="cleaned")
    text = open(p, encoding="utf-8").read()
    assert "CREATE TABLE" in text and "INSERT INTO" in text
    assert text.count("INSERT INTO") == 2
    assert "NULL" in text  # None → NULL，不臆造数据


def test_export_template_html(tmp_path):
    p = export_template(COLS, ROWS, str(tmp_path), "orders",
                        template_placeholders={"标题": "订单"}, encoding="utf-8", line_ending="crlf")
    assert p.endswith("_template.html")
    text = open(p, encoding="utf-8", newline="").read()
    assert "<table" in text and "订单" in text and "\r\n" in text


def test_export_issues_detail_and_summary(tmp_path):
    profile = {"issues": [{"issue_name": "null", "null_score": 0.5, "severity": "high",
                           "rows": [0, 2], "verbosity": 1}],
               "detector_errors": [{"issue_name": "date", "message": "检测器异常"}]}
    detail = export_issues_csv(profile, str(tmp_path), "orders")
    summary = export_issues_summary_csv(profile, str(tmp_path), "orders")
    assert "_issues.csv" in detail and "_issues_summary.csv" in summary
    detail_text = open(detail, encoding="utf-8-sig").read()
    assert "null" in detail_text and "0|2" in detail_text
    summary_text = open(summary, encoding="utf-8-sig").read()
    assert "检测器异常" in summary_text  # 检测失败项如实列出
