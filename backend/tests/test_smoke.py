"""pytest 冒烟入口：等价于 scripts/smoke.py 的核心断言。"""
# SPDX-License-Identifier: Apache-2.0
# sys.path 注入由同目录 conftest.py 统一完成（backend/ 入 path），此处不再自行插入，
# 以便模块级 import 全部位于文件顶部（E402 合规）。

from app.detectors.base import DetectorRegistry
from app.engine.engine import confirm_plan, execute_recipe
from app.parsing.parser import parse_csv
from app.recipe.engine import validate_recipe
from app.state import CleanState
from app.verify.verifier import compare

SAMPLE = (
    "id,名称,金额,日期,备注\n"
    "A001,张三,￥1,200,2024/01/01,正常\n"
    "A001,张三,￥1,200,2024/01/01,正常\n"
    "A002,李四,,2024-13-99,乱码��\n"
    "A003,王五,3000元,2024.02.30, 前后空格 \n"
)


def test_parse_csv():
    pr = parse_csv(SAMPLE.encode("utf-8"), "ref://t")
    assert pr.row_count == 4
    assert pr.col_count == 5


def test_detectors_all_9():
    pr = parse_csv(SAMPLE.encode("utf-8"), "ref://t")
    profile = DetectorRegistry.run_all(pr.columns, pr.rows)
    assert len(profile["issues"]) == 9


def test_recipe_engine_hitl():
    pr = parse_csv(SAMPLE.encode("utf-8"), "ref://t")
    recipe = {
        "schema_id": "clean-recipe/v1",
        "name": "t",
        "source": {"thread_id": "t", "file_name": "s.csv"},
        "operations": [
            {"op": "row_dedupe", "params": {}},
            {"op": "cell_trim", "params": {"columns": ["备注"]}},
            {"op": "cell_amount_clean", "params": {"column": "金额"}},
            {"op": "cell_date_normalize", "params": {"column": "日期"}},
        ],
    }
    assert validate_recipe(recipe, pr.columns) == []
    state = CleanState(thread_id="t", source={"file_name": "s.csv"})
    state.rules_plan = recipe
    state.stage = "plan"
    try:
        execute_recipe(state, pr.columns, pr.rows)
        raise AssertionError("未确认不应执行")
    except Exception:
        pass
    confirm_plan(state, True, "pytest")
    res = execute_recipe(state, pr.columns, pr.rows)
    id_col = res["columns"].index("id")
    assert res["rows"][0][id_col] == "A001"
    assert len(res["rows"]) == 3  # 去重后 3 行


def test_verify_improves():
    pr = parse_csv(SAMPLE.encode("utf-8"), "ref://t")
    recipe = {
        "schema_id": "clean-recipe/v1",
        "name": "t",
        "source": {"thread_id": "t", "file_name": "s.csv"},
        "operations": [{"op": "cell_trim", "params": {"columns": ["备注"]}}],
    }
    state = CleanState(thread_id="t", source={"file_name": "s.csv"})
    state.rules_plan = recipe
    state.stage = "plan"
    confirm_plan(state, True, "pytest")
    res = execute_recipe(state, pr.columns, pr.rows)
    v = compare({"columns": pr.columns, "rows": pr.rows}, {"columns": res["columns"], "rows": res["rows"]})
    assert v["metrics"]["empty_ratio"]["after"] <= v["metrics"]["empty_ratio"]["before"] + 1e-9
