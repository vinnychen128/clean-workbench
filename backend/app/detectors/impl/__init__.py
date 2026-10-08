"""9 个检测器实现（插件式，各独立文件，互不依赖）。"""
# SPDX-License-Identifier: Apache-2.0
from .amount import AmountDetector
from .date import DateDetector
from .duplicate import DuplicateDetector
from .format import FormatDetector
from .identifier_column import IdentifierColumnDetector
from .mojibake import MojibakeDetector
from .null import NullDetector
from .outlier import OutlierDetector
from .unit import UnitDetector

__all__ = [
    "AmountDetector", "DateDetector", "DuplicateDetector", "FormatDetector",
    "IdentifierColumnDetector", "MojibakeDetector", "NullDetector",
    "OutlierDetector", "UnitDetector",
]
