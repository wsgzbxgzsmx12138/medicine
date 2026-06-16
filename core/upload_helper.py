"""处理用户上传的文件/压缩包，写入待分析目录。"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from core.utils import PROJECT_ROOT, ensure_dir

SUPPORTED_EXTENSIONS = {".docx", ".pdf", ".doc"}


def _is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def _safe_extract_path(name: str) -> Path | None:
    """zip 内相对路径，过滤目录遍历。"""
    parts = [p for p in Path(name.replace("\\", "/")).parts if p and p not in (".", "..")]
    if not parts:
        return None
    return Path(*parts)


def save_uploaded_files(
    uploaded_files: list,
    *,
    zip_file=None,
    base_dir: Path | None = None,
) -> Path:
    """
    将 Streamlit 上传的多文件或 zip 保存到独立目录。
    zip 保留内部相对路径；单文件保存到根目录。
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = ensure_dir((base_dir or PROJECT_ROOT / "data" / "upload" / "custom") / stamp)

    if zip_file is not None:
        raw = zip_file.getvalue() if hasattr(zip_file, "getvalue") else zip_file.read()
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                rel = _safe_extract_path(info.filename)
                if rel is None or not _is_supported(rel):
                    continue
                dest = target / rel
                ensure_dir(dest.parent)
                dest.write_bytes(zf.read(info.filename))

    for uf in uploaded_files or []:
        name = Path(uf.name).name
        if not _is_supported(Path(name)):
            continue
        (target / name).write_bytes(uf.getbuffer())

    return target


def list_supported_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        p for p in directory.rglob("*") if p.is_file() and _is_supported(p)
    )


def upload_signature(uploaded_files: list | None, zip_file) -> str:
    parts: list[str] = []
    for uf in uploaded_files or []:
        parts.append(f"f:{uf.name}:{uf.size}")
    if zip_file is not None:
        size = zip_file.size if hasattr(zip_file, "size") else len(zip_file.getvalue())
        parts.append(f"z:{zip_file.name}:{size}")
    return "|".join(sorted(parts))
