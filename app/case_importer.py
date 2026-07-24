"""Safe, dependency-free import of maintenance-case source documents.

The platform stores the final article as Markdown.  This module extracts a
small, auditable subset of Office Open XML so imported Word/PPT source files
can become an editable draft without sending internal content to a third party.
"""

import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


SUPPORTED_SUFFIXES = {".docx", ".pptx", ".doc", ".ppt", ".md", ".markdown", ".txt"}
MAX_ARCHIVE_MEMBERS = int(os.getenv("CASE_IMPORT_MAX_ARCHIVE_MEMBERS", "2500"))
MAX_UNCOMPRESSED_BYTES = int(os.getenv("CASE_IMPORT_MAX_UNCOMPRESSED_MB", "30")) * 1024 * 1024
MAX_TEXT_CHARS = int(os.getenv("CASE_IMPORT_MAX_TEXT_CHARS", "1500000"))

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WORD = {"w": WORD_NS}
DRAWING = {"a": DRAWING_NS}


class CaseImportError(ValueError):
    """Expected source-document error shown to the person importing it."""


def format_label(value: str) -> str:
    return {
        "docx": "Word 文档（DOCX）",
        "pptx": "PowerPoint（PPTX）",
        "doc": "旧版 Word（DOC）",
        "ppt": "旧版 PowerPoint（PPT）",
        "md": "Markdown",
        "markdown": "Markdown",
        "txt": "文本文件",
    }.get(value.lower().lstrip("."), "导入资料")


def extract_case_document(path: Path, original_name: str) -> tuple[str, str, str]:
    """Return (Markdown body, source format, extraction note) for a source file."""
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        supported = "、".join(item.lstrip(".") for item in sorted(SUPPORTED_SUFFIXES))
        raise CaseImportError(f"暂不支持该文件格式。请上传：{supported}。")
    if suffix in {".md", ".markdown", ".txt"}:
        body = _decode_text(path.read_bytes())
        return _limit_text(body), suffix.lstrip("."), "已按文本内容导入。"
    if suffix in {".doc", ".ppt"}:
        converted = _convert_legacy_office(path, suffix)
        try:
            body = _extract_docx(converted) if suffix == ".doc" else _extract_pptx(converted)
        finally:
            converted.unlink(missing_ok=True)
            converted.parent.rmdir()
        return body, suffix.lstrip("."), "已通过服务器的 LibreOffice 兼容转换导入。"
    if suffix == ".docx":
        return _extract_docx(path), "docx", "已提取 Word 标题、段落和列表；请在发布前校对排版。"
    return _extract_pptx(path), "pptx", "已按 PowerPoint 幻灯片顺序提取文字；图片、动画和版式需在草稿中补充说明。"


def suggested_title(original_name: str, body: str) -> str:
    for line in body.splitlines():
        heading = re.match(r"^#\s+(.+?)\s*$", line)
        if heading and heading.group(1).strip():
            return heading.group(1).strip()[:120]
    return Path(original_name).stem.replace("_", " ").replace("-", " ").strip()[:120] or "未命名案例"


def suggested_summary(body: str) -> str:
    plain = re.sub(r"[`*_>#\-]", " ", body)
    plain = " ".join(plain.split())
    return plain[:180]


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CaseImportError("无法识别文本编码。请另存为 UTF-8 的 Markdown 或文本文件后重试。")


def _safe_openxml(path: Path) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as error:
        raise CaseImportError("文件不是有效的 Office Open XML 文档，请确认文件未损坏。") from error
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_MEMBERS or sum(item.file_size for item in infos) > MAX_UNCOMPRESSED_BYTES:
        archive.close()
        raise CaseImportError("文档解压后的内容超过导入安全限制，请拆分或精简后重试。")
    return archive


