# SPDX-License-Identifier: Apache-2.0
"""CI 守卫：AI 辅助层的结构性红线（静态断言，不依赖网络与模型）。

断言四件事：
1. **执行链不得 import AI 包**（红线）：operations / engine / verify / graph /
   recipe / report / export / detectors / parsing / persistence 一律不得引用 `app.ai`；
   只有 server 层（`app/server/app.py`，HTTP 装配处）允许。
2. **全仓唯一外发点** = `backend/app/ai/client.py`（红线的物理保证：
   数据只可能从这一处离开本机，且该处默认关闭）。
3. **模型关键词只允许出现在 `app/ai/` 包内**（与 test_regression 的零 LLM 扫描互为补充）。
4. **AI 台账不得出现值字段**（红线的运行态取证）：台账 JSONL 只记
   字段名/耗时/命中，不落任何单元格值。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_APP = REPO_ROOT / "backend" / "app"
AI_PKG = BACKEND_APP / "ai"
AI_CLIENT = AI_PKG / "client.py"

# 执行链：清洗「解析 → 规划 → 执行 → 校验 → 报告 → 导出」的全部模块
CHAIN_DIRS = ("operations", "engine", "verify", "graph", "recipe", "report",
              "export", "detectors", "parsing", "persistence")
ALLOWED_AI_IMPORTERS = {"backend/app/server/app.py"}

_AI_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+[\w.]*\bai\b", re.MULTILINE)
_LLM_KEYWORDS = [r"\bopenai\b", r"\banthropic\b", r"\blangchain\b", r"\blangsmith\b",
                 r"\bdeepseek\b", r"\bqwen\b", r"\bdashscope\b", r"\bcohere\b"]
_LLM_RE = re.compile("|".join(_LLM_KEYWORDS), re.IGNORECASE)
_OUTBOUND_RE = re.compile(
    r"requests\.(get|post|put|delete|patch)\(|urllib\.request|"
    r"httpx\.(get|post|put|delete|patch|Client)\(|aiohttp|"
    r"http[s]?://(?!127\.0\.0\.1|localhost|testserver)")

# 台账/缓存里不允许出现的值字段（只允许键名与统计量）
_FORBIDDEN_LEDGER_KEYS = {"value", "values", "raw", "raw_values", "samples",
                          "sample", "rows", "cell_values", "content", "payload_text"}


def _py_files(root: Path):
    """仓库自有 Python 文件（排除虚拟环境与缓存）。"""
    skip = (".venv", "node_modules", "__pycache__", ".git")
    return [p for p in root.rglob("*.py") if not any(part in skip for part in p.parts)]


def _chain_files():
    files = []
    for name in CHAIN_DIRS:
        d = BACKEND_APP / name
        if d.exists():
            files.extend(p for p in d.rglob("*.py") if "__pycache__" not in p.parts)
    state = BACKEND_APP / "state.py"
    if state.exists():
        files.append(state)
    return files


def test_ai_package_exists_and_is_isolated_dir():
    """AI 代码必须物理集中在一个包内（便于审计与守卫）。"""
    assert AI_PKG.is_dir(), "缺少 backend/app/ai/ 包"
    for required in ("config.py", "profile.py", "redact.py", "schema.py", "prompts.py",
                     "client.py", "service.py"):
        assert (AI_PKG / required).is_file(), f"AI 包缺少 {required}"


def test_execution_chain_never_imports_ai():
    """执行链模块不得 import AI 包（红线）。"""
    offenders = []
    for p in _chain_files():
        text = p.read_text(encoding="utf-8", errors="ignore")
        if _AI_IMPORT_RE.search(text):
            offenders.append(str(p.relative_to(REPO_ROOT)))
    assert not offenders, "执行链出现 AI 依赖（违反）：" + "；".join(offenders)


def test_only_server_layer_imports_ai():
    """允许 import AI 包的只有 server 装配层，且必须在白名单内。"""
    importers = []
    for p in _py_files(BACKEND_APP):
        if AI_PKG in p.parents:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if _AI_IMPORT_RE.search(text):
            importers.append(str(p.relative_to(REPO_ROOT)))
    unexpected = sorted(set(importers) - ALLOWED_AI_IMPORTERS)
    assert not unexpected, f"AI 包被白名单外的模块 import：{unexpected}"


def test_only_ai_client_reaches_out():
    """全仓唯一外发点 = backend/app/ai/client.py（红线）。"""
    offenders = []
    for p in _py_files(BACKEND_APP):
        if p == AI_CLIENT:
            continue
        text = "\n".join(line for line in p.read_text(encoding="utf-8", errors="ignore").splitlines()
                         if not line.strip().startswith("#"))
        if _OUTBOUND_RE.search(text):
            offenders.append(str(p.relative_to(REPO_ROOT)))
    assert not offenders, "AI 通道之外出现外发调用：" + "；".join(offenders)
    assert AI_CLIENT.is_file() and _OUTBOUND_RE.search(AI_CLIENT.read_text(encoding="utf-8")), \
        "唯一外发点缺失（AI 通道应集中在 client.py）"


def test_llm_keywords_confined_to_ai_package():
    """模型关键词只允许出现在 app/ai/ 包内（其余代码 = 清洗链，保持零 LLM）。"""
    offenders = []
    for p in _py_files(REPO_ROOT / "backend"):
        if AI_PKG in p.parents:
            continue
        text = "\n".join(line for line in p.read_text(encoding="utf-8", errors="ignore").splitlines()
                         if not line.strip().startswith("#"))
        if _LLM_RE.search(text):
            offenders.append(str(p.relative_to(REPO_ROOT)))
    assert not offenders, f"清洗链代码出现模型关键词：{offenders}"


def test_ledger_has_no_value_fields(tmp_path, monkeypatch):
    """AI 台账（运行态落盘）不含任何值字段。"""
    from app.ai import client as ai_client
    from app.ai.config import AiConfig

    monkeypatch.setattr(ai_client, "_cache_dir", lambda: tmp_path / "ai-cache")
    ai = ai_client.AiClient(AiConfig({}))
    ai.write_ledger(ai.ledger_entry(purpose="column_advice", key="digest-abc", cached=False,
                                    bytes_sent=1234, schema_ok=True, degraded=False,
                                    reason=None, latency_ms=88))
    ledger = tmp_path / "ai-cache" / "ai_ledger.jsonl"
    assert ledger.is_file(), "台账未落盘"
    entry = json.loads(ledger.read_text(encoding="utf-8").strip())
    for key in entry:
        assert key not in _FORBIDDEN_LEDGER_KEYS, f"台账出现值字段 {key}"
    assert entry["input_fields"] == []
    assert entry["bytes_sent"] == 1234 and entry["latency_ms"] == 88
    # 台账原文不得含任何值样态（手机号 / 邮箱 / 金额符号）
    raw = ledger.read_text(encoding="utf-8")
    assert not re.search(r"\d{3}[- ]?\d{4}[- ]?\d{4}", raw), "台账疑似落入了原始值"
