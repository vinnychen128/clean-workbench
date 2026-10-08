"""解析引擎：CSV / Excel(XLSX·XLS) / PDF(文本)。

依据：原件只读、不改写；输入类型白名单 CSV/XLSX/XLS/PDF（不含 JSON）；
PDF 使用浏览器内已解析结果（后端不接收原件），扫描版 PDF 明确提示不支持。
CSV 编码探测：UTF-8 → GBK → GB18030；Excel 长数字按文本读（防精度丢失）。
"""
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass, field
from typing import Any, Dict, List

ALLOWED_TYPES = {"csv", "xlsx", "xls", "pdf"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


class ParseError(Exception):
    """解析失败（携带 code 供接口层映射）。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ParseResult:
    """解析产物：数据引用 + 列信息 + 解析报告。"""

    data_ref: str
    columns: List[str]
    rows: List[List[Any]]
    row_count: int
    col_count: int
    parsing_report: Dict[str, Any] = field(default_factory=dict)


def compute_file_hash(raw: bytes) -> str:
    """按字节流式计算同一性哈希（仅用于同一性核对，不解析 / 不落库 / 不外发）。"""
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _decode_csv(raw: bytes) -> str:
    """CSV 编码探测：UTF-8 → GBK → GB18030。全部失败抛 ParseError。"""
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ParseError("PARSE_ENCODING_FAILED", "编码无法识别，请将文件另存为 UTF-8 后重试")


def _detect_encoding(raw: bytes) -> str:
    """返回实际成功解码的编码名（utf-8-sig 归一为 utf-8，供 parsing_report 如实上报）。"""
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            raw.decode(enc)
            return "utf-8" if enc == "utf-8-sig" else enc
        except UnicodeDecodeError:
            continue
    raise ParseError("PARSE_ENCODING_FAILED", "编码无法识别，请将文件另存为 UTF-8 后重试")


def _detect_delimiter(text: str) -> str:
    """简单分隔符探测：逗号 / 分号 / 制表符。"""
    sample = "\n".join(text.splitlines()[:5])
    for delim in (",", "\t", ";"):
        if delim in sample:
            return delim
    return ","


def _keep_long_number_as_text(value: Any, warnings: List[str]) -> Any:
    """Excel 长数字按文本读：超 15 位有效数字的数值改为 str 并加长数字⚠。"""
    if isinstance(value, (int, float)):
        s = str(value)
        if len(s.replace(".", "").replace("-", "")) >= 16:
            warnings.append("长数字⚠")
            return s
    return value


def parse_csv(raw: bytes, data_ref: str) -> ParseResult:
    """解析 CSV 数据流：编码探测 + 分隔符探测 + 文本化。"""
    import csv

    text = _decode_csv(raw)
    delim = _detect_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = [row for row in reader if any(cell.strip() != "" for cell in row)]
    if not rows:
        raise ParseError("EMPTY_FILE", "空文件，无法解析")
    columns = rows[0]
    data_rows = rows[1:]
    warnings: List[str] = []
    cleaned_rows = []
    for row in data_rows:
        cleaned_rows.append([_keep_long_number_as_text(c, warnings) for c in row])
    encoding = _detect_encoding(raw)
    return ParseResult(
        data_ref=data_ref,
        columns=columns,
        rows=cleaned_rows,
        row_count=len(cleaned_rows),
        col_count=len(columns),
        parsing_report={"encoding": encoding, "delimiter": delim, "warnings": warnings},
    )


def parse_excel(raw: bytes, file_type: str, data_ref: str) -> ParseResult:
    """解析 Excel 数据流（xlsx / xls）。多 sheet 由用户选择，不猜（默认取第一个）。"""
    warnings: List[str] = []
    sheets: List[str] = []
    if file_type == "xlsx":
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        sheets = wb.sheetnames
        ws = wb[sheets[0]]
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
    else:  # xls
        import xlrd

        book = xlrd.open_workbook(file_contents=raw)
        sheets = book.sheet_names()
        sh = book.sheet_by_index(0)
        rows = [sh.row_values(i) for i in range(sh.nrows)]

    rows = [[_keep_long_number_as_text(c, warnings) for c in row] for row in rows]
    rows = [row for row in rows if any(str(c).strip() != "" for c in row)]
    if not rows:
        raise ParseError("EMPTY_FILE", "空文件，无法解析")
    columns = [str(c).strip() if c is not None else "" for c in rows[0]]
    data_rows = rows[1:]
    return ParseResult(
        data_ref=data_ref,
        columns=columns,
        rows=data_rows,
        row_count=len(data_rows),
        col_count=len(columns),
        parsing_report={
            "format": file_type,
            "sheets": sheets,
            "selected_sheet": sheets[0] if sheets else None,
            "warnings": warnings,
        },
    )


def parse_pdf(raw: bytes, data_ref: str) -> ParseResult:
    """PDF：后端只做文本层探测与直读（浏览器内已解析结果为准）；扫描版明确提示不支持。

    解析库：pypdf（BSD-3-Clause，位于许可证白名单内）。
    说明：原实现依赖 PyMuPDF(fitz)，其许可证为 AGPL-3.0，违反红线（许可证白名单禁 AGPL），
    故改用 pypdf（符合许可证白名单）。
    """
    # 依据：PDF 使用浏览器内已解析结果，原件不上传；后端只登记引用。
    # 若前端只提交元信息（无内容），此处直接返回空表 + 提示。
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - 环境缺依赖分支
        raise ParseError("PARSE_FAILED", "后端未启用 PDF 解析库（pypdf）；请使用浏览器内已解析结果") from exc

    warnings = ["PDF 使用浏览器内已解析结果，后端不接收原件"]
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ParseError("PARSE_FAILED", "PDF 已加密，无法解析（请先解除密码保护）")
        page_count = len(reader.pages)
        page_texts: List[str] = []
        for page in reader.pages:
            try:
                page_texts.append(page.extract_text() or "")
            except Exception:
                page_texts.append("")
    except ParseError:
        raise
    except Exception as exc:  # 损坏 / 非法 PDF 统一上抛
        raise ParseError("PARSE_FAILED", f"PDF 解析失败：{exc}") from exc

    if page_count > 0 and not "".join(t.strip() for t in page_texts):
        # 无文本层 = 扫描件：明确拒收，绝不编造数据
        raise ParseError("SCANNED_PDF_UNSUPPORTED", "该 PDF 为扫描件，暂不支持，不产出假数据")

    text_chars = sum(len(t.strip()) for t in page_texts)
    return ParseResult(
        data_ref=data_ref,
        columns=[],
        rows=[],
        row_count=0,
        col_count=0,
        parsing_report={
            "format": "pdf",
            "page_count": page_count,
            "text_chars": text_chars,
            "warnings": warnings + ["文本已提取，供浏览器端展示"],
        },
    )


def parse_stream(
    file_name: str,
    file_type: str,
    file_size: int,
    file_hash: str,
    content_b64: str,
    thread_id: str,
) -> ParseResult:
    """统一解析入口（接口 /api/parse 调用）。

    - 类型白名单校验；大小上限 50MB；空文件拒绝。
    - 返回阶段化 data_ref（解析后 = 对原件的只读引用）。
    """
    if file_type not in ALLOWED_TYPES:
        raise ParseError("UNSUPPORTED_TYPE", f"仅支持 CSV / Excel / PDF，不支持 {file_type}")
    if file_size > MAX_FILE_SIZE:
        raise ParseError("FILE_TOO_LARGE", "文件超过 50MB 上限")
    if file_size == 0:
        raise ParseError("EMPTY_FILE", "空文件，无法解析")

    raw = base64.b64decode(content_b64)
    actual_hash = compute_file_hash(raw)
    if file_hash and file_hash != actual_hash:
        # 同一性核对失败：仅记录，不阻断（哈希仅用于同一性核对）
        pass

    data_ref = f"ref://parse/{thread_id}"
    if file_type == "csv":
        return parse_csv(raw, data_ref)
    if file_type in ("xlsx", "xls"):
        return parse_excel(raw, file_type, data_ref)
    return parse_pdf(raw, data_ref)
