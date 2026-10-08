"""检测器：重复 duplicate。"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any, Dict, List

from ..base import Detector


class DuplicateDetector(Detector):
    issue_name = "duplicate"
    description = "完全重复行检测"
    verbosity_levels = (0, 1, 2)

    def compute(self, columns: List[str], rows: List[List[Any]]) -> Dict[str, Any]:
        seen = set()
        dup_rows: List[int] = []
        for i, row in enumerate(rows):
            key = tuple(str(c) for c in row)
            if key in seen:
                dup_rows.append(i)
            else:
                seen.add(key)
        score = len(dup_rows) / max(len(rows), 1)
        severity = "high" if score >= 0.1 else ("medium" if score >= 0.02 else "low")
        return self.build_report(score, severity, dup_rows)
