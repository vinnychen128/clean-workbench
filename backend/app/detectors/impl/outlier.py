"""检测器：异常值 outlier（IQR / Z-Score）。"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import statistics
from typing import Any, Dict, List

from ..base import Detector


class OutlierDetector(Detector):
    issue_name = "outlier"
    description = "异常值检测：数值列 IQR 1.5 倍距 + Z-Score 阈值 3"
    verbosity_levels = (0, 1, 2)

    def _numeric_rows(self, rows: List[List[Any]]) -> List[List[float]]:
        out = []
        for row in rows:
            vals = []
            for c in row:
                if isinstance(c, (int, float)) and not isinstance(c, bool):
                    vals.append(float(c))
                elif isinstance(c, str):
                    s = c.replace(",", "").strip()
                    try:
                        vals.append(float(s))
                    except ValueError:
                        pass
            if vals:
                out.append(vals)
        return out

    def compute(self, columns: List[str], rows: List[List[Any]]) -> Dict[str, Any]:
        numeric_rows = self._numeric_rows(rows)
        all_vals = [v for row in numeric_rows for v in row]
        hit_rows: List[int] = []
        if len(all_vals) < 4:
            return self.build_report(0.0, "low", [])
        q1 = statistics.quantiles(all_vals, n=4)[0]
        q3 = statistics.quantiles(all_vals, n=4)[2]
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        mean = statistics.mean(all_vals)
        stdev = statistics.stdev(all_vals) if len(all_vals) > 1 else 0.0
        for idx, row in enumerate(rows):
            is_outlier = False
            for c in row:
                try:
                    v = float(str(c).replace(",", "")) if isinstance(c, str) else float(c)
                except (ValueError, TypeError):
                    continue
                if v < lower or v > upper:
                    is_outlier = True
                elif stdev > 0 and abs(v - mean) / stdev > 3:
                    is_outlier = True
            if is_outlier:
                hit_rows.append(idx)
        score = len(hit_rows) / max(len(rows), 1)
        severity = "high" if score >= 0.05 else ("medium" if score >= 0.01 else "low")
        return self.build_report(score, severity, hit_rows)
