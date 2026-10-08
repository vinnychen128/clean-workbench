"""操作引擎包：16 个清洗操作（行级 3 + 列级 5 + 单元格级 8，唯一具名清单）。"""
# SPDX-License-Identifier: Apache-2.0
from . import impl  # noqa: F401  触发 16 个操作 __init_subclass__ 注册
