#!/usr/bin/env python3
"""洗前 / 洗后 对比示例生成器（README 示例的真实出处，可复现）。

输入 = 仓库自带合成样例（`samples/dirty_orders.csv` + `samples/recipe_orders_demo.json`）；
流程 = 解析 → 9 类检测器 → 配方校验 → 人工确认门 → 执行 → 前后校验 → 报告；
输出 = 洗前表 / 洗后表 / 处理日志 / 体检结论 / 校验指标（Markdown，可直接粘进 README）。

用法：
    python scripts/demo_before_after.py            # 打印 Markdown
    python scripts/demo_before_after.py --print-env  # 附带运行环境指纹行

失败即非零退出；不写任何仓库内文件。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "backend"))


def render_table(columns, rows):
    """rows 为与 columns 对齐的行列表（list[list]），None/空串渲染为 *(空)*。"""
    out = ["| " + " | ".join(str(c) for c in columns) + " |",
           "|" + "|".join(["---"] * len(columns)) + "|"]
    for r in rows:
        if isinstance(r, dict):
            values = [r.get(c, "") for c in columns]
        else:
            values = list(r)
        cells = []
        for v in values:
            v = "" if v is None else str(v)
            cells.append(v if v.strip() else "*(空)*")
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def main() -> int:
    from app.parsing.parser import parse_csv
    from app.detectors.base import DetectorRegistry
    from app.recipe.engine import validate_recipe, describe_recipe
    from app.engine.engine import confirm_plan, execute_recipe
    from app.verify.verifier import compare
    from app.report.reporter import build_report, render_markdown
    from app.state import CleanState

    dirty = os.path.join(REPO, "samples", "dirty_orders.csv")
    recipe_path = os.path.join(REPO, "samples", "recipe_orders_demo.json")
    with open(dirty, "rb") as fh:
        raw = fh.read()
    with open(recipe_path, "r", encoding="utf-8") as fh:
        recipe = json.load(fh)

    pr = parse_csv(raw, "demo://before-after")
    profile = DetectorRegistry.run_all(pr.columns, pr.rows)
    errs = validate_recipe(recipe, pr.columns)
    if errs:
        print("RECIPE INVALID:", errs, file=sys.stderr)
        return 1

    state = CleanState(thread_id="readme-demo", source={"file_name": os.path.basename(dirty)})
    state.rules_plan = recipe
    state.recipe_id = recipe.get("name")
    state.stage = "plan"
    confirm_plan(state, True, "demo")
    res = execute_recipe(state, pr.columns, pr.rows)
    v = compare({"columns": pr.columns, "rows": pr.rows},
                {"columns": res["columns"], "rows": res["rows"]})

    state.profile = profile
    state.verify = {"metrics": v["metrics"], "passed": v["passed"]}
    rep = build_report(state, state.profile, state.verify, state.transform_log)
    md = render_markdown(rep)

    print("### 洗前（samples/dirty_orders.csv，%d 行 × %d 列）" % (len(pr.rows), len(pr.columns)))
    print()
    print(render_table(pr.columns, pr.rows))
    print()
    print("### 洗后（同一份配方的执行结果，%d 行 × %d 列）" % (len(res["rows"]), len(res["columns"])))
    print()
    print(render_table(res["columns"], res["rows"]))
    print()
    print("### 体检结论（%d 类检测器命中）" % len(profile["issues"]))
    print()
    for it in profile["issues"]:
        rows = it.get("rows") or []
        print("- `%s` · %s · 涉及 %d 行%s" % (it["issue_name"], it["severity"], len(rows),
                                                ("（索引 " + ", ".join(str(r) for r in rows) + "）") if rows else ""))
    print()
    print("### 处理日志（%d 步，逐步可追溯）" % len(res["transform_log"]))
    print()
    for i, op in enumerate(describe_recipe(recipe), 1):
        # 配方描述自带序号（"1. xxx"），此处统一由脚本编号，避免出现 "1. 1. xxx"
        print("%d. %s" % (i, op.split(". ", 1)[-1] if op[:2].rstrip(".").strip().isdigit() else op))
    print()
    print("### 前后校验（引擎自动比对，非人工填报）")
    print()
    print("```json")
    print(json.dumps(v, ensure_ascii=False, indent=2))
    print("```")
    print()
    print("### 报告实样（引擎输出，节选前 40 行 / 共 %d 字符）" % len(md))
    print()
    print("```markdown")
    print("\n".join(md.splitlines()[:40]))
    print("```")
    if "--print-env" in sys.argv:
        import platform
        print()
        print("<!-- env: python=%s platform=%s -->" % (platform.python_version(), platform.platform()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
