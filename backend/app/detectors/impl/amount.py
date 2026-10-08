"""检测器：金额 amount：金额格式不规范（千分位 / 货币前后缀 / 全角数字）。"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any, Dict, List

from ...operations.data.currency_affixes import is_canonical_amount, looks_like_amount
from ..base import Detector


class AmountDetector(Detector):
    issue_name = "amount"
    description = ("金额检测：货币符号/英文代码/中文后缀混用、千分位写法不一致、全角数字。"
                   "不检测：日期、手机号（归属 date / format）")
    verbosity_levels = (0, 1, 2)

    def compute(self, columns: List[str], rows: List[List[Any]]) -> Dict[str, Any]:
        # 逐列收集命中行（样本 / 指标需要"问题出在哪一列"；行为与"每行只记一次"等价）
        col_rows: Dict[str, set] = {}
        for i, row in enumerate(rows):
            for ci, c in enumerate(row):
                if not isinstance(c, str):
                    continue
                # 识别口径与 CellAmountCleanOp 同源（符号表）：含货币前后缀/千分位/全角数字才纳入，
                # 日期与手机号形态显式排除——旧守卫 `[,\\-]` 会把 `2024-01-18`、`138-5907-3635` 误计为金额缺口。
                if looks_like_amount(c) and not is_canonical_amount(c):
                    name = columns[ci] if ci < len(columns) else f"第 {ci + 1} 列"
                    col_rows.setdefault(name, set()).add(i)
        hit_rows = sorted({i for s in col_rows.values() for i in s})
        score = len(hit_rows) / max(len(rows), 1)
        severity = "high" if score >= 0.1 else ("medium" if score >= 0.02 else "low")
        report = self.build_report(score, severity, hit_rows)
        # 新增字段（不改既有键）：命中列按命中行数降序
        report["columns"] = [name for name, _ in sorted(col_rows.items(), key=lambda kv: -len(kv[1]))]
        return report
