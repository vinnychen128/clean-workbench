"""回归测试：洗后脏点对账脚本（入仓 + 能出相反结论 + 用法错退出码）。

对应回归要求：
- 脚本已入仓 `scripts/check_residual_dirt.py`（`git ls-files` 可查），CLI 语义与退出码保持
  0 通过 / 1 不合格 / 2 用法错。
- 跑样例链路 → 导出 → 对账 → 非 0 即红（smoke.py 第 9 步与 CI 均接该门）。
- 变异检测：把一条修复规则改回旧实现 → 对账必须变红；改回 → 变绿。
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CHECKER = os.path.join(REPO, "scripts", "check_residual_dirt.py")
SRC_CSV = os.path.join(REPO, "samples", "dirty_orders.csv")
RECIPE_JSON = os.path.join(REPO, "samples", "recipe_orders_demo.json")


def _run_checker(src: str, out: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, CHECKER, src, out], capture_output=True, text=True, cwd=REPO)


def _clean_to_csv(out_dir: str) -> str:
    from app.engine.engine import confirm_plan, execute_recipe
    from app.export.exporter import export_csv
    from app.parsing.parser import parse_csv
    from app.recipe.engine import validate_recipe
    from app.state import CleanState

    with open(SRC_CSV, "rb") as fh:
        parsed = parse_csv(fh.read(), "ref://parse/test-recon")
    with open(RECIPE_JSON, encoding="utf-8") as fh:
        recipe = json.load(fh)
    assert not validate_recipe(recipe, parsed.columns)
    state = CleanState(thread_id="clean-recon-test", source={"file_name": "dirty_orders.csv"})
    state.rules_plan = recipe
    state.stage = "plan"
    confirm_plan(state, True, "pytest")
    res = execute_recipe(state, parsed.columns, parsed.rows)
    return export_csv(res["columns"], res["rows"], out_dir, "recon_out")


def test_recon_script_is_tracked_and_usage_exit_code():
    """脚本入仓（git ls-files 可查），用法错返回 2 且不抛 traceback。"""
    tracked = subprocess.run(["git", "ls-files", "scripts/check_residual_dirt.py"],
                             capture_output=True, text=True, cwd=REPO)
    assert tracked.stdout.strip() == "scripts/check_residual_dirt.py", tracked.stdout
    proc = subprocess.run([sys.executable, CHECKER], capture_output=True, text=True, cwd=REPO)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr
    proc = subprocess.run([sys.executable, CHECKER, "/tmp/不存在.csv", "/tmp/不存在.csv"],
                          capture_output=True, text=True, cwd=REPO)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr


def test_recon_red_on_uncleaned_and_green_after_pipeline():
    """未清洗必红（1）；正确清洗后必绿（0）。"""
    with tempfile.TemporaryDirectory() as tmp:
        cleaned = _clean_to_csv(tmp)
        red = _run_checker(SRC_CSV, SRC_CSV)
        assert red.returncode == 1, red.stdout
        green = _run_checker(SRC_CSV, cleaned)
        assert green.returncode == 0, green.stdout


def test_recon_detects_reverted_rule():
    """把一条修复规则改回旧实现（金额回退带币称后缀、日期回退点分）→ 必须变红。"""
    with tempfile.TemporaryDirectory() as tmp:
        cleaned = _clean_to_csv(tmp)
        with open(cleaned, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
            cols = list(rows[0].keys())
        for row in rows:
            if row.get("金额", "").strip():
                row["金额"] = "3000元"
                break
        for row in rows:
            if len(row.get("日期", "")) == 10:
                row["日期"] = "2024.01.01"
                break
        mutated = os.path.join(tmp, "mutated.csv")
        with open(mutated, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=cols)
            writer.writeheader()
            writer.writerows(rows)
        bad = _run_checker(SRC_CSV, mutated)
        assert bad.returncode == 1, bad.stdout
        ok = _run_checker(SRC_CSV, cleaned)
        assert ok.returncode == 0, ok.stdout


def test_recon_selftest_script_passes():
    """CI 门同一条命令：脚本自检必须整体通过。"""
    proc = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "check_residual_dirt_selftest.py")],
                          capture_output=True, text=True, cwd=REPO)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("text,expected", [
    ("2024-13-99", True),   # 月份非法
    ("2024.02.30", True),   # 2 月 30 日不存在（语义判定：不能只看形态）
    ("20240230", True),
    ("2024-02-29", False),  # 闰年合法
    ("2023-02-29", True),   # 平年非法
    ("2024-05-06", False),
])
def test_semantic_date_classification(text, expected):
    """语义非法判定覆盖点分/无分隔等全部日期形态。"""
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import importlib
    mod = importlib.import_module("check_residual_dirt")
    assert mod._semantic_bad_date(text) is expected
