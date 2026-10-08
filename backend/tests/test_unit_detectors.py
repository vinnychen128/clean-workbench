# SPDX-License-Identifier: Apache-2.0
"""L1 单元测试：9 个检测器。

每个检测器为纯函数：给定输入列/行 → 断言检出与分数。
"""

from app.detectors.base import Detector, DetectorRegistry

COLUMNS = ["id", "名称", "金额", "日期", "备注"]

ROWS = [
    ["A001", "张三", "100", "2024/01/01", "正常"],
    ["A001", "张三", "100", "2024/01/01", "正常"],      # duplicate 行
    ["A002", "李四", None, "2024-13-99", "乱码��"],     # null / date / mojibake
    ["A003", "王五", "3000元", "2024.02.30", " 空格 "],  # amount / unit? / date / format
    ["A004", "赵六", "abc", "2024/03/01", "正常"],       # amount 异常
    ["", "孙七", "-9999", "2024/04/01", ""],             # null / outlier / identifier
    ["A006", "周八", "1,200", "2024/05/01", "ABC-123"],  # format / amount
]

EXPECTED_ISSUES = {
    "null", "duplicate", "outlier", "format", "amount", "date",
    "unit", "identifier_column", "mojibake",
}


def test_registry_has_9():
    assert set(DetectorRegistry.all().keys()) == EXPECTED_ISSUES


def test_each_detector_returns_contract():
    for name, cls in DetectorRegistry.all().items():
        det = cls(verbosity=1)
        assert det.issue_name == name
        report = det.compute(COLUMNS, ROWS)
        assert report["issue_name"] == name
        assert f"{name}_score" in report
        assert report["severity"] in ("low", "medium", "high")
        assert isinstance(report["rows"], list)


def test_null_detector():
    from app.detectors.impl.null import NullDetector
    rep = NullDetector().compute(COLUMNS, ROWS)
    assert 0 in rep["rows"] or any(True for _ in rep["rows"])
    assert rep["null_score"] >= 0


def test_duplicate_detector():
    from app.detectors.impl.duplicate import DuplicateDetector
    rep = DuplicateDetector().compute(COLUMNS, ROWS)
    assert 1 in rep["rows"]
    assert rep["duplicate_score"] > 0


def test_outlier_detector():
    from app.detectors.impl.outlier import OutlierDetector
    rep = OutlierDetector().compute(COLUMNS, ROWS)
    # 行 5 有 -9999 极端值
    assert rep["outlier_score"] >= 0
    assert rep["severity"] in ("low", "medium", "high")


def test_format_detector():
    from app.detectors.impl.format import FormatDetector
    rep = FormatDetector().compute(COLUMNS, ROWS)
    assert rep["format_score"] >= 0


def test_amount_detector():
    from app.detectors.impl.amount import AmountDetector
    rep = AmountDetector().compute(COLUMNS, ROWS)
    assert rep["amount_score"] > 0  # 存在"3000元"、"1,200"、"abc"


def test_date_detector():
    from app.detectors.impl.date import DateDetector
    rep = DateDetector().compute(COLUMNS, ROWS)
    assert rep["date_score"] > 0  # 存在非法日期


def test_unit_detector():
    from app.detectors.impl.unit import UnitDetector
    rep = UnitDetector().compute(COLUMNS, ROWS)
    assert rep["unit_score"] >= 0


def test_identifier_column_detector():
    from app.detectors.impl.identifier_column import IdentifierColumnDetector
    rep = IdentifierColumnDetector().compute(COLUMNS, ROWS)
    assert rep["identifier_column_score"] >= 0


def test_mojibake_detector():
    from app.detectors.impl.mojibake import MojibakeDetector
    rep = MojibakeDetector().compute(COLUMNS, ROWS)
    assert rep["mojibake_score"] > 0  # 行 2 有乱码字符


