"""检测器：空值 null。"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any, Dict, List

from ..base import Detector


class NullDetector(Detector):
    issue_name = "null"
    description = "空值检测：空字符串 / None / 纯空白视为缺失"
    verbosity_levels = (0, 1, 2)

    def compute(self, columns: List[str], rows: List[List[Any]]) -> Dict[str, Any]:
        total = max(len(rows), 1)
        hit_rows: List[int] = []
        for i, row in enumerate(rows):
            if any(c is None or (isinstance(c, str) and c.strip() == "") for c in row):
                hit_rows.append(i)
        ratio = len(hit_rows) / total
        severity = "high" if ratio >= 0.2 else ("medium" if ratio >= 0.05 else "low")
        return self.build_report(ratio, severity, hit_rows)
