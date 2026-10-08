"""契约测试：问题 ↔ 可处理操作 判据前后端**逐项一致**（唯一清单，禁止第二份）。

背景：
- 后端唯一来源：`app.report.reporter.HANDLED_BY_OPS`（+ `ISSUE_LABELS`）；
- 前端 `frontend/src/hooks/useSession.ts::ISSUE_HANDLERS` 必须与其逐项一致（含顺序、含 `unit` 的
  `cell_text_replace`）—— 不一致时"前端认为已覆盖、后端认为未覆盖"，就会出现"界面放行、接口 409"的错位。
- 货币词表单一来源：`operations/data/currency_affixes.py`；后端 `app/` 其余位置不得再写一份。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.report.reporter import HANDLED_BY_OPS, ISSUE_LABELS

REPO = Path(__file__).resolve().parents[2]   # 清洗项目仓库/
USE_SESSION = REPO / "frontend" / "src" / "hooks" / "useSession.ts"
APP = REPO / "backend" / "app" / "operations" / "data" / "currency_affixes.py"


def _frontend_handlers() -> dict:
    src = USE_SESSION.read_text(encoding="utf-8")
    m = re.search(r"ISSUE_HANDLERS[^=]*=\s*\{(.*?)\n\};", src, re.S)
    assert m, "前端 ISSUE_HANDLERS 表未找到（前端必须保留该表并与后端对齐）"
    out = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"\s*([a-z_]+)\s*:\s*\[(.*?)\]", line)
        if mm:
            out[mm.group(1)] = [x.strip().strip("'\"") for x in mm.group(2).split(",") if x.strip()]
    return out


@pytest.mark.skipif(not USE_SESSION.exists(), reason="前端源码不在场（纯后端交付场景）")
def test_frontend_handlers_match_backend():
    fe = _frontend_handlers()
    assert set(fe.keys()) == set(HANDLED_BY_OPS.keys()), (
        f"前后端问题键不一致：前端{sorted(fe)} 后端{sorted(HANDLED_BY_OPS)}")
    for key, ops in HANDLED_BY_OPS.items():
        assert fe[key] == list(ops), f"{key} 判据不一致：前端 {fe[key]} ≠ 后端 {list(ops)}"


def test_unit_issue_covered_by_unit_convert_and_text_replace():
    # 单位问题（含与数字粘连）必须有对应清洗操作可用
    assert "cell_unit_convert" in HANDLED_BY_OPS["unit"]
    assert "cell_text_replace" in HANDLED_BY_OPS["unit"]


def test_issue_labels_cover_all_issues():
    assert set(ISSUE_LABELS.keys()) == set(HANDLED_BY_OPS.keys())
    for key, label in ISSUE_LABELS.items():
        assert label and not label.isascii(), f"{key} 缺少中文名"


def test_currency_tokens_only_in_single_source():
    """货币词表只允许出现在 currency_affixes.py（不做第二份）。"""
    tokens = ["万元", "人民币", "USD", "RMB", "CNY", "EUR", "￥", "¥", "€"]
    non_currency = ["元数据", "元信息", "单元", "元素"]
    allowed = APP.resolve()
    offenders = []
    for path in (REPO / "backend" / "app").rglob("*.py"):
        if path.resolve() == allowed:
            continue
        text = path.read_text(encoding="utf-8")
        for tok in tokens + ["元"]:
            probe = text
            if tok == "元":
                for w in non_currency:
                    probe = probe.replace(w, "")
            if tok in probe:
                offenders.append(f"{path.relative_to(REPO)}: {tok}")
    assert not offenders, "货币词出现在单一来源之外：" + "；".join(sorted(set(offenders)))
