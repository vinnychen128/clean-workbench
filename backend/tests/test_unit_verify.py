# SPDX-License-Identifier: Apache-2.0
"""L1 单元测试：前后校验。

覆盖：指标计算（行数/列数/空值率/重复率）/ 目标判定 / 行数塌缩不通过 / 空表兜底。
"""
from app.verify.verifier import compare

BEFORE = {
    "columns": ["id", "金额", "备注"],
    "rows": [
        ["A001", "￥1,200", "  正常  "],
        ["A001", "￥1,200", "  正常  "],
        ["A002", None, "乱码��"],
        ["A003", "3000元", "文本"],
    ],
}

AFTER_CLEAN = {
    "columns": ["id", "金额", "备注"],
    "rows": [
        ["A001", "1200.00", "正常"],
        ["A002", None, "乱码��"],
        ["A003", "3000.00", "文本"],
    ],
}


def test_compare_metrics_fields():
    r = compare(BEFORE, BEFORE)
    m = r["metrics"]
    # 既有四键不变；无体检结果传入时按数据派生判定范围 —— 本份数据含"金额不规范"，故含金额残留键
    assert {"rows", "columns", "empty_ratio", "dup_ratio"} <= set(m.keys())
    assert "amount_dirty_ratio" in m
    assert m["rows"]["before"] == m["rows"]["after"] == 4
    assert m["dup_ratio"]["before"] == 0.25


def test_compare_passed_after_clean():
    r = compare(BEFORE, AFTER_CLEAN)
    assert r["passed"] is True
    assert r["unmet"] == []


def test_compare_dup_not_fixed_fails():
    r = compare(BEFORE, BEFORE)
    assert r["passed"] is False
    # 契约：unmet 为对象数组
    assert any(u["key"] == "dup_ratio" for u in r["unmet"])


def test_compare_row_count_collapse_fails():
    after = {"columns": BEFORE["columns"], "rows": BEFORE["rows"][:1]}
    r = compare(BEFORE, after)
    assert r["passed"] is False
    assert any("行数" in u["message"] for u in r["unmet"])


def test_compare_empty_rows_safe():
    r = compare({"columns": [], "rows": []}, {"columns": [], "rows": []})
    assert r["metrics"]["empty_ratio"]["after"] == 1.0
    assert "passed" in r


def test_compare_custom_targets():
    r = compare(BEFORE, AFTER_CLEAN, targets={"dup_ratio": 0.5, "empty_ratio": 0.9})
    assert r["passed"] is True
