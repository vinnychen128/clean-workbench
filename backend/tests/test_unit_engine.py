# SPDX-License-Identifier: Apache-2.0
"""L1 单元测试：执行引擎。

覆盖：build_plan / 风险标注 / 人工确认门（未确认拒绝执行）/ 执行成功 /
前后校验回退 ≤2 次 / 超限转 AWAITING_HITL。
"""
import pytest

from app.engine.engine import (
    MAX_RETRY,
    EngineError,
    begin_verify_round,
    build_plan,
    confirm_plan,
    execute_recipe,
)
from app.state import CleanState

COLS = ["id", "金额", "备注"]
ROWS = [
    ["A001", "￥1,200", "  正常  "],
    ["A001", "￥1,200", "  正常  "],
    ["A002", None, "乱码��"],
]

RECIPE = {
    "schema_id": "clean-recipe/v1",
    "name": "t",
    "source": {"thread_id": "t", "file_name": "s.csv"},
    "operations": [
        {"op": "row_dedupe", "params": {}},
        {"op": "cell_trim", "params": {"columns": ["备注"]}},
        {"op": "cell_amount_clean", "params": {"column": "金额"}},
    ],
}


def make_state(stage="idle"):
    return CleanState(thread_id="t", source={"file_name": "s.csv"}, stage=stage)


# --- build_plan -----------------------------------------------------------
def test_build_plan_ok():
    state = make_state()
    res = build_plan(state, RECIPE)
    assert res["recipe_id"]
    assert len(res["steps"]) == 3
    assert len(res["description"]) == 3
    assert state.stage == "plan"


def test_build_plan_invalid_raises():
    state = make_state()
    bad = dict(RECIPE, operations=[{"op": "no_such_op", "params": {}}])
    with pytest.raises(EngineError) as ei:
        build_plan(state, bad)
    assert ei.value.code == "PLAN_INVALID"


def test_build_plan_risk_flags_delete():
    state = make_state()
    r = dict(RECIPE, operations=[{"op": "row_delete", "params": {"column": "id", "value": "A001"}}])
    res = build_plan(state, r)
    assert any("删除类操作" in f for f in res["risk_flags"])


def test_build_plan_risk_flags_mean_fill():
    state = make_state()
    r = dict(RECIPE, operations=[{"op": "cell_fill_missing", "params": {"column": "金额", "method": "mean"}}])
    res = build_plan(state, r)
    assert any("均值填充" in f for f in res["risk_flags"])


# --- 人工确认门 ------------------------------------------------------------
def test_confirm_plan_approve():
    state = make_state("plan")
    res = confirm_plan(state, True, "ok")
    assert res == {"confirmed": True, "reason": "ok", "stage": "confirmed"}
    assert state.confirmed is True


def test_confirm_plan_reject():
    state = make_state("plan")
    confirm_plan(state, False, "no")
    assert state.stage == "rejected"
    assert state.confirmed is False


def test_confirm_plan_wrong_stage():
    state = make_state("idle")
    with pytest.raises(EngineError) as ei:
        confirm_plan(state, True)
    assert ei.value.code == "STATE_MISMATCH"


def test_execute_recipe_without_confirm_raises():
    """红队：未确认不得执行，不产生任何清洗产物。"""
    state = make_state()
    build_plan(state, RECIPE)
    with pytest.raises(EngineError) as ei:
        execute_recipe(state, COLS, ROWS)
    assert ei.value.code == "NOT_CONFIRMED"
    assert state.stage == "awaiting_confirm"
    assert state.transform_log == []


def test_execute_recipe_no_plan():
    state = make_state("confirmed")
    state.confirmed = True
    with pytest.raises(EngineError) as ei:
        execute_recipe(state, COLS, ROWS)
    assert ei.value.code == "NO_PLAN"


def test_execute_recipe_ok():
    state = make_state()
    build_plan(state, RECIPE)
    confirm_plan(state, True, "pytest")
    res = execute_recipe(state, COLS, ROWS)
    assert len(res["rows"]) == 2  # 去重后
    assert len(res["transform_log"]) == 3
    assert state.stage == "executed"
    assert state.data_ref.startswith("clean://")


def test_execute_recipe_dependency_failure_sets_error():
    """未知列依赖：build_plan 不阻断（列依赖在 replay 时校验），execute 时报错且不产数据。"""
    state = make_state()
    bad = dict(RECIPE, operations=[{"op": "cell_date_normalize", "params": {"column": "不存在"}}])
    build_plan(state, bad)
    confirm_plan(state, True, "pytest")
    with pytest.raises(EngineError) as ei:
        execute_recipe(state, COLS, ROWS)
    assert ei.value.code == "RECIPE_INVALID"
    assert state.transform_log == []


# --- 前后校验回退 ----------------------------------------------------------
def test_verify_pass():
    state = make_state("executed")
    v = begin_verify_round(state, True, {"x": 1})
    assert v["passed"] is True
    assert state.stage == "verified"
    assert state.retry_count == 0


def test_verify_fail_retryable():
    state = make_state("executed")
    v = begin_verify_round(state, False, {"x": 1})
    assert v["passed"] is False
    assert v["retryable"] is True
    assert state.stage == "verify_failed"
    assert state.retry_count == 1


def test_verify_fail_exceed_max_hitl():
    state = make_state("executed")
    for _ in range(MAX_RETRY + 1):
        begin_verify_round(state, False, {"x": 1})
    assert state.stage == "awaiting_hitl"
    assert state.retry_count == MAX_RETRY + 1
    assert state.errors
