from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from core.utils import chapter_code_from_name, ensure_dir, normalize_text


@dataclass
class FileInfo:
    file_name: str
    file_path: str
    file_format: str
    page_count: int
    file_size_kb: float
    chapter_code: str | None
    title: str


def count_docx_pages(path: Path) -> int:
    try:
        from docx import Document

        doc = Document(str(path))
        pages = sum(1 for p in doc.paragraphs if "PAGE" in p.text.upper() or "第" in p.text and "页" in p.text)
        if pages == 0:
            pages = max(1, len(doc.paragraphs) // 40 + len(doc.tables) // 2)
        return max(1, pages)
    except Exception:
        return 1


def count_pdf_pages(path: Path) -> int:
    try:
        import fitz

        with fitz.open(str(path)) as doc:
            return len(doc)
    except Exception:
        return 1


def count_pages(path: Path) -> int:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return count_pdf_pages(path)
    if suffix == ".docx":
        return count_docx_pages(path)
    return 1


def guess_title(name: str, chapter: str | None) -> str:
    mapping = {
        "CH1.2": "章节目录",
        "CH1.4": "申请表",
        "CH1.5": "产品列表",
        "CH1.9": "申报前沟通说明",
        "CH1.11.1": "符合标准清单",
        "CH1.11.5": "真实性声明",
        "CH1.11.6": "符合性声明",
    }
    if chapter and chapter in mapping:
        return mapping[chapter]
    if "说明书" in name:
        return "产品说明书"
    if "附件" in name or "申报资料要求" in name:
        return "法规参考文件"
    return Path(name).stem


def scan_directory(upload_dir: Path) -> list[FileInfo]:
    files: list[FileInfo] = []
    if not upload_dir.exists():
        return files

    for path in sorted(upload_dir.iterdir()):
        if not path.is_file():
            continue
        chapter = chapter_code_from_name(path.name)
        files.append(
            FileInfo(
                file_name=path.name,
                file_path=str(path),
                file_format=path.suffix.lower().lstrip(".") or "unknown",
                page_count=count_pages(path),
                file_size_kb=round(path.stat().st_size / 1024, 1),
                chapter_code=chapter,
                title=guess_title(path.name, chapter),
            )
        )
    return files


def build_catalog_dataframe(file_list: list[FileInfo]) -> pd.DataFrame:
    rows = []
    for f in file_list:
        rows.append(
            {
                "RPS目录": f.chapter_code or "-",
                "标题": f.title,
                "适用情况": "R" if f.chapter_code else "O",
                "资料名称": f.file_name,
                "页码": f.page_count,
                "文件格式": f.file_format,
                "大小(KB)": f.file_size_kb,
            }
        )
    return pd.DataFrame(rows)


def export_ch12_excel(file_list: list[FileInfo], output_path: Path) -> Path:
    ensure_dir(output_path.parent)
    df = build_catalog_dataframe(file_list)
    df.to_excel(output_path, index=False, sheet_name="CH1.2目录汇总")
    return output_path


def files_index(file_list: list[FileInfo]) -> str:
    return "|".join(normalize_text(f.file_name) for f in file_list)