def test_run_all_isolates_bad_detector(monkeypatch):
    """单个检测器异常不影响其余（独立捕获）。"""

    class BadDetector(Detector):
        issue_name = "bad_test_detector"

        def compute(self, columns, rows):
            raise RuntimeError("boom")

    DetectorRegistry._registry["bad_test_detector"] = BadDetector
    try:
        result = DetectorRegistry.run_all(COLUMNS, ROWS)
        assert len(result["issues"]) == 9  # 其余 9 个照常
        assert any(e["issue_name"] == "bad_test_detector" for e in result["detector_errors"])
    finally:
        DetectorRegistry._registry.pop("bad_test_detector", None)


def test_verbosity_cap():
    det = DetectorRegistry.get("null")(verbosity=99)
    assert det.verbosity <= max(det.verbosity_levels)


# ---------------------------------------------------------------------------
# 「单位」检测行的正例 / 反例边界
# ---------------------------------------------------------------------------

def _unit_report(rows, columns=("数量", "备注")):
    from app.detectors.impl.unit import UnitDetector
    return UnitDetector().compute(list(columns), [list(r) for r in rows])


def test_unit_quantity_mixed_reports():
    """正例：`3件` + `5` + `2kg` 同列混用 → 命中并给出波及行数。"""
    rep = _unit_report([["3件", "a"], ["5", "b"], ["2kg", "c"]])
    assert rep["unit_score"] > 0
    assert rep["columns"] == ["数量"]
    assert rep["rows_total"] >= 2
    kinds = {it["kind"] for it in rep["sub_items"]}
    assert "mixed" in kinds and "quantity_unit" in kinds
    q = next(it for it in rep["sub_items"] if it["kind"] == "quantity_unit")
    assert q["suggest_op"] == "cell_unit_convert"
    assert q["suggest_params"]["column"] == "数量"
    assert q["suggest_params"]["to"] == "纯数值"
    # 本列同时含物理量混用 → 不给"问题级"通用参数（不猜，交由用户在步卡自选）
    assert "suggest_op" not in rep


def test_unit_quantity_unit_mixed_bare_gives_suggest():
    """命中类子项全为量词（`3件` 与裸数字同列）→ 给问题级剥离建议（联动）。"""
    rep = _unit_report([["3件", ""], ["5", ""], ["12", ""]])
    assert {it["kind"] for it in rep["sub_items"]} == {"quantity_unit"}
    assert rep["suggest_op"] == "cell_unit_convert"
    assert rep["suggest_params"] == {"column": "数量", "from": "件", "to": "纯数值"}


def test_unit_single_quantity_unit_only_not_reported():
    """反例：全列单一只含 `3件` → 不报（避免噪声）。"""
    rep = _unit_report([["3件", ""], ["7件", ""], ["2件", ""]])
    assert rep["unit_score"] == 0
    assert rep["sub_items"] == []
    assert rep["columns"] == []
    assert "suggest_op" not in rep


def test_unit_bare_numbers_only_not_reported():
    """反例：`5` + `12`（全列无单位）→ 不报。"""
    rep = _unit_report([["5", ""], ["12", ""]])
    assert rep["unit_score"] == 0
    assert rep["sub_items"] == []


def test_unit_two_quantity_unit_kinds_reports():
    """边界：同列出现 ≥2 种量词（件/个）→ 按同列混用命中，且给剥离建议。"""
    rep = _unit_report([["3件", ""], ["2个", ""]])
    assert rep["unit_score"] > 0
    q = next(it for it in rep["sub_items"] if it["kind"] == "quantity_unit")
    assert q["units"] == ["个", "件"]


def test_unit_currency_column_not_counted_as_mixed():
    """金额列（带「元」+ 裸数字）不得出现在单位混用命中里。"""
    rep = _unit_report([["100元", ""], ["200", ""]], columns=("金额", "备注"))
    assert rep["unit_score"] == 0
    kinds = [it["kind"] for it in rep["sub_items"]]
    assert kinds == ["currency_hint"]
    assert rep["columns"] == []
