#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""洗后脏点对账 —— 自检门（接 CI / 变异检测）。

固定在仓样例上跑「样例链路 → 导出 → 对账 → 退出码」，三种情形都必须给出预期结论：

  ① 未清洗（源 vs 源）            → `check_residual_dirt.py` 退出码 = 1（红）
  ② 正确清洗（源 vs 洗后）        → 退出码 = 0（绿）
  ③ 回退一条修复规则（变异：把洗后的一个金额改回带币称后缀、一个日期改回点分）
     → 退出码 = 1（红）；再改回 → 0（绿）。用于证明"对账脚本真能抓到规则回退"，
       而不是恰好命中/自证。

用法: python3 scripts/check_residual_dirt_selftest.py
退出码: 0 = 三情形全部符合预期; 1 = 任一情形不符（即 CI 红）。
"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
import tempfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "backend"))
CHECKER = os.path.join(REPO, "scripts", "check_residual_dirt.py")
SRC_CSV = os.path.join(REPO, "samples", "dirty_orders.csv")
RECIPE_JSON = os.path.join(REPO, "samples", "recipe_orders_demo.json")


def run_checker(src: str, out: str) -> int:
    """跑对账脚本，返回其退出码（0 通过 / 1 不合格 / 2 用法错）。"""
    proc = subprocess.run(
        [sys.executable, CHECKER, src, out],
        capture_output=True, text=True, cwd=REPO,
    )
    if proc.returncode == 2:
        print(proc.stdout, proc.stderr)
        raise AssertionError(f"对账脚本用法错（exit=2）: {src} vs {out}")
    return proc.returncode


def clean_via_pipeline(src: str, out_dir: str) -> str:
    """样例链路：解析 → 配方校验 → 确认 → 执行 → 导出 CSV。"""
    import json

    from app.parsing.parser import parse_csv
    from app.recipe.engine import validate_recipe
    from app.engine.engine import confirm_plan, execute_recipe
    from app.export.exporter import export_csv
    from app.state import CleanState

    with open(src, "rb") as fh:
        parsed = parse_csv(fh.read(), "ref://parse/selftest")
    with open(RECIPE_JSON, encoding="utf-8") as fh:
        recipe = json.load(fh)
    errs = validate_recipe(recipe, parsed.columns)
    assert not errs, f"样例配方校验失败: {errs}"
    state = CleanState(thread_id="clean-selftest", source={"file_name": os.path.basename(src)})
    state.rules_plan = recipe
    state.stage = "plan"
    confirm_plan(state, True, "selftest")
    res = execute_recipe(state, parsed.columns, parsed.rows)
    return export_csv(res["columns"], res["rows"], out_dir, "selftest_out")


def mutate(cleaned: str, mutated: str) -> None:
    """变异：把一条修复规则"改回旧实现"——金额回退成带币称后缀、日期回退成点分写法。"""
    with open(cleaned, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
        cols = list(rows[0].keys()) if rows else []
    touched = {"金额": False, "日期": False}
    for row in rows:
        if not touched["金额"] and row.get("金额", "").strip():
            row["金额"] = "3000元"       # 旧实现：不清货币后缀
            touched["金额"] = True
        if not touched["日期"] and len(row.get("日期", "")) == 10:
            row["日期"] = "2024.01.01"   # 旧实现：保留点分分隔
            touched["日期"] = True
    with open(mutated, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="clean-selftest-")
    failures = []

    # ① 未清洗（源 vs 源）→ 必须红
    code = run_checker(SRC_CSV, SRC_CSV)
    print(f"[{'OK' if code == 1 else 'FAIL'}] ① 未清洗 源vs源 → exit={code}（期望 1 红）")
    if code != 1:
        failures.append("① 未清洗未变红")

    # ② 正确清洗 → 必须绿
    cleaned = clean_via_pipeline(SRC_CSV, tmp)
    code = run_checker(SRC_CSV, cleaned)
    print(f"[{'OK' if code == 0 else 'FAIL'}] ② 正确清洗 → exit={code}（期望 0 绿）: {cleaned}")
    if code != 0:
        failures.append("② 正确清洗未变绿")

    # ③ 回退一条修复规则 → 必须红；再改回 → 必须绿
    mutated = os.path.join(tmp, "selftest_mutated.csv")
    mutate(cleaned, mutated)
    code = run_checker(SRC_CSV, mutated)
    print(f"[{'OK' if code == 1 else 'FAIL'}] ③ 回退修复规则(变异) → exit={code}（期望 1 红）")
    if code != 1:
        failures.append("③ 规则回退未被对账脚本抓到")
    code = run_checker(SRC_CSV, cleaned)
    print(f"[{'OK' if code == 0 else 'FAIL'}] ③' 改回修复规则 → exit={code}（期望 0 绿）")
    if code != 0:
        failures.append("③' 改回规则后未恢复绿")

    print()
    if failures:
        print("RESIDUAL-DIRT SELFTEST FAILED: " + "；".join(failures))
        return 1
    print("RESIDUAL-DIRT SELFTEST ALL PASSED（对账脚本能出相反结论：错件红 / 对件绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
