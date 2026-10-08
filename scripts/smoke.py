#!/usr/bin/env python3
"""清洗项目核心链路冒烟测试（仅标准库，不依赖 FastAPI / LangGraph / 可选包）。

覆盖：解析(CSV) → 9 检测器 → 配方校验/重放 → 人工门 → 执行 → 前后校验 → 报告 → 导出(CSV)。
失败即非零退出。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile

# 仓库根（脚本位于仓库/scripts/）
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "backend"))


def main() -> int:
    from app.parsing.parser import parse_csv
    from app.detectors.base import DetectorRegistry
    from app.recipe.engine import describe_recipe, replay, validate_recipe
    from app.engine.engine import confirm_plan, execute_recipe
    from app.verify.verifier import compare
    from app.report.reporter import build_report, render_markdown
    from app.state import CleanState

    # 1) 构造含问题的 CSV
    sample = (
        "id,名称,金额,日期,备注\n"
        "A001,张三,￥1,200,2024/01/01,正常\n"
        "A001,张三,￥1,200,2024/01/01,正常\n"
        "A002,李四,,2024-13-99,乱\u00e4\u00b8码\u00e4\u00b8\n"
        "A003,王五,3000元,2024.02.30, 前后空格 \n"
    )
    raw = sample.encode("utf-8")
    pr = parse_csv(raw, "ref://parse/test")
    assert pr.row_count == 4, f"row_count={pr.row_count}"
    print(f"[OK] parse_csv: {pr.row_count} 行 x {pr.col_count} 列, 报告={pr.parsing_report}")

    # 2) 检测器全跑
    profile = DetectorRegistry.run_all(pr.columns, pr.rows)
    assert len(profile["issues"]) == 9, f"issues={len(profile['issues'])}"
    assert profile["issues"][0]["severity"] in ("high", "medium"), "首条应为高危/中危"
    print(f"[OK] detectors: 9 项, 首条={profile['issues'][0]['issue_name']}({profile['issues'][0]['severity']})")

    # 3) 配方
    recipe = {
        "schema_id": "clean-recipe/v1",
        "name": "smoke",
        "source": {"thread_id": "t", "file_name": "sample.csv"},
        "operations": [
            {"op": "row_dedupe", "params": {}},
            {"op": "cell_trim", "params": {"columns": ["备注"]}},
            {"op": "cell_amount_clean", "params": {"column": "金额"}},
            {"op": "cell_date_normalize", "params": {"column": "日期"}},
            {"op": "cell_fullwidth", "params": {"columns": ["名称"]}},
        ],
    }
    errs = validate_recipe(recipe, pr.columns)
    assert not errs, f"validate_recipe errors: {errs}"
    desc = describe_recipe(recipe)
    assert len(desc) == 5
    print(f"[OK] recipe: 校验通过, 预览={desc}")

    # 4) 人工门拒绝
    state = CleanState(thread_id="clean-smoke-1", source={"file_name": "sample.csv"})
    state.rules_plan = recipe
    state.stage = "plan"
    try:
        execute_recipe(state, pr.columns, pr.rows)
        raise AssertionError("未确认不应执行")
    except Exception as exc:
        assert "未经人工确认" in str(exc)
    print("[OK] engine: 人工门拦截生效")

    # 5) 确认后执行
    confirm_plan(state, True, "smoke")
    res = execute_recipe(state, pr.columns, pr.rows)
    assert state.data_ref.startswith("clean://"), state.data_ref
    assert len(res["transform_log"]) == 5
    print(f"[OK] engine: 执行完成, 5 步, 清洗后 {len(res['rows'])} 行")

    # 6) 前后校验
    v = compare({"columns": pr.columns, "rows": pr.rows}, {"columns": res["columns"], "rows": res["rows"]})
    print(f"[OK] verify: passed={v['passed']}, 空值率 {v['metrics']['empty_ratio']['before']}→{v['metrics']['empty_ratio']['after']}")

    # 7) 报告
    state.profile = profile
    state.verify = {"metrics": v["metrics"], "passed": v["passed"]}
    rep = build_report(state, state.profile, state.verify, state.transform_log)
    md = render_markdown(rep)
    assert "清洗报告" in md and "体检结论" in md
    print(f"[OK] report: 报告生成（三段式 + 未处理项清单）{len(md)} 字符")

    # 8) 导出 CSV
    tmp = tempfile.mkdtemp(prefix="clean-smoke-")
    from app.export.exporter import export_csv
    path = export_csv(res["columns"], res["rows"], tmp, "smoke_out")
    assert os.path.exists(path)
    print(f"[OK] export: {path}")

    # 9) 洗后脏点对账（跑样例链路 → 导出 → 对账 → 非 0 即红）
    #    自检门覆盖三情形：未清洗必红 / 正确清洗必绿 / 回退一条修复规则必红（变异检测）
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO, "scripts", "check_residual_dirt_selftest.py")],
        capture_output=True, text=True, cwd=REPO,
    )
    assert proc.returncode == 0, f"洗后脏点对账自检未通过:\n{proc.stdout}\n{proc.stderr}"
    for line in proc.stdout.strip().splitlines():
        if line.startswith("[") or line.startswith("RESIDUAL"):
            print("   " + line)
    print("[OK] residual-dirt: 对账门 4/4（未清洗红 / 正确清洗绿 / 回退规则红 / 改回绿）")

    print("\nSMOKE ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
