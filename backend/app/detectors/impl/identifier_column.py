"""检测器：ID 列 identifier_column：主键候选列的唯一性 / 空值 / 重复检测。"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any, Dict, List

from ..base import Detector

_ID_HINTS = ("id", "编号", "号", "code", "no", "sn", "单号", "订单号", "流水号")


class IdentifierColumnDetector(Detector):
    issue_name = "identifier_column"
    description = "ID 列检测：疑似主键列含空值 / 重复值（唯一性约束风险）"
    verbosity_levels = (0, 1, 2)

    def _candidate_cols(self, columns: List[str]) -> List[int]:
        out = []
        for idx, col in enumerate(columns):
            cl = str(col).lower()
            if any(h in cl for h in _ID_HINTS):
                out.append(idx)
        return out

    def compute(self, columns: List[str], rows: List[List[Any]]) -> Dict[str, Any]:
        cands = self._candidate_cols(columns)
        if not cands:
            return self.build_report(0.0, "low", [])
        hit_rows: List[int] = []
        for idx, row in enumerate(rows):
            for ci in cands:
                if ci >= len(row):
                    continue
                v = row[ci]
                if v is None or (isinstance(v, str) and v.strip() == ""):
                    hit_rows.append(idx)
                    break
        # 重复主键候选值
        seen = set()
        for idx, row in enumerate(rows):
            for ci in cands:
                if ci >= len(row):
                    continue
                v = row[ci]
                if v is None or (isinstance(v, str) and v.strip() == ""):
                    continue
                if v in seen:
                    hit_rows.append(idx)
                seen.add(v)
        score = len(hit_rows) / max(len(rows), 1)
        severity = "high" if score >= 0.05 else ("medium" if score >= 0.01 else "low")
        return self.build_report(score, severity, sorted(set(hit_rows)))
