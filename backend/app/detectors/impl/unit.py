"""检测器：单位 unit：同列物理量单位混用 / 未知单位。

判定（本检测器只判物理量单位，货币不归它管）：
- **货币形态的值一律不参与本检测器**（货币单位、货币符号与英文币称的**唯一词表**在
  `operations/data/currency_affixes.py`，本检测器只 import 判据、不再写第二份）。货币单位与符号
  **不在** `_KNOWN_UNITS` 里出现，避免"金额列被判同列混用"的假警报，
  也避免把带币称后缀的金额值报成"未知单位"。
- **同列混用**：同一列内「带单位值」与「裸数字值」共存，或出现 ≥2 种物理量单位 → 该列命中，
  行号取该列全部带单位行（上限 200 行，其余给计数）。
- **计数单位（量词）分流**：`件 / 台 / 个 / pcs` 等量词归 `operations/data/quantity_units.py`
  单一来源，**不算物理量混用**（量词之间不可换算）。数字与量词粘连且**构成同列混用**时（该列同时有
  裸数字值，或出现 ≥2 种量词），出独立子项 `kind=quantity_unit`（带 `suggest_op=cell_unit_convert`
  与 `suggest_params={"to":"纯数值"}`），行号照常计入命中 —— 清洗侧由该算子的「剥离单位」模式清除。
  **全列单一量词粘连（如整列都是 `3件`）不报**，避免噪声（反例边界）。
- **未知单位**：独立子项，行号取该单位所在行。
- **疑似金额列提示**：某列出现货币形态值时，给一条低优先级提示（`kind=currency_hint`），
  只提示"建议用金额清洗"，**不计入命中行数**。

不做：货币单位的判定与清洗、单位间数值换算是否合理、跨列单位是否一致。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List

from ...operations.data.currency_affixes import looks_like_amount
from ...operations.data.quantity_units import COUNT_UNITS
from ..base import Detector

# 物理量单位白名单（**不含任何货币单位 / 货币符号** —— 货币归 currency_affixes.py 单一来源；
# **不含计数单位（件/台/pcs…）** —— 计数单位归 quantity_units.py 单一来源，不可换算，单独成子项）
_KNOWN_UNITS = {
    "mm", "cm", "m", "km", "inch", "in", "ft", "kg", "g", "t", "lb", "oz",
    "MPa", "kPa", "Pa", "bar", "psi", "℃", "°C", "°F", "K",
    "ml", "L", "l", "m³", "m3", "kg/m²",
}
# 数字与单位粘连（允许中间空格）：3件 / 2.5 kg / 100 %
_UNIT_CELL = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*([^\d\s.+\-]{1,6})$")
_BARE_NUMBER = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
# 单次返回的行号上限（超出部分只给计数，避免报告体量失控）
MAX_ROWS = 200


class UnitDetector(Detector):
    issue_name = "unit"
    description = ("单位检测（物理量单位 kg/m/MPa/℃ 等）：同一列内带单位值与裸数字混用、"
                   "或出现两种以上物理量单位即命中；未知单位单列子项；"
                   "计数单位/量词（件/台/个/pcs 等）与裸数字混用、或同列量词混用时单列子项，"
                   "建议剥离单位只留数值（全列单一量词粘连不报）。"
                   "不检测：货币单位与货币符号（归金额清洗，本检测器只给「疑似金额列」提示、不计入命中）、"
                   "单位间数值换算是否合理、跨列单位是否一致")
    verbosity_levels = (0, 1, 2)

    def compute(self, columns: List[str], rows: List[List[Any]]) -> Dict[str, Any]:
        width = max([len(r) for r in rows] + [len(columns)])
        with_unit: Dict[int, List[Any]] = defaultdict(list)   # 列号 -> [(行号, 物理量单位)]
        count_unit_rows: Dict[int, List[Any]] = defaultdict(list)  # 列号 -> [(行号, 计数单位)]
        bare_count: Dict[int, int] = defaultdict(int)         # 列号 -> 裸数字行数
        currency_cols: Dict[int, int] = defaultdict(int)      # 列号 -> 货币形态值个数（仅提示）

        for i, row in enumerate(rows):
            for ci in range(min(len(row), width)):
                v = row[ci]
                if not isinstance(v, str):
                    continue
                s = v.strip()
                if s == "":
                    continue
                if looks_like_amount(s):
                    # 货币 / 千分位 / 全角数值形态：归金额口径（符号表），不进单位判定
                    currency_cols[ci] += 1
                    continue
                m = _UNIT_CELL.match(s)
                if m:
                    u = m.group(2)
                    # 计数单位（件/台/pcs…）不可换算：单独归类，走「剥离单位」建议，
                    # 不参与物理量单位混用判定，避免把数量列误报成物理量混用
                    if u in COUNT_UNITS:
                        count_unit_rows[ci].append((i, u))
                    else:
                        with_unit[ci].append((i, u))
                elif _BARE_NUMBER.match(s):
                    bare_count[ci] += 1

        hit_rows: set = set()
        sub_items: List[Dict[str, Any]] = []
        for ci in sorted(set(with_unit) | set(bare_count) | set(count_unit_rows)):
            entries = with_unit.get(ci, [])
            c_entries = count_unit_rows.get(ci, [])
            units = sorted({u for _, u in entries})
            c_units = sorted({u for _, u in c_entries})
            bare = bare_count.get(ci, 0)
            unknown = [u for u in units if u not in _KNOWN_UNITS]
            mixed = bool(entries) and (len(units) >= 2 or bare > 0)
            # 量词粘连（如 `3件`）只有在**同列构成混用**时才算命中：该列同时有裸数字值，
            # 或出现 ≥2 种量词。全列单一量词粘连不报（反例边界，避免噪声）。
            q_mixed = bool(c_entries) and (bare > 0 or len(c_units) >= 2)
            if not mixed and not unknown and not q_mixed:
                continue
            col_name = columns[ci] if ci < len(columns) else f"第 {ci + 1} 列"
            col_rows = [i for i, _ in entries]
            if mixed:
                reasons = []
                if len(units) >= 2:
                    reasons.append("同列出现多种物理量单位")
                if bare > 0:
                    reasons.append("同列带单位值与裸数字混用")
                hit_rows.update(col_rows)
                sub_items.append({
                    "kind": "mixed",
                    "column": col_name,
                    "units": units,
                    "with_unit_rows": len(entries),
                    "bare_rows": bare,
                    "rows": col_rows[:MAX_ROWS],
                    "reason": "；".join(reasons),
                })
            if unknown:
                unknown_rows = sorted({i for i, u in entries if u not in _KNOWN_UNITS})
                hit_rows.update(unknown_rows)
                sub_items.append({
                    "kind": "unknown_unit",
                    "column": col_name,
                    "units": unknown,
                    "rows": unknown_rows[:MAX_ROWS],
                    "reason": "出现未知单位",
                })
            if q_mixed:
                # 计数单位（量词）子项：数字与量词粘连且同列混用（含裸数字或多量词）。
                # 量词之间不可换算 → 建议「剥离单位、只留数值」（cell_unit_convert 剥离模式）
                c_rows = [i for i, _ in c_entries]
                hit_rows.update(c_rows)
                sub_items.append({
                    "kind": "quantity_unit",
                    "column": col_name,
                    "units": c_units,
                    "with_unit_rows": len(c_entries),
                    "bare_rows": bare,
                    "rows": c_rows[:MAX_ROWS],
                    "reason": "数字与计数单位（量词）粘连，不可换算；建议剥离单位只留数值",
                    "suggest_op": "cell_unit_convert",
                    # from 仅作展示（剥离去尾不依赖它），to 取「纯数值」触发剥离模式
                    "suggest_params": {"column": col_name, "from": "、".join(c_units), "to": "纯数值"},
                })

        # 疑似金额列提示：只提示、不计入命中
        for ci in sorted(currency_cols):
            col_name = columns[ci] if ci < len(columns) else f"第 {ci + 1} 列"
            sub_items.append({
                "kind": "currency_hint",
                "column": col_name,
                "currency_rows": currency_cols[ci],
                "reason": "疑似金额列（含货币前后缀/千分位），建议用「金额清洗」，不计入单位混用命中",
                "counted": False,
            })

        ordered = sorted(hit_rows)
        score = len(ordered) / max(len(rows), 1)
        severity = "high" if score >= 0.1 else ("medium" if score >= 0.02 else "low")
        report = self.build_report(score, severity, ordered[:MAX_ROWS])
        report["rows_total"] = len(ordered)
        report["rows_truncated"] = max(0, len(ordered) - MAX_ROWS)
        report["sub_items"] = sub_items
        report["columns"] = sorted({it["column"] for it in sub_items
                                    if it.get("kind") in ("mixed", "unknown_unit", "quantity_unit")})
        # 联动：问题级建议参数 —— 供前端「加入建议步骤」时预填（前端 ProfileIssue 允许扩展键）。
        # 只在命中类子项**全部**为计数单位时给出（`currency_hint` 是只提示不计命中的旁注，不参与判断）：
        # 此时剥离模式参数通用；含物理量混用/未知单位时无从给通用换算对，仍交由用户在步卡自选（不猜）。
        hit_kinds = {it.get("kind") for it in sub_items if it.get("kind") != "currency_hint"}
        if hit_kinds == {"quantity_unit"}:
            first = next(it for it in sub_items if it.get("kind") == "quantity_unit")
            report["suggest_op"] = first.get("suggest_op")
            report["suggest_params"] = first.get("suggest_params")
        return report
