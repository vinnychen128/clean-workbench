"""操作基类与注册机制。

约定：每个操作 = apply / validate / describe；注册表登记；新增操作不改他人。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class OpContext:
    """操作执行上下文。"""

    columns: List[str]
    rows: List[List[Any]]
    params: Dict[str, Any]


@dataclass
class OpResult:
    """操作结果：新行 / 新列 / 转换日志条目。"""

    rows: List[List[Any]]
    columns: List[str]
    log: Dict[str, Any] = field(default_factory=dict)
    ok: bool = True


class Operation(ABC):
    """操作基类。子类必须定义 op_name 并实现 apply / validate / describe。"""

    op_name: str = ""
    level: str = ""  # row / column / cell
    description: str = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.op_name and cls is not Operation:
            OperationRegistry._registry[cls.op_name] = cls

    @abstractmethod
    def apply(self, ctx: OpContext) -> OpResult:
        raise NotImplementedError

    @abstractmethod
    def validate(self, ctx: OpContext) -> List[str]:
        """校验参数与列存在性；返回错误列表（空 = 通过）。"""
        raise NotImplementedError

    @abstractmethod
    def describe(self, params: Dict[str, Any]) -> str:
        """人类可读描述（用于配方预览与转换日志）。"""
        raise NotImplementedError

    def _col_index(self, ctx: OpContext, col: str) -> Optional[int]:
        try:
            return ctx.columns.index(col)
        except ValueError:
            return None


class OperationRegistry:
    """操作注册表：所有 Operation 子类自动登记。"""

    _registry: Dict[str, type] = {}

    def __call__(cls, target):
        """装饰器用法：@OperationRegistry 注册类并原样返回。"""
        if isinstance(target, type) and issubclass(target, Operation):
            OperationRegistry._registry[target.op_name] = target
            return target
        raise TypeError("@OperationRegistry 仅可用于 Operation 子类")

    @classmethod
    def all(cls) -> Dict[str, type]:
        return dict(cls._registry)

    @classmethod
    def get(cls, name: str) -> Optional[type]:
        return cls._registry.get(name)

    @classmethod
    def is_known(cls, name: str) -> bool:
        return name in cls._registry
