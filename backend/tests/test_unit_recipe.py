# SPDX-License-Identifier: Apache-2.0
"""L1 单元测试：配方引擎。

覆盖：recipe.json 结构 / 字段级校验 / 未知操作标记 / 依赖列校验 /
内容签名 / 重放 / 导出含签名。
"""
import copy
import json

import pytest

from app.recipe.engine import (
    MAX_OPS,
    RECIPE_SCHEMA_ID,
    RecipeError,
    describe_recipe,
    export_recipe_json,
    new_recipe,
    recipe_signature,
    replay,
    validate_recipe,
)

COLS = ["id", "金额", "日期"]
ROWS = [
    ["A001", "￥1,200", "2024/01/01"],
    ["A001", "￥1,200", "2024/01/01"],
    ["A002", None, "2024-13-99"],
]

GOOD_OPS = [
    {"op": "row_dedupe", "params": {}},
    {"op": "cell_trim", "params": {"columns": ["id"]}},
    {"op": "cell_amount_clean", "params": {"column": "金额"}},
]


def make_recipe(ops=None, **overrides):
    recipe = new_recipe("t", {"thread_id": "t1", "file_name": "s.csv"},
                        copy.deepcopy(ops if ops is not None else GOOD_OPS))
    recipe.update(overrides)
    return recipe


# --- 结构 / 校验 ----------------------------------------------------------
def test_new_recipe_structure():
    r = new_recipe("n", {"thread_id": "t"}, [{"op": "row_dedupe", "params": {}}])
    assert r["schema_id"] == RECIPE_SCHEMA_ID
    assert r["name"] == "n"
    assert len(r["operations"]) == 1


def test_validate_ok():
    assert validate_recipe(make_recipe(), COLS) == []


def test_validate_wrong_schema():
    errors = validate_recipe(make_recipe(schema_id="other"), COLS)
    assert any("schema_id" in e for e in errors)


def test_validate_empty_ops():
    errors = validate_recipe(make_recipe(ops=[]), COLS)
    assert any("operations" in e for e in errors)


def test_validate_unknown_op():
    errors = validate_recipe(make_recipe(ops=[{"op": "no_such_op", "params": {}}]), COLS)
    assert any("未知" in e for e in errors)


def test_validate_missing_column_dependency():
    errors = validate_recipe(
        make_recipe(ops=[{"op": "cell_trim", "params": {"columns": ["不存在"]}}]), COLS)
    assert any("缺少列" in e for e in errors)


def test_validate_max_ops():
    ops = [{"op": "row_dedupe", "params": {}}] * (MAX_OPS + 1)
    errors = validate_recipe(make_recipe(ops=ops), COLS)
    assert any("上限" in e for e in errors)


def test_describe_recipe():
    lines = describe_recipe(make_recipe())
    assert len(lines) == len(GOOD_OPS)
    assert any("去重" in ln for ln in lines)


def test_describe_unknown_op():
    lines = describe_recipe(make_recipe(ops=[{"op": "no_such_op", "params": {}}]))
    assert any("未知操作" in ln for ln in lines)


# --- 签名 / 重放 ----------------------------------------------------------
def test_signature_deterministic_and_sensitive():
    r1, r2 = make_recipe(), make_recipe()
    assert recipe_signature(r1) == recipe_signature(r2)
    r2["operations"][0]["params"]["x"] = 1
    assert recipe_signature(r1) != recipe_signature(r2)


def test_replay_full():
    result = replay(make_recipe(), COLS, ROWS)
    assert len(result["rows"]) == 2  # 去重
    assert len(result["transform_log"]) == len(GOOD_OPS)
    assert result["columns"][0] == "id"


def test_replay_stops_on_unknown_op():
    # validate_recipe 在 replay 入口先做字段级校验（未知 op 属字段错误），故为 RECIPE_INVALID
    with pytest.raises(RecipeError) as ei:
        replay(make_recipe(ops=[{"op": "no_such_op", "params": {}}]), COLS, ROWS)
    assert ei.value.code == "RECIPE_INVALID"
    assert "未知" in ei.value.message


def test_replay_validates_dependency():
    with pytest.raises(RecipeError) as ei:
        replay(make_recipe(ops=[{"op": "cell_trim", "params": {"columns": ["不存在"]}}]), COLS, ROWS)
    assert ei.value.code == "RECIPE_INVALID"


def test_replay_does_not_mutate_input():
    before_rows = [list(r) for r in ROWS]
    replay(make_recipe(), COLS, ROWS)
    assert ROWS == before_rows


def test_export_recipe_json_includes_signature(tmp_path):
    p = tmp_path / "recipe.json"
    export_recipe_json(make_recipe(), str(p))
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["_signature"].startswith("sha256:")
    assert recipe_signature({k: v for k, v in data.items() if k != "_signature"}) == data["_signature"]
