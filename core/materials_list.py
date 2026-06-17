from __future__ import annotations

from pathlib import Path

from core.scanner import FileInfo, file_info_from_output_path
from core.utils import load_json, normalize_text

# 不作为「本次提交材料」列出的文件名特征
_SKIP_NAME_PATTERNS = (
    "AI工具",
    "需求.doc",
    "申报资料要求及说明",
    "附件+4",
    "附件4",
    "附件 4",
)

# 真实性声明自身不列入清单
_DEFAULT_EXCLUDE_CHAPTERS = frozenset({"CH1.11.5"})


def _should_skip_file(name: str, chapter: str | None, *, exclude_chapters: frozenset[str]) -> bool:
    if chapter and chapter in exclude_chapters:
        return True
    norm = normalize_text(name)
    return any(normalize_text(p) in norm for p in _SKIP_NAME_PATTERNS)


def _material_label(chapter: str | None, title: str, file_name: str) -> str:
    if chapter:
        ch1_titles = {
            r["code"]: r["title"]
            for r in load_json("nmpa_rules.json").get("ch1_required", [])
            if r.get("code")
        }
        short = ch1_titles.get(chapter, title)
        return f"{chapter} {short}" if short else chapter
    if "说明书" in file_name:
        return "产品说明书"
    return title or Path(file_name).stem


def build_ch115_material_lines(
    file_list: list[FileInfo],
    *,
    filled_paths: list[str] | None = None,
    exclude_chapters: frozenset[str] | None = None,
) -> list[str]:
    """根据实际上传/已填写文件生成 CH1.11.5「提交如下材料」条目。"""
    exclude = exclude_chapters or _DEFAULT_EXCLUDE_CHAPTERS
    ch1_order = [r["code"] for r in load_json("nmpa_rules.json").get("ch1_required", []) if r.get("code")]

    by_chapter: dict[str, FileInfo] = {}
    extras: list[FileInfo] = []

    def _register(fi: FileInfo) -> None:
        if _should_skip_file(fi.file_name, fi.chapter_code, exclude_chapters=exclude):
            return
        if fi.chapter_code:
            by_chapter[fi.chapter_code] = fi
            return
        if "说明书" in fi.file_name:
            if not any("说明书" in e.file_name for e in extras):
                extras.append(fi)
            return
        if fi.file_category == "核心数据源":
            extras.append(fi)

    for raw in filled_paths or []:
        path = Path(raw)
        if path.exists():
            _register(file_info_from_output_path(path))

    for fi in file_list:
        if fi.chapter_code:
            if fi.chapter_code not in by_chapter:
                _register(fi)
        elif fi.file_category == "核心数据源":
            _register(fi)

    lines: list[str] = []
    n = 1
    for code in ch1_order:
        fi = by_chapter.get(code)
        if not fi:
            continue
        label = _material_label(fi.chapter_code, fi.title, fi.file_name)
        lines.append(f"{n}.  {label}；")
        n += 1

    for fi in extras:
        label = _material_label(fi.chapter_code, fi.title, fi.file_name)
        lines.append(f"{n}.  {label}；")
        n += 1

    return lines
