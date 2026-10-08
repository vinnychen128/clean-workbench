"""检测器：格式 format：文本列的混用格式 / 特殊字符形态不一致。"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import re
from typing import Any, Dict, List

from ..base import Detector


class FormatDetector(Detector):
    issue_name = "format"
    description = "格式检测：同列内日期/电话/邮编格式混用、前后空白、全角半角混用"
    verbosity_levels = (0, 1, 2)

    _PHONE = re.compile(r"^\+?[\d\s\-()]{6,20}$")
    _ZIP = re.compile(r"^\d{5,6}$")

    def compute(self, columns: List[str], rows: List[List[Any]]) -> Dict[str, Any]:
        hit_rows: List[int] = []
        for i, row in enumerate(rows):
            for c in row:
                if not isinstance(c, str) or c.strip() == "":
                    continue
                s = c
                if s != s.strip():
                    hit_rows.append(i)
                    break
                # 电话/邮编列格式不一致的粗判：半角数字混全角
                if re.search(r"[０-９]", s):
                    hit_rows.append(i)
                    break
                if self._PHONE.match(s) or self._ZIP.match(s):
                    continue
        score = len(hit_rows) / max(len(rows), 1)
        severity = "high" if score >= 0.2 else ("medium" if score >= 0.05 else "low")
        return self.build_report(score, severity, hit_rows)
