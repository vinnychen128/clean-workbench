# SPDX-License-Identifier: Apache-2.0
"""AI 辅助层服务组装 —— 供 server 层调用的三项能力（列建议 / 人话摘要 / 加入配方）。

红线落地：
- 本模块**从不改数据值**，只产出「建议」与「文本」，不调用任何算子执行；
- 发模型的 payload 全部经 `profile` / `redact` 生成，不含任何原始单元格值；
- 本模块属于 AI 侧，**不被清洗执行链 import**（CI 静态守卫断言）；
- 任何失败（未启用 / 不可达 / 超时 / 不合 schema）都收敛为
      `degraded=true` + 本地确定性兜底，绝不向调用方抛异常。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from ..operations.base import OpContext, OperationRegistry
from .client import AiClient, AiClientError, now_iso
from .config import AiConfig
from .profile import build_column_profiles
from .prompts import build_column_advice_messages, build_report_explain_messages
from .redact import redact_samples
from .schema import (REPORT_DISCLAIMER, SchemaError, parse_json_output,
                     validate_column_advice, validate_report_explain)

PURPOSE_ADVICE = "column_advice"
PURPOSE_REPORT = "report_explain"

# 「会发送什么」预览与实际 payload 共用同一份字段定义（单测断言两者一致）
BASE_OUTBOUND_FIELDS: Tuple[str, ...] = ("column_name", "cell_profile", "cell_counts", "length_stats")

# 探活结果短时缓存：避免打开设置页就外呼；首次查询或点「测试连接」时才真正探活
_PROBE_CACHE: Dict[str, Any] = {"at": 0.0, "reachable": False, "last_error": None, "probed": False}
_PROBE_TTL_S = 30.0


def outbound_fields(value_sharing: str) -> List[str]:
    """本次真实外发字段清单（唯一来源，预览与请求共用）。"""
    fields = list(BASE_OUTBOUND_FIELDS)
    if value_sharing == "redacted_samples":
        fields.append("redacted_samples")
    return fields


def profile_item_key_map() -> Dict[str, str]:
    """实际画像条目的键 → 外发字段名（单测据此比对预览）。"""
    return {
        "column": "column_name",
        "profile_distribution": "cell_profile",
        "total_count": "cell_counts",
        "non_empty_count": "cell_counts",
        "unique_count": "cell_counts",
        "length_min": "length_stats",
        "length_max": "length_stats",
        "samples": "redacted_samples",
    }


def _unmask_params(value: Any, reverse: Dict[str, str]) -> Any:
    """递归把建议参数里的外发遮罩列名（如「列#1」）还原为真实列名。

    配套：模型只见过外发列名，它给出的建议参数同样使用遮罩名；
    若不还原，「加入配方」提交时会因参数里的列名不在真实列集合中而 400
    （默认配置下，含姓名 / 手机 / 邮箱 / 订单号等敏感列的 AI 建议必现）。
    """
    if isinstance(value, dict):
        return {k: _unmask_params(v, reverse) for k, v in value.items()}
    if isinstance(value, list):
        return [_unmask_params(v, reverse) for v in value]
    if isinstance(value, str):
        return reverse.get(value, value)
    return value


def _reason_from_kind(kind: str) -> str:
    """把通道错误类型映射为契约里的 reason 取值。"""
    if kind in ("disabled", "no_provider", "no_httpx", "no_base_url"):
        return "disabled"
    if kind == "timeout":
        return "timeout"
    return "unreachable"


class AiService:
    """一次实例化读取一次配置快照（便于测试注入 env）。"""

    def __init__(self, config: Optional[AiConfig] = None):
        self.config = config or AiConfig()
        self.client = AiClient(self.config)

    # ── 状态与连通性 ──────────────────────────────────────────────
    def status(self, probe: bool = False) -> Dict[str, Any]:
        cfg = self.config
        usable = bool(cfg.enabled and cfg.provider == "openai_compatible")
        result: Dict[str, Any] = {
            "enabled": cfg.enabled,
            "provider": cfg.provider,
            "model": cfg.model,
            "value_sharing": cfg.value_sharing,
            "column_name_sharing": cfg.column_name_sharing,
            "base_url": cfg.base_url,
            "timeout_s": cfg.timeout_s,
            "max_sample": cfg.max_sample,
            "cache_enabled": cfg.cache_enabled,
            "key_configured": cfg.key_configured,
            "reachable": False,
            "probed": False,
            "checked_at": None,
            "last_error": None,
            "config_errors": cfg.validate(),
            "preview": self.sent_preview(),
        }
        if not usable:
            # 未启用 / 未选 provider：不构造任何请求，直接如实回答
            result["last_error"] = "disabled"
            return result

        now = time.time()
        fresh = bool(_PROBE_CACHE["probed"]) and (now - float(_PROBE_CACHE["at"])) < _PROBE_TTL_S
        if probe or not fresh:
            probed = self.client.probe()
            _PROBE_CACHE.update({
                "at": now,
                "reachable": bool(probed.get("reachable")),
                "last_error": probed.get("last_error"),
                "probed": True,
            })
        result["reachable"] = bool(_PROBE_CACHE["reachable"])
        result["probed"] = bool(_PROBE_CACHE["probed"])
        result["last_error"] = _PROBE_CACHE["last_error"]
        result["checked_at"] = now_iso()
        return result

    # ── 列语义与方案建议 ──────────────────────────────────────────
    def column_advice(
        self,
        columns: List[str],
        rows: List[List[Any]],
        requested: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "model": self.config.model,
            "degraded": False,
            "reason": None,
            "advice": [],
        }
        if not self.config.enabled or self.config.provider != "openai_compatible":
            base.update(degraded=True, reason="disabled")
            return base

        wanted = [c for c in (requested or columns) if c in columns]
        if not wanted:
            base.update(degraded=True, reason="bad_schema")
            return base

        # ① 本地算形态画像（不含值）→ ② 列名按 sharing 规则可外发化
        profiles, label_map = self._profiles_for_request(columns, rows, wanted)
        outbound = list(label_map.values())
        fields = outbound_fields(self.config.value_sharing)
        if any(self.config.column_name_masked(c, i) for i, c in enumerate(columns)):
            fields = ["column_name:masked" if f == "column_name" else f for f in fields]
        messages = build_column_advice_messages(profiles, outbound)

        text, degraded_reason, cached, ledger = self._call(
            messages, PURPOSE_ADVICE, input_fields=fields
        )
        if degraded_reason:
            self._flush(ledger, degraded=True, reason=degraded_reason, schema_ok=False)
            base.update(degraded=True, reason=degraded_reason)
            return base

        parsed, schema_error = self._validate_advice(text, outbound)
        if schema_error:
            # 输出不合规 → 自动重试 1 次（绕过缓存）；仍不合规 → 降级
            text, degraded_reason, cached, ledger = self._call(
                messages, PURPOSE_ADVICE, use_cache=False, input_fields=fields
            )
            if degraded_reason:
                self._flush(ledger, degraded=True, reason=degraded_reason, schema_ok=False)
                base.update(degraded=True, reason=degraded_reason)
                return base
            parsed, schema_error = self._validate_advice(text, outbound)
            if schema_error:
                self._flush(ledger, degraded=True, reason="bad_schema", schema_ok=False)
                base.update(degraded=True, reason="bad_schema")
                return base

        # 只对「确实被遮罩」的列建还原表（外发名 == 真名时无需也不应改写）
        reverse = {label: real for real, label in label_map.items() if label != real}
        advice = []
        for raw_item in parsed["advice"]:
            item = dict(raw_item)
            item["column"] = reverse.get(item["column"], item["column"])
            # 建议参数里的列名同样来自外发遮罩名，必须与 column 一并对齐回真名，
            # 否则点「加入配方」提交时 params 找不到列 → 400（敏感列默认配置下必现）
            item["suggested_ops"] = [
                {**op, "params": _unmask_params(op.get("params") or {}, reverse)}
                for op in (item.get("suggested_ops") or [])
            ]
            if not item["evidence"]:
                item["evidence"] = self._evidence_from_profile(profiles, label_map, raw_item["column"])
            item["cached"] = bool(cached)
            advice.append(item)
        self._flush(ledger, degraded=False, reason=None, schema_ok=True)
        base.update(advice=advice, cached=bool(cached))
        return base

    # ── 体检报告人话版 ────────────────────────────────────────────
    def report_explain(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "text": self.deterministic_explain(summary),
            "model": self.config.model,
            "degraded": False,
            "reason": None,
            "cached": False,
            "disclaimer": REPORT_DISCLAIMER,
        }
        if not self.config.enabled or self.config.provider != "openai_compatible":
            base.update(degraded=True, reason="disabled")
            return base

        messages = build_report_explain_messages(summary)
        fields = ["row_count", "column_count", "issue_summary", "quality_metrics"]
        text, degraded_reason, cached, ledger = self._call(
            messages, PURPOSE_REPORT, input_fields=fields
        )
        if degraded_reason:
            self._flush(ledger, degraded=True, reason=degraded_reason, schema_ok=False)
            base.update(degraded=True, reason=degraded_reason)
            return base

        parsed, schema_error = self._validate_report(text)
        if schema_error:
            text, degraded_reason, cached, ledger = self._call(
                messages, PURPOSE_REPORT, use_cache=False, input_fields=fields
            )
            if degraded_reason:
                self._flush(ledger, degraded=True, reason=degraded_reason, schema_ok=False)
                base.update(degraded=True, reason=degraded_reason)
                return base
            parsed, schema_error = self._validate_report(text)
            if schema_error:
                self._flush(ledger, degraded=True, reason="bad_schema", schema_ok=False)
                base.update(degraded=True, reason="bad_schema")
                return base

        self._flush(ledger, degraded=False, reason=None, schema_ok=True)
        base.update(text=self._render_explain(parsed), cached=bool(cached))
        return base

    # ── 把人工确认过的建议落成标准配方步骤 ─────────────────────
    def build_recipe_step(
        self,
        columns: List[str],
        column: str,
        op: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """只做校验与构造，不落任何状态（落状态由 server 层走 build_plan 统一口径）。"""
        cls = OperationRegistry.get(op or "")
        if cls is None:
            return {"ok": False, "error": "unknown_op"}
        if column not in columns:
            return {"ok": False, "error": "column_not_found"}
        params = dict(params or {})
        # 建议步骤未显式指定列时补上（契约：步骤必须自洽、可重放）
        if "column" not in params and "columns" not in params:
            params["column"] = column
        ctx = OpContext(columns=list(columns), rows=[], params=params)
        try:
            errors = cls().validate(ctx)
        except Exception as exc:  # 参数形态异常一律当作 params_invalid，不抛给调用方
            return {"ok": False, "error": "params_invalid", "detail": str(exc)}
        if errors:
            return {"ok": False, "error": "params_invalid", "detail": "；".join(errors[:5])}
        return {"ok": True, "step": {"op": op, "params": params}}

    # ── 「会发送什么」预览（与实际请求同源，单测断言）────
    def sent_preview(self) -> Dict[str, Any]:
        """预览本机即将发出的字段与形态标签样例（**不含任何数据值**）。"""
        fields = outbound_fields(self.config.value_sharing)
        if self.config.column_name_sharing == "masked":
            fields = ["column_name:masked" if f == "column_name" else f for f in fields]
        return {
            "fields": fields,
            "example": {
                "column_name": "列#1" if self.config.column_name_sharing == "masked" else "订单金额",
                "cell_profile": ["CURRENCY_PREFIX 62%", "NUM+OTHER_UNIT 31%", "EMPTY 7%"],
                "cell_counts": {"total": 1204, "non_empty": 1120, "unique": 843},
                "length_stats": {"min": 2, "max": 12},
            },
            "never_sent": ["完整行", "原始单元格值", "文件路径", "配方内容", "清洗后数据", "任何凭证"],
            "key_source": "环境变量 CLEAN_AI_API_KEY（或仓库根 .env）",
            "key_configured": self.config.key_configured,
        }

    # ── 内部：画像构造 ──────────────────────────────────────────────────
    def _profiles_for_request(
        self, columns: List[str], rows: List[List[Any]], wanted: List[str]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        """返回（只含可外发字段的画像列表，原列名→可外发列名 映射）。"""
        index_map = {name: i for i, name in enumerate(columns)}
        all_profiles = build_column_profiles(columns, rows, max_rows=5000)
        by_col = {p["column"]: p for p in all_profiles}
        profiles: List[Dict[str, Any]] = []
        label_map: Dict[str, str] = {}
        for name in wanted:
            src = by_col.get(name)
            if src is None:
                continue
            label = self.config.column_label(name, index_map.get(name, 0))
            label_map[name] = label
            item = {
                "column": label,
                "total_count": src["total_count"],
                "non_empty_count": src["non_empty_count"],
                "non_empty_rate": src["non_empty_rate"],
                "unique_count": src["unique_count"],
                "length_min": src["length_min"],
                "length_max": src["length_max"],
                "profile_distribution": src["profile_distribution"],
            }
            if self.config.value_sharing == "redacted_samples":
                idx = index_map.get(name, 0)
                values = [row[idx] if idx < len(row) else None for row in rows[:5000]]
                item["samples"] = redact_samples(values, limit=self.config.max_sample)
            profiles.append(item)
        return profiles, label_map

    @staticmethod
    def _evidence_from_profile(
        profiles: List[Dict[str, Any]], label_map: Dict[str, str], column_label: str
    ) -> List[str]:
        for profile in profiles:
            if profile["column"] == column_label:
                return [
                    f'{d["profile"]} {round(d["ratio"] * 100)}%'
                    for d in profile["profile_distribution"][:3]
                    if d["ratio"] > 0
                ]
        return []

    # ── 内部：调用与校验 ────────────────────────────────────────────────
    def _call(
        self,
        messages: List[Dict[str, str]],
        purpose: str,
        use_cache: bool = True,
        input_fields: Optional[List[str]] = None,
    ) -> Tuple[Optional[str], Optional[str], bool, Dict[str, Any]]:
        """返回（文本, 降级原因, 是否缓存命中, 台账行）；降级原因非空即失败。"""
        try:
            out = self.client.complete(messages, purpose=purpose, use_cache=use_cache)
        except AiClientError as exc:
            ledger = getattr(exc, "entry", None) or self.client.ledger_entry(key="", purpose=purpose)
            ledger["input_fields"] = list(input_fields or [])
            return None, _reason_from_kind(exc.kind), False, ledger
        ledger = out["ledger"]
        ledger["input_fields"] = list(input_fields or [])
        return out["text"], None, bool(out.get("cached")), ledger

    @staticmethod
    def _validate_advice(
        text: Optional[str], outbound_columns: List[str]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        try:
            return validate_column_advice(parse_json_output(text or ""), outbound_columns), None
        except SchemaError as exc:
            return None, str(exc)

    @staticmethod
    def _validate_report(text: Optional[str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        try:
            return validate_report_explain(parse_json_output(text or "")), None
        except SchemaError as exc:
            return None, str(exc)

    def _flush(
        self, ledger: Dict[str, Any], degraded: bool, reason: Optional[str], schema_ok: bool
    ) -> None:
        if not ledger:
            return
        ledger["schema_ok"] = bool(schema_ok)
        ledger["degraded"] = bool(degraded)
        ledger["reason"] = reason
        self.client.write_ledger(ledger)

    # ── 本地确定性文本（降级兜底，永不缺席）────────────────────────────
    @staticmethod
    def deterministic_explain(summary: Dict[str, Any]) -> str:
        parts = [f'本次处理 {summary.get("row_count", 0)} 行 × {summary.get("column_count", 0)} 列。']
        if summary.get("profile_conclusion"):
            parts.append(str(summary["profile_conclusion"]).rstrip("。") + "。")
        if summary.get("quality_conclusion"):
            parts.append(str(summary["quality_conclusion"]).rstrip("。") + "。")
        unhandled = summary.get("unhandled_count")
        if unhandled is not None:
            parts.append(f"未处理项 {unhandled} 项。")
        return "".join(parts)

    @staticmethod
    def _render_explain(parsed: Dict[str, Any]) -> str:
        lines = [parsed["summary"]]
        for bullet in parsed.get("bullets", []):
            lines.append(f"· {bullet}")
        actions = parsed.get("next_actions", [])
        if actions:
            lines.append("建议下一步：")
            for idx, action in enumerate(actions, 1):
                lines.append(f"{idx}. {action}")
        return "\n".join(lines)
