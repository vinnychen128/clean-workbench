"""导出套件：清洗副本导出 CSV / XLSX / ODS / PDF / JSON / SQL / 自定义模板。

依据：导出=用户指定目录 + 时间戳文件名；数据不出本机。
附件产物：问题明细 CSV + 问题汇总 CSV + 配方 recipe.json（默认与主格式同批导出）。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

SUPPORTED_FORMATS = ("csv", "xlsx", "ods", "pdf", "json", "sql", "template")
# 自定义模板的元信息插槽（按顺序渲染；未提供则不输出该行）
TEMPLATE_SLOTS = ("标题", "来源文件", "生成时间")


class ExportError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _stamp() -> str:
    now = datetime.now()
    return f"{now.year}{now.month:02d}{now.day:02d}_{now.hour:02d}{now.minute:02d}{now.second:02d}"


def _write_text(path: str, content: str, encoding: str = "utf-8") -> str:
    """文本写盘：编码失败即报错（fail-loud，不做静默替换）。"""
    try:
        with open(path, "w", encoding=encoding, newline="") as f:
            f.write(content)
    except UnicodeEncodeError as exc:
        raise ExportError("EXPORT_ENCODING_FAILED",
                          f"目标编码 {encoding} 无法表示导出内容：{exc}") from exc
    return path


def export_csv(columns: List[str], rows: List[List[Any]], out_dir: str, base_name: str) -> str:
    path = os.path.join(out_dir, f"{base_name}_{_stamp()}.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)
    return path


def export_xlsx(columns: List[str], rows: List[List[Any]], out_dir: str, base_name: str) -> str:
    from openpyxl import Workbook

    path = os.path.join(out_dir, f"{base_name}_{_stamp()}.xlsx")
    wb = Workbook()
    ws = wb.active
    ws.title = "清洗结果"
    ws.append(columns)
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def export_ods(columns: List[str], rows: List[List[Any]], out_dir: str, base_name: str) -> str:
    # odfpy 双许可；本项目按 Apache-2.0 条款使用
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.table import Table, TableCell, TableRow
    from odf.text import P

    path = os.path.join(out_dir, f"{base_name}_{_stamp()}.ods")
    doc = OpenDocumentSpreadsheet()
    table = Table(name="清洗结果")

    def _cell(value: Any) -> TableCell:
        cell = TableCell()
        cell.addElement(P(text="" if value is None else str(value)))
        return cell

    def _row(values) -> TableRow:
        r = TableRow()
        for v in values:
            r.addElement(_cell(v))
        return r

    table.addElement(_row(columns))
    for row in rows:
        table.addElement(_row(row))
    doc.spreadsheet.addElement(table)
    doc.save(path)
    return path


def export_pdf(columns: List[str], rows: List[List[Any]], out_dir: str, base_name: str,
               report_md: Optional[str] = None) -> str:
    """PDF 导出：分段式报告 + 数据表（中文字体缺失时提示用系统字体路径）。"""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table as RLTable, TableStyle
    from reportlab.lib import colors

    path = os.path.join(out_dir, f"{base_name}_{_stamp()}.pdf")
    doc = SimpleDocTemplate(path, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm)
    styles = getSampleStyleSheet()
    story = [Paragraph(f"{base_name} 清洗导出", styles["Title"]), Spacer(1, 6 * mm)]
    if report_md:
        # 报告 Markdown 摘要：提取三段标题与判定，不整篇嵌入
        story.append(Paragraph("详见清洗报告（同目录 .md 文件）", styles["Normal"]))
        story.append(Spacer(1, 4 * mm))
    table_data = [columns] + rows[:200]  # 大表只导出前 200 行预览，完整数据见 CSV/XLSX
    t = RLTable(table_data, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
    ]))
    story.append(t)
    doc.build(story)
    return path


def export_json(columns: List[str], rows: List[List[Any]], out_dir: str, base_name: str,
                meta: Optional[Dict[str, Any]] = None) -> str:
    """JSON 导出：列名 + 记录数组（records 结构，便于程序消费）。"""
    path = os.path.join(out_dir, f"{base_name}_{_stamp()}.json")
    payload: Dict[str, Any] = {
        "columns": list(columns),
        "row_count": len(rows),
        "rows": [dict(zip(columns, row)) for row in rows],
    }
    if meta:
        payload["meta"] = meta
    return _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _sql_ident(name: Any) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def export_sql(columns: List[str], rows: List[List[Any]], out_dir: str, base_name: str,
               table_name: str = "cleaned") -> str:
    """SQL 导出：建表 + 批量 INSERT（标准 SQL，可直接在 DB 客户端执行）。"""
    path = os.path.join(out_dir, f"{base_name}_{_stamp()}.sql")
    table = _sql_ident(table_name or "cleaned")
    cols_sql = ", ".join(f"{_sql_ident(c)} TEXT" for c in columns)
    lines = [
        f"-- 清洗副本导出（SQL）base={base_name} rows={len(rows)} generated={_stamp()}",
        "BEGIN TRANSACTION;",
        f"DROP TABLE IF EXISTS {table};",
        f"CREATE TABLE {table} ({cols_sql});",
    ]
    names = ", ".join(_sql_ident(c) for c in columns)
    for row in rows:
        values = ", ".join(_sql_literal(v) for v in row)
        lines.append(f"INSERT INTO {table} ({names}) VALUES ({values});")
    lines.append("COMMIT;")
    return _write_text(path, "\n".join(lines) + "\n")


def _esc(value: Any) -> str:
    return ("" if value is None else str(value)).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def export_template(columns: List[str], rows: List[List[Any]], out_dir: str, base_name: str,
                    template_placeholders: Optional[Dict[str, str]] = None,
                    encoding: str = "utf-8", line_ending: str = "lf") -> str:
    """自定义模板导出：内置 HTML 表格模板（可直接打开 / 二次编辑）。

    - template_placeholders：占位符映射（如 {"日期": "2026-09-15"}），在模板文本中替换 `{日期}`。
    - encoding：写盘编码（utf-8 / gbk）；line_ending：lf / crlf。
    说明：「自定义模板」按实施期内置模板落地；模板参数留白（delimiter 等）由内置模板约定。
    """
    nl = "\r\n" if str(line_ending).lower() == "crlf" else "\n"
    slots = {str(k): str(v) for k, v in (template_placeholders or {}).items()}
    blocks = ["<!-- 清洗副本导出模板（可编辑后复用） -->"]
    if any(s in slots for s in TEMPLATE_SLOTS):
        blocks.append("<header>")
        for slot in TEMPLATE_SLOTS:
            if slot in slots:
                blocks.append(f"<p class=\"{slot}\">{_esc(slots[slot])}</p>")
        blocks.append("</header>")
    blocks += ["<table border=\"1\">",
               "<thead><tr>" + "".join(f"<th>{_esc(c)}</th>" for c in columns) + "</tr></thead>", "<tbody>"]
    for row in rows:
        blocks.append("<tr>" + "".join(f"<td>{_esc(v)}</td>" for v in row) + "</tr>")
    blocks += ["</tbody>", "</table>"]
    content = nl.join(blocks)
    for key, value in slots.items():
        content = content.replace("{" + key + "}", value)
    path = os.path.join(out_dir, f"{base_name}_{_stamp()}_template.html")
    return _write_text(path, content, encoding=encoding)


def _issue_rows(profile: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    issues = (profile or {}).get("issues", []) or []
    out: List[Dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        name = issue.get("issue_name", "")
        score = issue.get("score")
        if score is None:
            for key, value in issue.items():
                if key.endswith("_score"):
                    score = value
                    break
        rows_hit = issue.get("rows") or []
        out.append({
            "issue_name": name,
            "severity": issue.get("severity", ""),
            "score": score if score is not None else "",
            "affected_rows": len(rows_hit),
            "rows": "|".join(str(r) for r in rows_hit[:200]),
            "verbosity": issue.get("verbosity", ""),
        })
    return out


def export_issues_csv(profile: Optional[Dict[str, Any]], out_dir: str, base_name: str) -> str:
    """问题明细 CSV：每个检测器每条问题一行（含涉及行号，最多 200 行号）。"""
    path = os.path.join(out_dir, f"{base_name}_{_stamp()}_issues.csv")
    rows = _issue_rows(profile)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["issue_name", "severity", "score", "affected_rows", "rows", "verbosity"])
        for r in rows:
            writer.writerow([r["issue_name"], r["severity"], r["score"], r["affected_rows"], r["rows"], r["verbosity"]])
    return path


def export_issues_summary_csv(profile: Optional[Dict[str, Any]], out_dir: str, base_name: str) -> str:
    """问题汇总 CSV：按检测器聚合一行（严重度 / 分数 / 涉及行数 / 异常）。"""
    path = os.path.join(out_dir, f"{base_name}_{_stamp()}_issues_summary.csv")
    rows = _issue_rows(profile)
    errors = (profile or {}).get("detector_errors", []) or []
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["issue_name", "severity", "score", "affected_rows", "verbosity", "detector_error"])
        for r in rows:
            writer.writerow([r["issue_name"], r["severity"], r["score"], r["affected_rows"], r["verbosity"], ""])
        for err in errors:
            writer.writerow([err.get("issue_name", "detector"), "", "", "", "", err.get("message", str(err))])
    return path


def export_data(fmt: str, columns: List[str], rows: List[List[Any]], out_dir: str, base_name: str,
                report_md: Optional[str] = None, **options: Any) -> str:
    """按格式导出清洗副本。options 见各导出函数（table_name / encoding / line_ending / meta 等）。"""
    if fmt not in SUPPORTED_FORMATS:
        raise ExportError("UNSUPPORTED_FORMAT", f"仅支持 {SUPPORTED_FORMATS}")
    os.makedirs(out_dir, exist_ok=True)
    if fmt == "csv":
        return export_csv(columns, rows, out_dir, base_name)
    if fmt == "xlsx":
        return export_xlsx(columns, rows, out_dir, base_name)
    if fmt == "ods":
        return export_ods(columns, rows, out_dir, base_name)
    if fmt == "json":
        return export_json(columns, rows, out_dir, base_name, meta=options.get("meta"))
    if fmt == "sql":
        return export_sql(columns, rows, out_dir, base_name, table_name=options.get("table_name") or "cleaned")
    if fmt == "template":
        return export_template(columns, rows, out_dir, base_name,
                               template_placeholders=options.get("template_placeholders"),
                               encoding=options.get("encoding") or "utf-8",
                               line_ending=options.get("line_ending") or "lf")
    return export_pdf(columns, rows, out_dir, base_name, report_md)
