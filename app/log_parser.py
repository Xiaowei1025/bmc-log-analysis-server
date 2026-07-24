import fnmatch
import gzip
import io
import re
import tarfile
import zipfile
from pathlib import Path

MAX_EXTRACTED_BYTES = 500 * 1024 * 1024


def _safe_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def read_log_bundle(path: Path) -> dict[str, str]:
    """Returns text files from a plain log, zip, tar(.gz), or gz file. Never extracts to disk."""
    result, used = {}, 0

    def add(name: str, content: bytes):
        nonlocal used
        base_name = Path(name).name
        if name.startswith("__MACOSX/") or base_name == ".DS_Store" or base_name.startswith("._"):
            return
        # BMC dump archives commonly carry rotated *.log.gz files inside the
        # outer tar.gz. Decode those inner logs as searchable text as well.
        if name.lower().endswith(".gz"):
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(content)) as inner:
                    content = inner.read(20 * 1024 * 1024 + 1)
                name = name[:-3]
            except OSError:
                pass
        # Skip obvious image / binary payloads. They add no searchable log
        # evidence and would otherwise pollute regex matching with replacement
        # characters.
        if content and content.count(b"\x00") * 100 > len(content):
            return
        if used >= MAX_EXTRACTED_BYTES or len(content) > 20 * 1024 * 1024:
            return
        used += len(content)
        result[name] = _safe_text(content)

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir() or info.file_size > 20 * 1024 * 1024:
                    continue
                add(info.filename, archive.read(info))
        return result
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                if not member.isfile() or member.size > 20 * 1024 * 1024:
                    continue
                stream = archive.extractfile(member)
                if stream:
                    add(member.name, stream.read())
        return result
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rb") as source:
            add(path.stem, source.read(20 * 1024 * 1024 + 1))
        return result
    add(path.name, path.read_bytes()[:20 * 1024 * 1024])
    return result


def find_evidence(files: dict[str, str], file_pattern: str, expression: str, is_regex: bool):
    for name, content in files.items():
        if not fnmatch.fnmatch(name.lower(), file_pattern.lower()):
            continue
        if is_regex:
            try:
                found = re.search(expression, content, re.IGNORECASE | re.MULTILINE)
            except re.error as error:
                return None, f"无效正则：{error}"
            if found:
                line = content.count("\n", 0, found.start()) + 1
                excerpt = content[max(0, found.start() - 100): found.end() + 180].replace("\n", " ")
                return {"file": name, "line": line, "excerpt": excerpt}, None
        else:
            position = content.lower().find(expression.lower())
            if position >= 0:
                line = content.count("\n", 0, position) + 1
                excerpt = content[max(0, position - 100): position + len(expression) + 180].replace("\n", " ")
                return {"file": name, "line": line, "excerpt": excerpt}, None
    return None, None
