"""清洗报告：三段式报告 + 「未处理项」清单 + Markdown/JSON 渲染。

三段式：①体检结论（检测器发现+严重度） ②执行过程（配方+转换日志） ③质量对比（前后指标）。
另含 ④未处理项：检出的问题若无配方操作可处理、检测器执行失败、校验未达标、步骤被跳过，
一律如实列出，绝不标记为已处理（零编造 / fail-loud）。
仅汇总本地状态生成，不引入外部数据。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

# 检测器 issue_name → 可处理该问题的操作 op_name（依据唯一具名清单）
# 本表是「体检命中 → 配方覆盖 → 报告未处理项 → 前端 riskGate」的**唯一判据来源**，
# 前端 `frontend/src/hooks/useSession.ts` 的 `ISSUE_HANDLERS` 与之逐项对齐（契约测试把关）。
# 文本替换可处理"单位/金额/日期"残留（如 数量列的"件"后缀、货币后缀），故一并列入。
HANDLED_BY_OPS: Dict[str, tuple] = {
    "null": ("cell_fill_missing", "row_delete", "row_keep"),
    "duplicate": ("row_dedupe",),
    "outlier": ("row_delete", "row_keep"),
    "format": ("cell_trim", "cell_fullwidth", "cell_case", "cell_text_replace"),
    "amount": ("cell_amount_clean", "cell_text_replace"),
    "date": ("cell_date_normalize", "cell_text_replace"),
    "unit": ("cell_unit_convert", "cell_text_replace"),
    "identifier_column": ("row_dedupe", "row_keep"),
    "mojibake": ("cell_text_replace",),
}

# 检测器 issue_name → 中文名（首屏/报告/覆盖校验共用文案）
ISSUE_LABELS: Dict[str, str] = {
    "null": "空值",
    "duplicate": "重复行",
    "outlier": "异常值",
    "format": "格式不一致",
    "amount": "金额不规范",
    "date": "日期不规范",
    "unit": "单位混用",
    "identifier_column": "标识列异常",
    "mojibake": "乱码",
}


def _unmet_text(item: Any) -> str:
    """契约：unmet 为对象数组；此处兼容取出可读文案（并兼容历史字符串形态）。"""
    if isinstance(item, dict):
        return str(item.get("message") or item.get("key") or item)
    return str(item)


def collect_unhandled(profile: Dict[str, Any], recipe: Dict[str, Any],
                      verify: Dict[str, Any], transform_log: List[Dict[str, Any]],
                      overrides: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """收集未处理 / 未识别项（如实列出，不掩盖）。

    overrides：越权放行的记录；命中的项补标「经用户确认未处理」+ 用户填写的说明，
    仍是"未处理"，绝不改成"已处理"。
    """
    ops = {op.get("op") for op in (recipe or {}).get("operations", []) if isinstance(op, dict)}
    override_issues = set()
    override_reason = ""
    if isinstance(overrides, dict) and overrides.get("ack"):
        override_reason = str(overrides.get("note") or overrides.get("reason") or "")
        override_issues = {u.get("issue_name") for u in (overrides.get("uncovered") or []) if isinstance(u, dict)}
        override_issues |= {str(n) for n in (overrides.get("skipped") or [])}
    items: List[Dict[str, Any]] = []
    for issue in (profile or {}).get("issues", []) or []:
        name = issue.get("issue_name", "")
        affected = issue.get("rows") or []
        entry = {
            "issue_name": name,
            "column": issue.get("column"),
            "severity": issue.get("severity", ""),
            "affected_rows": len(affected) or int(issue.get("rows_total") or 0),
        }
        resolvers = HANDLED_BY_OPS.get(name)
        if resolvers is None:
            entry["reason"] = "未知问题类型：无可处理操作，保持原样待人工判断"
        elif not (set(resolvers) & ops):
            entry["reason"] = "配方未包含可处理该问题的操作，保持原样"
        else:
            continue
        if name in override_issues:
            entry["user_acknowledged"] = True
            entry["reason"] = f"{entry['reason']}；**经用户确认未处理**（越权放行说明：{override_reason or '未填写'}）"
        items.append(entry)
    for err in (profile or {}).get("detector_errors", []) or []:
        items.append({
            "issue_name": err.get("issue_name", "detector"),
            "column": None,
            "severity": "unknown",
            "affected_rows": 0,
            "reason": f"检测器执行失败，该项未识别：{err.get('message', err)}",
        })
    for unmet in (verify or {}).get("unmet", []) or []:
        text = _unmet_text(unmet)
        key = unmet.get("key") if isinstance(unmet, dict) else "verify"
        entry = {
            "issue_name": "verify" if key not in ISSUE_LABELS else key,
            "column": None,
            "severity": "unknown",
            "affected_rows": (unmet.get("rows") if isinstance(unmet, dict) else 0) or 0,
            "reason": f"前后校验未达标项：{text}",
            "unmet_key": key,
        }
        # 语义非法日期：不是"没洗干净"，是"洗不了"，用词区分开
        if key == "date_invalid_count":
            entry["reason"] = f"不可清洗项（日期不存在，保留原值）：{text}"
        items.append(entry)
    for entry in transform_log or []:
        if isinstance(entry, dict) and entry.get("skipped"):
            items.append({
                "issue_name": entry.get("op", ""),
                "column": entry.get("column"),
                "severity": "unknown",
                "affected_rows": 0,
                "reason": f"步骤 {entry.get('step')} 被跳过：{entry.get('skip_reason') or '原因未记录'}",
            })
    # 剥离单位时被量词守卫拦下的非计数单位后缀值（如 `2kg`）**保留原值**，
    # 属"不能剥离"而非"已洗净"，必须如实计入未处理项清单，不得静默。
    for entry in transform_log or []:
        if not isinstance(entry, dict):
            continue
        skipped_non = int(entry.get("skipped_non_count") or 0)
        if skipped_non <= 0:
            continue
        samples = [str(s) for s in (entry.get("skipped_non_samples") or [])]
        items.append({
            "issue_name": entry.get("op", ""),
            "column": entry.get("target"),
            "severity": "unknown",
            "affected_rows": skipped_non,
            "reason": (f"步骤 {entry.get('step')} 剥离单位时跳过 {skipped_non} 个非计数单位值（保留原值）："
                       f"{entry.get('skipped_non_reason') or '非计数单位后缀未剥离'}"
                       + (f"；样本：{'、'.join(samples)}" if samples else "")),
        })
    return items


def build_report(state: Any, profile: Dict[str, Any], verify: Dict[str, Any],
                 transform_log: List[Dict[str, Any]]) -> Dict[str, Any]:
    """汇总三段式报告 + 未处理项清单。"""
    issues = profile.get("issues", [])
    high = [i for i in issues if i.get("severity") == "high"]
    medium = [i for i in issues if i.get("severity") == "medium"]
    low = [i for i in issues if i.get("severity") == "low"]

    metrics = (verify or {}).get("metrics", {})
    unmet = (verify or {}).get("unmet", []) or []
    passed = bool((verify or {}).get("passed", False))
    overrides = getattr(state, "overrides", None) or {}
    unhandled = collect_unhandled(profile, getattr(state, "rules_plan", {}) or {}, verify or {},
                                  transform_log or [], overrides)
    return {
        "thread_id": state.thread_id,
        "source": state.source,
        "unhandled": unhandled,
        "sections": {
            "1_profile": {
                "title": "体检结论",
                "severity_summary": {"high": len(high), "medium": len(medium), "low": len(low)},
                "issues": issues,
                "conclusion": _profile_conclusion(len(high), len(medium), passed, len(unmet)),
            },
            "2_process": {
                "title": "执行过程",
                "recipe_id": state.recipe_id,
                "recipe": state.rules_plan,
                "transform_log": transform_log,
            },
            "3_quality": {
                "title": "质量对比",
                "metrics": metrics,
                "passed": passed,
                "unmet": unmet,
                # 后端部分：结论文案必须写清「未达标 N 项」，不许只给通过/未通过
                "conclusion": _quality_conclusion(passed, unmet),
                # 越权放行留痕（跳过项 + 说明 + 时间）；无越权时本区块不出现
                **(dict(overrides=[overrides]) if isinstance(overrides, dict) and overrides.get("ack") else {}),
            },
            "4_unhandled": {
                "title": "未处理项",
                "count": len(unhandled),
                "unhandled": unhandled,
                "conclusion": ("全部检出问题均有配方操作覆盖，无遗留未处理项" if not unhandled
                               else f"存在 {len(unhandled)} 项未处理 / 未识别，未标记为已清洗"),
            },
        },
    }


def _profile_conclusion(high: int, medium: int, passed: Optional[bool] = None,
                        unmet_count: int = 0) -> str:
    if high:
        base = f"检出 {high} 项高危问题，建议先处理高危项再执行清洗"
    elif medium:
        base = f"检出 {medium} 项中危问题，可结合配方一并处理"
    else:
        base = "未检出明显问题，可直接进入配方与执行"
    if passed is False:
        base += f"；**质量校验未达标 {unmet_count} 项**（明细见「三、质量对比」）"
    return base


def _quality_conclusion(passed: bool, unmet: List[Any]) -> str:
    """结论里必须写清「未达标 N 项」，并给出前 3 条明细，不许只给一个判定字。"""
    if passed:
        return "通过 · 可交付（未达标 0 项）"
    details = "；".join(_unmet_text(item) for item in (unmet or [])[:3])
    more = f"（另有 {len(unmet) - 3} 项，见明细）" if len(unmet or []) > 3 else ""
    return f"未达标 {len(unmet or [])} 项：{details}{more}"


def render_markdown(report: Dict[str, Any]) -> str:
    """渲染为 Markdown（三段式 + 未处理项段）。"""
    sec = report["sections"]
    lines = [
        f"# 清洗报告 · {report['thread_id']}",
        "",
        f"源文件：{report['source'].get('file_name', '-')}",
        "",
        f"## 一、{sec['1_profile']['title']}",
        "",
        f"结论：{sec['1_profile']['conclusion']}",
        "",
        "| 严重度 | 数量 |",
        "|---|---|",
        f"| 高 | {sec['1_profile']['severity_summary']['high']} |",
        f"| 中 | {sec['1_profile']['severity_summary']['medium']} |",
        f"| 低 | {sec['1_profile']['severity_summary']['low']} |",
        "",
    ]
    for issue in sec["1_profile"]["issues"]:
        lines.append(f"- **{issue['issue_name']}**（{issue['severity']}，score={issue.get(issue['issue_name'] + '_score')}）：{issue.get('rows', [])[:10]}")
    lines += [
        "",
        f"## 二、{sec['2_process']['title']}",
        "",
        f"配方：{sec['2_process'].get('recipe_id')}",
        "",
    ]
    for entry in sec["2_process"]["transform_log"]:
        lines.append(f"- 步骤{entry.get('step')} {entry.get('op')}: {entry}")
    lines += [
        "",
        f"## 三、{sec['3_quality']['title']}",
        "",
        "| 指标 | 清洗前 | 清洗后 |",
        "|---|---|---|",
    ]
    for key, m in sec["3_quality"]["metrics"].items():
        lines.append(f"| {key} | {m.get('before', '-')} | {m.get('after', '-')} |")
    lines += [
        "",
        f"判定：{'通过 ✅' if sec['3_quality']['passed'] else '未通过'}",
        f"结论：{sec['3_quality'].get('conclusion', '')}",
    ]
    if sec["3_quality"].get("unmet"):
        lines.append("未达标项：")
        for item in sec["3_quality"]["unmet"]:
            lines.append(f"- {_unmet_text(item)}")
    unhandled_sec = sec.get("4_unhandled", {"title": "未处理项", "unhandled": []})
    lines += [
        "",
        f"## 四、{unhandled_sec['title']}",
        "",
    ]
    if not unhandled_sec.get("unhandled"):
        lines.append("无：全部检出问题均有配方操作覆盖。")
    else:
        if unhandled_sec.get("conclusion"):
            lines.append(unhandled_sec["conclusion"])
            lines.append("")
        lines.append("| 问题 | 严重度 | 涉及行数 | 未处理原因 |")
        lines.append("|---|---|---|---|")
        for item in unhandled_sec["unhandled"]:
            lines.append(f"| {item.get('issue_name', '-')} | {item.get('severity', '-')} | "
                         f"{item.get('affected_rows', 0)} | {item.get('reason', '-')} |")
    return "\n".join(lines)


def render_json(report: Dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
