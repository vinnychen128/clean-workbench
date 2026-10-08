# SPDX-License-Identifier: Apache-2.0
"""三件套机器闸门：能力声明 / 必测样例 / 真实数据对账入口 —— 缺项即红。

机制：
- 每个 `Detector` / `Operation` 必须：① 有非空 `description`（能力声明）；
  ② 在 `docs/contracts/detector_operation_contract.md` 有一行，且该行写明**真实存在的测试用例**
  （`路径::用例名`）；③ 写明真实数据对账入口（脏点模式表行 / 洗后指标键，或显式声明"无对应"+原因）。
- 因此：**新增检测器/操作不登记 → 红；登记的测试用例被删 → 红；对账模式名被改 → 红**（反向验证闸有效）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import app.detectors.impl  # noqa: F401  （导入即注册全部检测器）
import app.operations.impl  # noqa: F401
from app.detectors.base import DetectorRegistry
from app.operations.base import OperationRegistry

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "contracts" / "detector_operation_contract.md"
RECON_SCRIPT = REPO / "scripts" / "check_residual_dirt.py"
VERIFIER = REPO / "backend" / "app" / "verify" / "verifier.py"

EXPECTED_DETECTORS = 9
EXPECTED_OPERATIONS = 16
# 既有四键 + 新增五键（键名定死）
KNOWN_METRICS = {"rows", "columns", "empty_ratio", "dup_ratio",
                 "amount_dirty_ratio", "date_nonstandard_ratio", "date_invalid_count",
                 "unit_dirty_ratio", "numeric_dirty_ratio"}
NO_RECON_PREFIX = "无对应脏点模式"
COL_CAPABILITY = "能干什么"
COL_LIMIT = "不能干什么"
COL_SAMPLES = "必测样例（正 / 反 / 边界）"
COL_TEST_REF = "测试落点"
COL_RECON = "真实数据对账入口"
TEST_REF = re.compile(r"([A-Za-z0-9_./]+\.py)::([A-Za-z0-9_]+)")


def _clean(cell: str) -> str:
    return cell.strip()


def _doc_rows() -> dict[str, dict[str, str]]:
    """解析契约文档里的清单表（按表头取列，兼容"检测器表 6 列 / 操作表 7 列"）。"""
    rows: dict[str, dict[str, str]] = {}
    header: list[str] | None = None
    for line in DOC.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s.startswith("|"):
            header = None
            continue
        cells = [_clean(c) for c in s.strip("|").split("|")]
        name = cells[0].strip("`").strip() if cells else ""
        if name == "名称":
            header = cells
            continue
        if not any(cells) or set("".join(cells)) <= set("-: "):
            continue
        if header is None or not name:
            continue
        rows[name] = {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(header)}
    return rows


def test_registry_counts_as_contract():
    assert len(DetectorRegistry._registry) == EXPECTED_DETECTORS, sorted(DetectorRegistry._registry)
    assert len(OperationRegistry._registry) == EXPECTED_OPERATIONS, sorted(OperationRegistry._registry)


def test_every_registered_item_is_documented():
    """注册表 ↔ 契约文档 双向一致：漏登记（新增未写文档）与过期行（文档留着已删项）都红。"""
    rows = _doc_rows()
    registered = set(DetectorRegistry._registry) | set(OperationRegistry._registry)
    missing = sorted(registered - set(rows))
    stale = sorted(set(rows) - registered)
    assert not missing, f"注册表里有、契约文档没登记：{missing}"
    assert not stale, f"契约文档有的行，注册表里已不存在：{stale}"


@pytest.mark.parametrize("name", sorted(set(DetectorRegistry._registry) | set(OperationRegistry._registry)))
def test_item_has_declaration_samples_and_real_tests(name):
    """① 能力声明齐（code.description + 表里"能干什么/不能干什么"）；② 必测样例正/反/边界齐；③ 测试落点是真用例。"""
    cls = DetectorRegistry._registry.get(name) or OperationRegistry._registry.get(name)
    assert cls is not None, f"{name} 不在任何注册表里"
    rows = _doc_rows()
    assert name in rows, f"{name} 未登记进 {DOC.name}"
    row = rows[name]
    assert (cls.description or "").strip(), f"{name} 缺能力声明（description 为空）"
    assert row.get(COL_CAPABILITY), f"{name} 未写「能干什么」"
    assert row.get(COL_LIMIT), f"{name} 未写「不能干什么」（声明必须写清做不到的部分）"

    samples = row.get(COL_SAMPLES, "")
    for tag in ("正", "反", "边界"):
        assert tag in samples, f"{name} 必测样例缺「{tag}」档：{samples}"

    refs = TEST_REF.findall(row.get(COL_TEST_REF, ""))
    assert refs, f"{name} 「测试落点」未写 路径::用例名：{row.get(COL_TEST_REF)}"
    for rel, case in refs:
        path = REPO / rel
        assert path.exists(), f"{name} 指向的测试文件不存在：{rel}"
        assert re.search(rf"def {re.escape(case)}\(", path.read_text(encoding="utf-8")), \
            f"{name} 指向的用例不存在：{rel}::{case}"


@pytest.mark.parametrize("name", sorted(set(DetectorRegistry._registry) | set(OperationRegistry._registry)))
def test_item_recon_entry_is_real(name):
    """真实数据对账入口：模式名必须在入仓对账脚本里、指标键必须是 verifier 里真实存在的键。

    约定：对账入口里每个 `mode:…` / `metrics:…` 记号必须写在反引号内（便于机器提取）；
    声明"无对应脏点模式"时必须写成 `无对应脏点模式（原因）`，原因不得为空。
    """
    entry = _doc_rows()[name].get(COL_RECON, "")
    assert entry.strip(), f"{name} 缺「真实数据对账入口」"
    script_src = RECON_SCRIPT.read_text(encoding="utf-8")
    verifier_src = VERIFIER.read_text(encoding="utf-8")

    tokens = re.findall(r"`([^`]+)`", entry)
    assert tokens, f"{name} 对账入口未写可机检记号（mode:/metrics:/无对应脏点模式（原因））：{entry}"
    for tok in tokens:
        if tok.startswith("mode:"):
            mode = tok[len("mode:"):]
            assert mode in script_src, f"{name} 对账模式名在 {RECON_SCRIPT.name} 里找不到：{mode}"
        elif tok.startswith("metrics:"):
            key = tok[len("metrics:"):]
            assert key in KNOWN_METRICS, f"{name} 指标键不在约定集合内：{key}"
            assert key in verifier_src, f"{name} 指标键 {key} 在 verifier.py 里不存在"
        elif tok.startswith(NO_RECON_PREFIX):
            assert re.match(rf"{NO_RECON_PREFIX}（.+）", tok), f"{name} 声明无对账入口时必须写原因：{tok}"
        else:
            raise AssertionError(f"{name} 对账入口写法不合规（mode:/metrics:/{NO_RECON_PREFIX}（原因））：{tok}")
