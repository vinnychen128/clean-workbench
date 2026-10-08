"""计数单位（量词）单一来源：件 / 个 / 台 / 套 / pcs …

为什么单独成文件（沿用「同一判据只写一份词表」的原则）：
- 检测器 `detectors/impl/unit.py` 用本词表把「数字 + 计数单位粘连」（如 `3件`）与
  「物理量单位混用」（如 `kg` 与 `g` 同列）**区分开**：前者不可换算、应剥离单位取数值；
- 操作器 `operations/impl/cell_ops.py::CellUnitConvertOp` 的「剥离单位」模式复用同一判据。
  **实现接入位置** = `CellUnitConvertOp.apply()` 的 `strip` 分支：先按 `_STRIP_SPLIT` 拆出
  「数值 + 后缀」，后缀为空或 `is_count_unit(suffix)` 为真才剥离；否则（物理量 / 货币 / 时间等
  非计数单位后缀）**保留原值**并计入 `OpResult.log["skipped_non_count"]`，由 `describe()` 与报告侧
  未处理项如实披露。
  该接入由 `backend/tests/test_quantity_units_guard.py` 守卫（防"文档声明复用、实现从未接入"复发）。

注意与 `currency_affixes.py` 的分工：货币符号 / 币称归货币词表，本表只管计数单位；
物理量单位（kg / m / MPa / ℃ …）不进本表，见 `unit.py::_KNOWN_UNITS`。
本词表 **只此一份**，任何模块不得再写第二份。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

# 计数单位（量词）：不可做单位换算法则上的换算，混用 / 与数值粘连时应剥离单位只留数值
COUNT_UNITS = frozenset({
    # 中文量词
    "件", "个", "台", "套", "箱", "瓶", "包", "条", "只", "枚", "袋", "盒",
    "张", "支", "块", "双", "片", "粒", "罐", "桶", "组", "份", "次", "人",
    "户", "家", "册", "辆", "艘", "架", "顶", "副", "把", "面", "盒装", "件装",
    # 英文 / 缩写计数单位
    "pcs", "PCS", "Pcs", "pc", "PC", "unit", "units", "set", "sets",
})


def is_count_unit(unit: str) -> bool:
    """是否为计数单位（量词）。空字符串 / 非字符串一律 False。"""
    return isinstance(unit, str) and unit.strip() in COUNT_UNITS