def _member_bytes(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as error:
        raise CaseImportError("文档缺少必要内容，无法提取正文。") from error
    if info.file_size > MAX_UNCOMPRESSED_BYTES:
        raise CaseImportError("文档正文超过导入安全限制。")
    return archive.read(info)


def _paragraph_text(paragraph: ET.Element, namespace: str) -> str:
    values: list[str] = []
    for element in paragraph.iter():
        if element.tag == f"{{{namespace}}}t":
            values.append(element.text or "")
        elif element.tag in {f"{{{namespace}}}br", f"{{{namespace}}}cr"}:
            values.append("\n")
        elif element.tag == f"{{{namespace}}}tab":
            values.append("\t")
    return "".join(values).strip()


def _extract_docx(path: Path) -> str:
    archive = _safe_openxml(path)
    try:
        root = ET.fromstring(_member_bytes(archive, "word/document.xml"))
    except ET.ParseError as error:
        raise CaseImportError("Word 文档正文格式异常，无法读取。") from error
    finally:
        archive.close()
    blocks: list[str] = []
    for paragraph in root.findall(".//w:body//w:p", WORD):
        text = _paragraph_text(paragraph, WORD_NS)
        if not text:
            continue
        style = paragraph.find("./w:pPr/w:pStyle", WORD)
        style_name = style.get(f"{{{WORD_NS}}}val", "") if style is not None else ""
        heading = re.search(r"([1-6])$", style_name)
        if heading:
            blocks.append("#" * int(heading.group(1)) + " " + text)
        elif style_name.lower() in {"title", "subtitle"}:
            blocks.append("# " + text)
        elif paragraph.find("./w:pPr/w:numPr", WORD) is not None:
            blocks.append("- " + text.replace("\n", " "))
        else:
            blocks.append(text)
    if not blocks:
        raise CaseImportError("未在 Word 文档中读取到可编辑的文字内容。")
    return _limit_text("\n\n".join(blocks))


def _extract_pptx(path: Path) -> str:
    archive = _safe_openxml(path)
    try:
        slide_names = []
        for name in archive.namelist():
            match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name)
            if match:
                slide_names.append((int(match.group(1)), name))
        if not slide_names:
            raise CaseImportError("未在 PowerPoint 中读取到幻灯片文字内容。")
        blocks: list[str] = []
        for number, name in sorted(slide_names):
            try:
                root = ET.fromstring(_member_bytes(archive, name))
            except ET.ParseError as error:
                raise CaseImportError("PowerPoint 幻灯片格式异常，无法读取。") from error
            paragraphs = [_paragraph_text(item, DRAWING_NS) for item in root.findall(".//a:p", DRAWING)]
            text = "\n\n".join(item for item in paragraphs if item)
            if text:
                blocks.append(f"## 幻灯片 {number}\n\n{text}")
    finally:
        archive.close()
    if not blocks:
        raise CaseImportError("未在 PowerPoint 中读取到可编辑的文字内容。")
    return _limit_text("\n\n".join(blocks))


def _convert_legacy_office(path: Path, suffix: str) -> Path:
    configured = os.getenv("CASE_IMPORT_SOFFICE", "soffice").strip() or "soffice"
    executable = shutil.which(configured)
    if not executable:
        target = ".docx" if suffix == ".doc" else ".pptx"
        raise CaseImportError(f"服务器尚未安装 LibreOffice，暂不能直接转换旧版 {suffix}。请另存为 {target} 后导入，或由管理员安装 LibreOffice。")
    target_format = "docx" if suffix == ".doc" else "pptx"
    temp_root = Path(tempfile.mkdtemp(prefix="bmc-case-import-"))
    output_dir = temp_root / "output"
    profile_dir = temp_root / "profile"
    output_dir.mkdir()
    profile_dir.mkdir()
    try:
        subprocess.run(
            [executable, "--headless", f"-env:UserInstallation={profile_dir.as_uri()}", "--convert-to", target_format, "--outdir", str(output_dir), str(path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise CaseImportError("旧版 Office 文档转换失败，请另存为 DOCX/PPTX 后重试。") from error
    converted = next(output_dir.glob(f"*.{target_format}"), None)
    if not converted:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise CaseImportError("旧版 Office 文档转换失败，请另存为 DOCX/PPTX 后重试。")
    final_path = temp_root / f"converted.{target_format}"
    converted.replace(final_path)
    shutil.rmtree(output_dir, ignore_errors=True)
    shutil.rmtree(profile_dir, ignore_errors=True)
    return final_path


def _limit_text(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise CaseImportError("未读取到可编辑的文字内容。")
    if len(text) > MAX_TEXT_CHARS:
        raise CaseImportError("提取的文字超过导入限制，请拆分案例后重试。")
    return text
