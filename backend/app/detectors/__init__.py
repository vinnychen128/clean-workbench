"""检测器引擎包：9 个检测器插件式注册。"""
# SPDX-License-Identifier: Apache-2.0
from . import impl  # noqa: F401  触发 9 个检测器 __init_subclass__ 注册
