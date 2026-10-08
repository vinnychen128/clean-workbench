"""检测器基类与插件注册机制。

约定：每个检测器 = 独立类：description / issue_name / verbosity_levels / 纯函数算分。
分数键自动派生为 `<issue_name>_score`（基类统一生成）。
新增检测器：继承 Detector 并实现 compute()，无需改动既有类。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}


class Detector(ABC):
    """检测器基类。子类必须定义 issue_name 并实现 compute()。"""

    issue_name: str = ""
    description: str = ""
    verbosity_levels: tuple = (0, 1, 2)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.issue_name and cls is not Detector:
            DetectorRegistry._registry[cls.issue_name] = cls

    def __init__(self, verbosity: int = 1):
        self.verbosity = min(verbosity, max(self.verbosity_levels))

    @abstractmethod
    def compute(self, columns: List[str], rows: List[List[Any]]) -> Dict[str, Any]:
        """纯函数算分。返回统一报告字段：issue_name / <issue>_score / severity / rows / verbosity。"""
        raise NotImplementedError

    def build_report(self, score: float, severity: str, rows: List[int]) -> Dict[str, Any]:
        """基类统一生成报告字段（含自动派生分数键）。"""
        report = {
            "issue_name": self.issue_name,
            f"{self.issue_name}_score": round(float(score), 4),
            "severity": severity,
            "rows": rows[:1000],  # 行号上限，避免超大列表
            "verbosity": self.verbosity,
        }
        return report


class DetectorRegistry:
    """插件注册表：所有 Detector 子类自动登记。"""

    _registry: Dict[str, type] = {}

    def __call__(cls, target):
        """装饰器用法：@DetectorRegistry 注册类并原样返回。"""
        if isinstance(target, type) and issubclass(target, Detector):
            DetectorRegistry._registry[target.issue_name] = target
            return target
        raise TypeError("@DetectorRegistry 仅可用于 Detector 子类")

    @classmethod
    def all(cls) -> Dict[str, type]:
        return dict(cls._registry)

    @classmethod
    def get(cls, name: str) -> type:
        return cls._registry[name]

    @classmethod
    def run_all(cls, columns: List[str], rows: List[List[Any]], verbosity: int = 1) -> Dict[str, Any]:
        """一次运行全部检测器；单个检测器异常不影响其余（独立捕获并记入 errors）。"""
        issues: List[Dict[str, Any]] = []
        detector_errors: List[Dict[str, Any]] = []
        for name, det_cls in cls._registry.items():
            try:
                det = det_cls(verbosity=verbosity)
                issues.append(det.compute(columns, rows))
            except Exception as exc:  # 独立捕获
                detector_errors.append({"issue_name": name, "message": str(exc)})
        # 按严重度降序稳定排序（高 → 低）
        issues.sort(key=lambda i: -SEVERITY_ORDER.get(i.get("severity", "low"), 0))
        return {"issues": issues, "detector_errors": detector_errors}
