"""检测器：日期 date：同列日期格式混用 / 非法日期。"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List

from ..base import Detector

_DATE_PATTERNS = (
    ("%Y-%m-%d", r"^\d{4}-\d{1,2}-\d{1,2}$"),
    ("%Y/%m/%d", r"^\d{4}/\d{1,2}/\d{1,2}$"),
    ("%Y.%m.%d", r"^\d{4}\.\d{1,2}\.\d{1,2}$"),
    ("%Y年%m月%d日", r"^\d{4}年\d{1,2}月\d{1,2}日$"),
    ("%d/%m/%Y", r"^\d{1,2}/\d{1,2}/\d{4}$"),
)


class DateDetector(Detector):
    issue_name = "date"
    description = "日期检测：列内日期格式混用（YYYY-MM-DD / YYYY/MM/DD / 中文日期等）或非法日期"
    verbosity_levels = (0, 1, 2)

    def _looks_like_date(self, s: str) -> bool:
        return any(re.match(p, s) for _, p in _DATE_PATTERNS)

    def _parse_any(self, s: str) -> bool:
        for fmt, _ in _DATE_PATTERNS:
            try:
                datetime.strptime(s, fmt)
                return True
            except ValueError:
                continue
        return False

    def compute(self, columns: List[str], rows: List[List[Any]]) -> Dict[str, Any]:
        # 逐列收集命中行（新增字段：样本 / 指标需要"问题出在哪一列"）
        col_rows: Dict[str, set] = {}
        invalid_cols: Dict[str, int] = {}
        for i, row in enumerate(rows):
            for ci, c in enumerate(row):
                if not isinstance(c, str):
                    continue
                s = c.strip()
                if not self._looks_like_date(s):
                    continue
                if not self._parse_any(s):
                    name = columns[ci] if ci < len(columns) else f"第 {ci + 1} 列"
                    col_rows.setdefault(name, set()).add(i)  # 非法日期
                    invalid_cols[name] = invalid_cols.get(name, 0) + 1
                    break
        hit_rows = sorted({i for s in col_rows.values() for i in s})
        score = len(hit_rows) / max(len(rows), 1)
        severity = "high" if score >= 0.1 else ("medium" if score >= 0.01 else "low")
        report = self.build_report(score, severity, hit_rows)
        report["columns"] = [name for name, _ in sorted(col_rows.items(), key=lambda kv: -len(kv[1]))]
        report["invalid_rows_by_column"] = invalid_cols
        return report
