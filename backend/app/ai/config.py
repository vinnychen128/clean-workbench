# SPDX-License-Identifier: Apache-2.0
"""AI 辅助层配置 —— 全部键走环境变量（或仓库根 `.env`）；密钥只在此处读（红线）。

纪律：
- 密钥只从「进程环境变量」或「仓库根 .env」读取，**不落日志、不落台账、不回显、不入仓**；
- 所有取值默认「关 / 空」：不配置 = 通道完全不可用（红线默认关）；
- 不引入任何 LLM 专用 SDK，只用 httpx 走 OpenAI 兼容协议。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 受控枚举（写死，清单即规则；模型输出表外值一律不合规）──
SEMANTIC_TYPES: List[str] = [
    "金额", "数量", "日期", "日期时间", "百分比",
    "姓名", "电话", "邮箱", "地址", "编号ID",
    "类别枚举", "自由文本",
]

CELL_PROFILES: List[str] = [
    "INT", "DECIMAL", "NUM+COUNT_UNIT", "NUM+OTHER_UNIT",
    "CURRENCY_PREFIX", "CURRENCY_SUFFIX", "PERCENT",
    "DATE_ISO", "DATE_SLASH", "DATE_DOT", "DATE_NONSTD", "DATETIME",
    "TEXT_CN", "TEXT_LATIN", "EMAIL_SHAPE", "PHONE_SHAPE", "ID_SHAPE", "CODE_ALNUM",
    "EMPTY", "PLACEHOLDER_DASH", "FULLWIDTH", "HAS_SPACE", "MIXED",
]

# ── 敏感列名词表与匹配规则（masked 模式；清单即规则，fail-closed）──
SENSITIVE_WORDS: List[str] = [
    "姓名", "名字", "联系人", "客户名", "客户", "法人", "身份证", "证件号",
    "手机", "手机号", "电话", "联系方式", "地址", "住址", "收货地址",
    "卡号", "银行账号", "账号", "账户", "邮箱", "邮件", "密码", "密钥", "税号",
]
SENSITIVE_SUFFIXES: List[str] = ["名", "号", "电话", "地址", "账号", "邮箱", "证件"]
SENSITIVE_BELONGS: List[str] = ["客户", "个人", "员工", "用户"]

# 英文对照表（「中英同表」）：按分隔符切词后整词匹配，覆盖英文列名的常见写法
SENSITIVE_WORDS_EN = frozenset({
    "name", "fullname", "username", "realname", "contact", "contactperson",
    "email", "mail", "phone", "mobile", "tel", "telephone", "cellphone",
    "address", "addr", "idcard", "idno", "identity", "passport",
    "account", "acct", "bankaccount", "cardno", "creditcard", "iban",
    "password", "passwd", "pwd", "secret", "token", "apikey",
    "taxno", "taxid", "ssn", "customer", "client", "employee", "staff",
    "user", "person", "personal",
})

VALUE_SHARING_MODES = ("shape_only", "redacted_samples")
COLUMN_NAME_MODES = ("on", "masked")
PROVIDERS = ("none", "openai_compatible")


def _repo_root() -> Path:
    # backend/app/ai/config.py → 仓库根
    return Path(__file__).resolve().parents[3]


def _load_repo_env() -> Dict[str, str]:
    """只读取仓库根 `.env`（若存在）；不覆盖进程环境变量，不改写任何文件。"""
    path = _repo_root() / ".env"
    if not path.is_file():
        return {}
    try:
        from dotenv import dotenv_values  # python-dotenv 已在依赖中
    except Exception:
        return {}
    try:
        return {k: v for k, v in dotenv_values(path).items() if v is not None}
    except Exception:
        return {}


def _as_bool(text: Optional[str], default: bool = False) -> bool:
    if text is None:
        return default
    return str(text).strip().lower() in ("1", "true", "yes", "on")


def _as_int(text: Optional[str], default: int) -> int:
    try:
        return int(str(text).strip())
    except Exception:
        return default


def is_sensitive_column(name: str) -> bool:
    """敏感列判定：子串匹配（大小写不敏感，中英同表）+ 后缀启发式 + 归属词兜底（fail-closed）。

    「中英同表」= 同一张词表同时覆盖中文与英文列名：英文按**分隔符切词**后整词匹配
    （`customer_name` → 命中 `name`），避免 `filename` 这类含 `name` 字面但语义无关的
    误伤；中文仍按子串匹配（中文无词边界）。
    """
    if not name:
        return True
    clean = str(name).strip().lower()
    if clean == "":
        return True
    if any(word in clean for word in SENSITIVE_WORDS):
        return True
    if any(clean.endswith(suffix) for suffix in SENSITIVE_SUFFIXES):
        return True
    if any(belong in clean for belong in SENSITIVE_BELONGS):
        return True
    # 英文同表：分词后整词匹配（大小写已在上面归一）
    tokens = [t for t in re.split(r"[^0-9a-z]+", clean) if t]
    if any(t in SENSITIVE_WORDS_EN for t in tokens):
        return True
    return False


class AiConfig:
    """一次性快照式配置（实例化时读环境，便于测试注入）。"""

    def __init__(self, env: Optional[Dict[str, str]] = None):
        base: Dict[str, str] = dict(_load_repo_env())
        runtime = dict(os.environ) if env is None else dict(env)
        merged: Dict[str, str] = {**base, **runtime}

        self.enabled: bool = _as_bool(merged.get("CLEAN_AI_ENABLED"), False)
        self.provider: str = (merged.get("CLEAN_AI_PROVIDER") or "none").strip() or "none"
        self.base_url: str = (merged.get("CLEAN_AI_BASE_URL") or "").strip()
        self.model: str = (merged.get("CLEAN_AI_MODEL") or "").strip()
        # 密钥：只读入内存，绝不外传
        self.api_key: str = merged.get("CLEAN_AI_API_KEY") or ""
        self.timeout_s: int = _as_int(merged.get("CLEAN_AI_TIMEOUT_S"), 20)
        self.max_sample: int = _as_int(merged.get("CLEAN_AI_MAX_SAMPLE"), 5)
        self.value_sharing: str = (merged.get("CLEAN_AI_VALUE_SHARING") or "shape_only").strip()
        self.column_name_sharing: str = (merged.get("CLEAN_AI_COLUMN_NAME_SHARING") or "on").strip()
        self.cache_enabled: bool = _as_bool(merged.get("CLEAN_AI_CACHE"), True)

    # ── 派生信息 ──
    @property
    def key_configured(self) -> bool:
        """界面只读展示用：已设置 / 未设置（绝不回显值）。"""
        return bool(self.api_key)

    def column_label(self, name: str, index: int) -> str:
        """按 sharing 规则产出可外发列名；命中敏感词或 masked 模式 → 列#<序号>。"""
        if self.column_name_sharing == "masked":
            return f"列#{index}"
        if is_sensitive_column(name):
            return f"列#{index}"
        return name

    def column_name_masked(self, name: str, index: int) -> bool:
        return self.column_label(name, index) != name

    # ── 校验 ──
    def validate(self) -> List[str]:
        errors: List[str] = []
        if self.provider not in PROVIDERS:
            errors.append(f"CLEAN_AI_PROVIDER 非法：{self.provider}")
        if self.value_sharing not in VALUE_SHARING_MODES:
            errors.append(f"CLEAN_AI_VALUE_SHARING 非法：{self.value_sharing}")
        if self.column_name_sharing not in COLUMN_NAME_MODES:
            errors.append(f"CLEAN_AI_COLUMN_NAME_SHARING 非法：{self.column_name_sharing}")
        if self.enabled and self.provider == "openai_compatible":
            if not self.base_url:
                errors.append("CLEAN_AI_BASE_URL 不能为空（provider=openai_compatible）")
            if not self.model:
                errors.append("CLEAN_AI_MODEL 不能为空（provider=openai_compatible）")
        return errors

    def public_view(self) -> Dict[str, Any]:
        """对外可见的配置快照（**不含密钥本身**）。"""
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "value_sharing": self.value_sharing,
            "column_name_sharing": self.column_name_sharing,
            "key_configured": self.key_configured,
            "timeout_s": self.timeout_s,
        }


# 端点一律不接收密钥字段：出现即 400
FORBIDDEN_BODY_KEYS = ("api_key", "apikey", "key", "token", "secret", "password")
