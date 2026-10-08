# SPDX-License-Identifier: Apache-2.0
"""L1 单元测试：报告生成。

覆盖：三段式结构 / 严重度汇总 / 结论文案 / Markdown 渲染 / JSON 渲染。
"""
import json

from app.report.reporter import build_report, render_json, render_markdown
from app.state import CleanState

STATE = CleanState(thread_id="t1", source={"file_name": "s.csv"})
PROFILE = {
    "issues": [
        {"issue_name": "null", "null_score": 0.5, "severity": "high", "rows": [0]},
        {"issue_name": "date", "date_score": 0.2, "severity": "medium", "rows": [1]},
        {"issue_name": "format", "format_score": 0.1, "severity": "low", "rows": [2]},
    ],
    "detector_errors": [],
}
VERIFY = {"passed": True, "metrics": {"rows": {"before": 3, "after": 2}, "empty_ratio": {"before": 0.3, "after": 0.1}}}
TRANSFORM_LOG = [{"step": 1, "op": "row_dedupe", "rows_affected": 1}]


def build():
    return build_report(STATE, PROFILE, VERIFY, TRANSFORM_LOG)


def test_report_structure():
    r = build()
    assert set(r["sections"].keys()) == {"1_profile", "2_process", "3_quality", "4_unhandled"}
    assert r["sections"]["1_profile"]["severity_summary"] == {"high": 1, "medium": 1, "low": 1}
    assert r["sections"]["2_process"]["transform_log"] == TRANSFORM_LOG
    assert r["sections"]["3_quality"]["passed"] is True
    # 未处理项清单同时挂顶层 unhandled 与第四段
    assert isinstance(r["unhandled"], list)
    assert r["sections"]["4_unhandled"]["unhandled"] == r["unhandled"]


def test_unhandled_lists_uncovered_issues():
    """空配方 → 三类检出问题均如实列入未处理项（不标记为已清洗）。"""
    r = build()
    assert {i["issue_name"] for i in r["unhandled"]} == {"null", "date", "format"}
    assert all(i["reason"] for i in r["unhandled"])


def test_unhandled_excludes_covered_issues():
    """配方包含可处理该问题的操作时，该项不再计入未处理项。"""
    state = CleanState(thread_id="t2", source={"file_name": "s.csv"})
    state.rules_plan = {"operations": [{"op": "cell_fill_missing", "params": {"column": "备注"}}]}
    r = build_report(state, PROFILE, VERIFY, TRANSFORM_LOG)
    assert {i["issue_name"] for i in r["unhandled"]} == {"date", "format"}


def test_profile_conclusion_high():
    r = build()
    assert "高危" in r["sections"]["1_profile"]["conclusion"]


def test_profile_conclusion_clean():
    r = build_report(STATE, {"issues": []}, VERIFY, [])
    assert "未检出明显问题" in r["sections"]["1_profile"]["conclusion"]


def test_render_markdown_sections():
    md = render_markdown(build())
    assert "## 一、" in md and "## 二、" in md and "## 三、" in md
    assert "清洗报告" in md


def test_render_markdown_fail_loud():
    """未处理/未达标项必须如实出现（红线：不编造）。"""
    v = dict(VERIFY, passed=False, unmet=["dup_ratio: 0.5 > 0.0"])
    md = render_markdown(build_report(STATE, PROFILE, v, TRANSFORM_LOG))
    assert "未通过" in md
    assert "dup_ratio" in md


def test_render_json_roundtrip():
    data = json.loads(render_json(build()))
    assert data["thread_id"] == "t1"
    assert "sections" in data


def test_unhandled_discloses_skipped_non_count_units():
    """报告侧披露：剥离模式跳过的非计数单位值（保留原值）必须进「未处理项」，不得静默。"""
    log = [{"step": 1, "op": "cell_unit_convert", "mode": "strip", "rows_affected": 1, "target": "数量",
            "skipped_non_count": 2, "skipped_non_samples": ["2kg", "10元"],
            "skipped_non_reason": "非计数单位后缀（如 kg / 元）保留原值，未剥离"}]
    report = build_report(STATE, PROFILE, VERIFY, log)
    hit = [i for i in report["unhandled"] if i["issue_name"] == "cell_unit_convert"]
    assert len(hit) == 1, report["unhandled"]
    assert hit[0]["affected_rows"] == 2
    assert hit[0]["column"] == "数量"
    assert "2kg" in hit[0]["reason"] and "10元" in hit[0]["reason"]
    assert "保留原值" in hit[0]["reason"]
    # Markdown 渲染同样要看到（fail-loud，不只在 JSON 里）
    md = render_markdown(report)
    assert "非计数单位" in md and "2kg" in md


def test_unhandled_silent_when_no_skipped_non_count():
    """反向：无跳过项时不得凭空多出该条目（不编造）。"""
    log = [{"step": 1, "op": "cell_unit_convert", "mode": "strip", "rows_affected": 3, "target": "数量",
            "skipped_non_count": 0, "skipped_non_samples": [], "skipped_non_reason": ""}]
    report = build_report(STATE, PROFILE, VERIFY, log)
    assert "cell_unit_convert" not in {i["issue_name"] for i in report["unhandled"]}
