# SPDX-License-Identifier: Apache-2.0
"""守卫：计数单位「单一来源」的文档声明必须与实现接入一致。

背景：`operations/data/quantity_units.py` 文件头写着「操作器 `cell_ops.py`
复用同一判据……本词表只此一份」，但实现层**从未 import 该词表**，剥离模式无任何量词判据，
`3kg` / `10元` 被静默洗成裸数字（文档声明与实现脱节）。

本文件同时守两层：
1. **静态接入**：`cell_ops.py` 必须 import 本词表，且不得再写第二份量词表；
2. **行为等价**：剥离模式必须**逐词**跟随 `COUNT_UNITS`（表内剥离、表外保留原值），
   避免「import 了但没用」这种假接入。
"""
from __future__ import annotations

import pathlib

import app.operations.impl.cell_ops as cell_ops_mod
from app.operations.base import OpContext, OperationRegistry
from app.operations.data import quantity_units

CELL_OPS_SRC = pathlib.Path(cell_ops_mod.__file__).read_text(encoding="utf-8")
QUANTITY_UNITS_SRC = pathlib.Path(quantity_units.__file__).read_text(encoding="utf-8")


def test_cell_ops_imports_single_source_table():
    """单一来源确已接入：`cell_ops.py` import 了 `is_count_unit` 并在剥离分支调用。"""
    assert "from ..data.quantity_units import is_count_unit" in CELL_OPS_SRC, \
        "cell_ops.py 未 import 计数单位词表 —— quantity_units.py 的「复用同一判据」声明即沦为哑声明"
    assert "is_count_unit(suffix)" in CELL_OPS_SRC, \
        "cell_ops.py 未在剥离分支调用 is_count_unit() —— 仅 import 不等于接入"
    # 反向守卫：不得在本文件再写第二份量词表（同一判据只写一份）
    assert "COUNT_UNITS" not in CELL_OPS_SRC, \
        "cell_ops.py 直接引用了 COUNT_UNITS（应只经 is_count_unit() 判据，避免第二份口径）"


def test_quantity_units_doc_states_impl_entry_point():
    """声明侧同样受守：文件头必须写明**实现接入位置**，防止「声明复用、实现缺席」复发。"""
    assert "实现接入位置" in QUANTITY_UNITS_SRC
    assert "cell_ops.py" in QUANTITY_UNITS_SRC and "skipped_non_count" in QUANTITY_UNITS_SRC


def test_strip_honours_table_unit_by_unit():
    """行为等价：词表里**每一个**量词都剥离，表外后缀一律保留原值并计数。"""
    units = sorted(quantity_units.COUNT_UNITS)
    assert units, "计数单位词表不得为空"
    assert quantity_units.is_count_unit("件") and not quantity_units.is_count_unit("kg")
    rows = [[f"7{u}"] for u in units] + [["7kg"], ["7元"], ["7万元"]]
    ctx = OpContext(columns=["数量"], rows=rows,
                    params={"column": "数量", "from": "件", "to": "纯数值"})
    op = OperationRegistry.get("cell_unit_convert")()
    assert op.validate(ctx) == []
    result = op.apply(ctx)
    assert result.ok
    got = [row[0] for row in result.rows]
    assert got == [7] * len(units) + ["7kg", "7元", "7万元"], got
    assert result.log["skipped_non_count"] == 3
