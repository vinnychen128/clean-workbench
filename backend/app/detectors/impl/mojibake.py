"""检测器：编码乱码 mojibake：乱码字符 / 替换符 / 异常 Unicode 区块。"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import re
from typing import Any, Dict, List

from ..base import Detector


class MojibakeDetector(Detector):
    issue_name = "mojibake"
    description = "编码乱码检测：替换符 \\uFFFD、控制字符、孤立代理、典型 mojibake 序列"
    verbosity_levels = (0, 1, 2)

    _BAD_RE = re.compile(
        r"[\ufffd]|[\x00-\x08\x0b\x0c\x0e-\x1f]|[\ud800-\udfff]|"
        r"(\u00e4\u00b8|\u00e5\u00ad|\u00e6\u0096|\u00c3\u00a9|\u00c3\u00a0|\u00c3\u00a7)"
    )

    def compute(self, columns: List[str], rows: List[List[Any]]) -> Dict[str, Any]:
        hit_rows: List[int] = []
        for i, row in enumerate(rows):
            for c in row:
                if isinstance(c, str) and self._BAD_RE.search(c):
                    hit_rows.append(i)
                    break
        score = len(hit_rows) / max(len(rows), 1)
        severity = "high" if score >= 0.1 else ("medium" if score >= 0.01 else "low")
        return self.build_report(score, severity, hit_rows)
