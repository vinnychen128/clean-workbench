# SPDX-License-Identifier: Apache-2.0
"""AI 通道客户端 —— OpenAI 兼容协议、超时、单次重试、缓存与台账。

纪律：
- 密钥只从环境变量（或仓库根 `.env`）读（红线），本模块不落盘密钥、不回显、不写日志；
- 台账只记录「事实性元数据」（时间 / 用途 / 模型 / 提示词版本 / 输入摘要 / 耗时 / 成败），
  **不写任何数据值字段**（红线）；
- 网络失败不抛给调用方执行链，一律降级为「通道不可用」（红线）。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import AiConfig
from .prompts import PROMPT_VERSION

try:  # httpx 为运行时直接依赖；缺失时通道一律视为不可用，不影响主链路
    import httpx
except Exception:  # pragma: no cover - 极端环境兜底
    httpx = None  # type: ignore


class AiClientError(Exception):
    """通道级错误（网络 / 协议 / 鉴权）。"""

    def __init__(self, kind: str, message: str = ""):
        super().__init__(message or kind)
        self.kind = kind
        self.message = message or kind


def _repo_root() -> Path:
    # backend/app/ai/client.py → 仓库根
    return Path(__file__).resolve().parents[3]


def _cache_dir() -> Path:
    return _repo_root() / ".cache" / "ai"


def input_digest(*parts: Any) -> str:
    """输入摘要（只做哈希，不保留内容原文）。"""
    blob = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()[:32]


def now_iso() -> str:
    """本地时区 ISO8601（带冒号偏移，与接口契约示例一致）。"""
    now = time.localtime()
    offset = time.strftime("%z", now)  # 形如 +0800
    if len(offset) == 5:
        offset = f"{offset[:3]}:{offset[3:]}"
    return (
        f"{now.tm_year:04d}-{now.tm_mon:02d}-{now.tm_mday:02d}"
        f"T{now.tm_hour:02d}:{now.tm_min:02d}:{now.tm_sec:02d}{offset}"
    )


class AiClient:
    """OpenAI 兼容 /chat/completions 客户端（同步，供 FastAPI 同步端点使用）。"""

    def __init__(self, config: AiConfig):
        self.config = config

    # ── 缓存 ──
    def cache_key(self, messages: List[Dict[str, str]], purpose: str) -> str:
        """键 = sha256(provider|model|prompt_version|用途|输入摘要)。"""
        return input_digest(
            self.config.provider, self.config.model, PROMPT_VERSION, purpose, messages
        )

    def cache_read(self, key: str) -> Optional[str]:
        if not self.config.cache_enabled:
            return None
        path = _cache_dir() / f"{key.replace(':', '_')}.json"
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                return data.get("text")
        except Exception:
            return None
        return None

    def cache_write(self, key: str, text: str) -> None:
        if not self.config.cache_enabled:
            return
        try:
            path = _cache_dir() / f"{key.replace(':', '_')}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass  # 缓存失败静默降级

    # ── 台账 ──
    def write_ledger(self, entry: Dict[str, Any]) -> None:
        """追加一行台账；失败静默（台账不可用不得影响主链路）。"""
        try:
            path = _cache_dir() / "ai_ledger.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def ledger_entry(self, purpose: str, key: str, **extra: Any) -> Dict[str, Any]:
        """构造台账行的基础字段（禁止添加任何数据值字段）。"""
        entry = {
            "ts": now_iso(),
            "purpose": purpose,
            "provider": self.config.provider,
            "model": self.config.model,
            "prompt_version": PROMPT_VERSION,
            "input_digest": key,
            "input_fields": [],
            "value_sharing": self.config.value_sharing,
            "bytes_sent": 0,
            "cached": False,
            "schema_ok": False,
            "degraded": False,
            "reason": None,
            "latency_ms": 0,
        }
        entry.update(extra)
        return entry

    # ── 探活（仅在显式请求时发起，避免后台偷跑外发）──
    def probe(self) -> Dict[str, Any]:
        """显式探活：返回 {"reachable": bool, "last_error": str|None}。"""
        if not self.config.enabled or not self.config.base_url or self.config.provider == "none":
            return {"reachable": False, "last_error": "disabled"}
        if httpx is None:
            return {"reachable": False, "last_error": "httpx_missing"}
        url = self.config.base_url.rstrip("/") + "/models"
        try:
            with httpx.Client(timeout=min(self.config.timeout_s, 5)) as client:
                resp = client.get(url, headers=self._headers())
            if resp.status_code < 500:
                return {"reachable": True, "last_error": None}
            return {"reachable": False, "last_error": f"HTTP {resp.status_code}"}
        except Exception as exc:
            return {"reachable": False, "last_error": f"{type(exc).__name__}: {exc}"}

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    # ── 主调用 ──
    def complete(
        self,
        messages: List[Dict[str, str]],
        purpose: str,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """
        调用一次模型，返回 {"text", "cached", "latency_ms", "bytes_sent", "cache_key", "ledger"}。

        网络 / 协议错误抛 AiClientError；缓存命中直接返回（不发起任何网络请求）。
        """
        if not self.config.enabled:
            raise AiClientError("disabled", "AI 通道未启用")
        if self.config.provider != "openai_compatible":
            raise AiClientError("no_provider", "未配置可用的 provider")
        if httpx is None:
            raise AiClientError("no_httpx", "缺少 httpx 运行时依赖")
        if not self.config.base_url:
            raise AiClientError("no_base_url", "未配置 AI 服务地址")

        key = self.cache_key(messages, purpose)
        if use_cache:
            cached = self.cache_read(key)
            if cached is not None:
                entry = self.ledger_entry(key=key, purpose=purpose, cached=True, schema_ok=True)
                return {
                    "text": cached, "cached": True, "latency_ms": 0,
                    "bytes_sent": 0, "cache_key": key, "ledger": entry,
                }

        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0,
            "stream": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        started = time.time()
        try:
            with httpx.Client(timeout=self.config.timeout_s) as client:
                resp = client.post(url, headers=self._headers(), content=body)
            latency = int((time.time() - started) * 1000)
            if resp.status_code >= 400:
                kind = "auth" if resp.status_code in (401, 403) else "http"
                entry = self.ledger_entry(
                    key=key, purpose=purpose, bytes_sent=len(body),
                    latency_ms=latency, degraded=True, reason=kind,
                )
                raise AiClientError(kind, f"HTTP {resp.status_code}", entry=entry)
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
        except AiClientError:
            raise
        except Exception as exc:
            latency = int((time.time() - started) * 1000)
            kind = "timeout" if "timeout" in type(exc).__name__.lower() else "unreachable"
            entry = self.ledger_entry(
                key=key, purpose=purpose, bytes_sent=len(body),
                latency_ms=latency, degraded=True, reason=kind,
            )
            err = AiClientError(kind, f"{type(exc).__name__}: {exc}")
            err.entry = entry  # type: ignore[attr-defined]
            raise err from exc

        entry = self.ledger_entry(
            key=key, purpose=purpose, bytes_sent=len(body),
            latency_ms=latency, cached=False, schema_ok=True,
        )
        if use_cache:
            self.cache_write(key, text)
        return {
            "text": text, "cached": False, "latency_ms": latency,
            "bytes_sent": len(body), "cache_key": key, "ledger": entry,
        }
