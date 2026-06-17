from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from core.checker import ConsistencyIssue, StructureIssue, check_consistency, check_manual_structure
from core.extractor import read_docx_full_text
from core.llm_client import call_llm, should_use_llm
from core.utils import glob_files, load_json, normalize_text, read_prompt


@dataclass
class FormatIssue:
    doc_name: str
    chapter_code: str
    problems: list[str]
    severity: str = "warning"
    suggestion: str = ""
    regulation_ref: str = ""
    summary: str = ""
    check_source: str = "rule"


@dataclass
class CrossCheckResult:
    consistency_issues: list[ConsistencyIssue] = field(default_factory=list)
    structure_issues: list[StructureIssue] = field(default_factory=list)
    format_issues: list[FormatIssue] = field(default_factory=list)
    field_matrix: dict[str, dict[str, str]] = field(default_factory=dict)
    llm_used: bool = False


def _read_doc_text(path: Path, max_chars: int = 10000) -> str:
    if path.suffix.lower() == ".docx":
        text = read_docx_full_text(path)
    elif path.suffix.lower() == ".doc":
        raw = path.read_bytes()
        text = raw.decode("utf-16-le", errors="ignore")
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")
    return text[:max_chars]


def _parse_llm_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return {}
    return {}


def _clip(text: str, n: int = 80) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _log_llm_detail(
    purpose: str,
    *,
    request_brief: str,
    prompt_file: str,
    success: bool,
    response_brief: str,
    fallback: str = "",
) -> None:
    from core.run_logger import get_run_logger

    logger = get_run_logger()
    if logger:
        logger.llm_round(
            purpose,
            request_brief=request_brief,
            prompt_file=prompt_file,
            success=success,
            response_brief=response_brief,
            fallback=fallback,
        )


def _doc_profile(path: Path, config: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    for key, profile in config.get("doc_profiles", {}).items():
        if fnmatch(path.name, profile.get("match", "")):
            return key, profile
    return None


def _resolve_check_docs(upload_dir: Path, filled_files: list[str]) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for fp in filled_files:
        p = Path(fp)
        if p.exists() and p.name not in seen:
            paths.append(p)
            seen.add(p.name)
    if paths:
        return paths

    config = load_json("cross_check_config.json")
    for profile in config.get("doc_profiles", {}).values():
        for p in glob_files(upload_dir, profile.get("match", "*")):
            if p.name not in seen:
                paths.append(p)
                seen.add(p.name)
    for p in glob_files(upload_dir, "*说明书*.docx"):
        if p.name not in seen:
            paths.append(p)
            seen.add(p.name)
    return sorted(paths, key=lambda x: x.name)


def _rule_structure_check(path: Path, profile: dict[str, Any]) -> StructureIssue | None:
    text = _read_doc_text(path, max_chars=50000)
    required = profile.get("required_sections", [])
    missing = [s for s in required if s not in text]
    perf = profile.get("performance_items", [])
    missing_perf = [s for s in perf if s not in text]
    all_missing = missing + [f"性能项:{p}" for p in missing_perf]
    if not all_missing:
        return None
    return StructureIssue(
        doc_name=path.name,
        missing_sections=all_missing,
        severity="critical" if missing else "warning",
    )


def _rule_format_check(path: Path, profile_key: str, profile: dict[str, Any]) -> FormatIssue | None:
    text = _read_doc_text(path, max_chars=50000)
    problems: list[str] = []
    if profile_key == "manual" and "【产品名称】" not in text:
        problems.append("未使用【产品名称】规范章节标题")
    if profile_key in ("CH1.11.5", "CH1.11.6", "CH1.11.1") and "申请境内第三类" in text:
        if len(text) < 120:
            problems.append("声明/清单正文过短，可能未填写完整产品名称")
    if not problems:
        return None
    return FormatIssue(
        doc_name=path.name,
        chapter_code=profile_key.upper() if profile_key.startswith("CH") else profile_key,
        problems=problems,
        suggestion="请对照附件4及编写指导原则修正格式",
        regulation_ref=profile.get("regulation_ref", ""),
        check_source="rule",
    )


def _llm_structure_check(path: Path, profile: dict[str, Any]) -> StructureIssue | None:
    text = _read_doc_text(path)
    doc_type = profile.get("label", path.stem)
    purpose = f"阶段4 · 章节完整性 · {path.name}"
    req = (
        f"检查《{path.name}》（{doc_type}）是否包含必检章节"
        f"及性能项（如分析灵敏度、特异性、重复性等）；"
        "缺失项列入 missing_sections，输出 JSON，禁止编造。"
    )
    prompt = read_prompt(
        "structure_check_prompt.md",
        DOC_NAME=path.name,
        DOC_TYPE=doc_type,
        REGULATION_REF=profile.get("regulation_ref", "附件4"),
        REQUIRED_SECTIONS="\n".join(f"- {s}" for s in profile.get("required_sections", [])) or "（无固定章节要求）",
        PERFORMANCE_ITEMS="\n".join(f"- {p}" for p in profile.get("performance_items", [])) or "（不适用）",
        TEXT=text,
    )
    raw = call_llm(prompt, purpose=purpose, request_brief=req, prompt_file="prompts/structure_check_prompt.md")
    data = _parse_llm_json(raw)
    if not data:
        _log_llm_detail(
            purpose,
            request_brief=req,
            prompt_file="prompts/structure_check_prompt.md",
            success=False,
            response_brief="无有效 JSON",
            fallback="Python 改用关键词匹配规则检查章节。",
        )
        return _rule_structure_check(path, profile)

    missing = list(data.get("missing_sections") or [])
    missing.extend(data.get("missing_performance_items") or [])
    summary = str(data.get("summary", ""))
    if not missing:
        _log_llm_detail(
            purpose,
            request_brief=req,
            prompt_file="prompts/structure_check_prompt.md",
            success=True,
            response_brief=f"章节齐全 — {summary or '未发现缺失项'}",
        )
        return None

    _log_llm_detail(
        purpose,
        request_brief=req,
        prompt_file="prompts/structure_check_prompt.md",
        success=True,
        response_brief=f"缺 {len(missing)} 项：{_clip(', '.join(missing))} — {summary}",
    )
    return StructureIssue(
        doc_name=path.name,
        missing_sections=missing,
        severity=str(data.get("severity", "warning")),
    )


def _llm_format_check(path: Path, profile_key: str, profile: dict[str, Any]) -> FormatIssue | None:
    text = _read_doc_text(path)
    doc_type = profile.get("label", path.stem)
    purpose = f"阶段4 · 格式规范 · {path.name}"
    req = f"对照附件4检查《{path.name}》（{doc_type}）格式是否合规；只报告能从正文判断的问题，输出 JSON。"
    prompt = read_prompt(
        "format_check_prompt.md",
        DOC_NAME=path.name,
        DOC_TYPE=doc_type,
        REGULATION_REF=profile.get("regulation_ref", "附件4"),
        FORMAT_HINTS="\n".join(f"- {h}" for h in profile.get("format_hints", [])),
        TEXT=text,
    )
    raw = call_llm(prompt, purpose=purpose, request_brief=req, prompt_file="prompts/format_check_prompt.md")
    data = _parse_llm_json(raw)
    if not data:
        _log_llm_detail(
            purpose,
            request_brief=req,
            prompt_file="prompts/format_check_prompt.md",
            success=False,
            response_brief="无有效 JSON",
            fallback="Python 改用简单规则检查格式。",
        )
        return _rule_format_check(path, profile_key, profile)

    problems = list(data.get("problems") or [])
    if data.get("compliant") is True or not problems:
        _log_llm_detail(
            purpose,
            request_brief=req,
            prompt_file="prompts/format_check_prompt.md",
            success=True,
            response_brief=str(data.get("summary", "格式合规")),
        )
        return None

    suggestions = data.get("suggestions") or []
    _log_llm_detail(
        purpose,
        request_brief=req,
        prompt_file="prompts/format_check_prompt.md",
        success=True,
        response_brief=f"{len(problems)} 个问题：{_clip('; '.join(problems))}",
    )
    return FormatIssue(
        doc_name=path.name,
        chapter_code=profile_key.upper() if profile_key.startswith("CH") else profile_key,
        problems=problems,
        severity=str(data.get("severity", "warning")),
        suggestion="；".join(suggestions) if suggestions else "请对照附件4修正",
        regulation_ref=profile.get("regulation_ref", ""),
        summary=str(data.get("summary", "")),
        check_source="llm",
    )


def _llm_extract_fields(path: Path, field_defs: list[dict[str, str]]) -> dict[str, str]:
    text = _read_doc_text(path)
    labels = "、".join(fd.get("label", fd["field"]) for fd in field_defs)
    purpose = f"阶段4 · 一致性字段提取 · {path.name}"
    req = f"从《{path.name}》提取用于跨文档比对的字段：{labels}；找不到填「未提及」，输出 JSON。"
    prompt = read_prompt(
        "consistency_extract_prompt.md",
        DOC_NAME=path.name,
        FIELDS_JSON=json.dumps(field_defs, ensure_ascii=False, indent=2),
        TEXT=text,
    )
    raw = call_llm(
        prompt,
        purpose=purpose,
        request_brief=req,
        prompt_file="prompts/consistency_extract_prompt.md",
    )
    data = _parse_llm_json(raw)
    fields = data.get("fields") if isinstance(data.get("fields"), dict) else data
    result: dict[str, str] = {}
    for fd in field_defs:
        key = fd["field"]
        val = fields.get(key, "未提及") if isinstance(fields, dict) else "未提及"
        if val and val != "未提及":
            result[key] = str(val).strip()
    preview = "；".join(f"{k}={_clip(v)}" for k, v in list(result.items())[:5])
    _log_llm_detail(
        purpose,
        request_brief=req,
        prompt_file="prompts/consistency_extract_prompt.md",
        success=bool(result),
        response_brief=preview or "未提取到有效字段",
        fallback="该文件不参与一致性矩阵比对。" if not result else "",
    )
    return result


def _compare_field_matrix(
    matrix: dict[str, dict[str, str]],
    field_defs: list[dict[str, str]],
) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    for fd in field_defs:
        field = fd["field"]
        label = fd.get("label", field)
        values: dict[str, str] = {}
        for doc_name, fields in matrix.items():
            val = fields.get(field)
            if val and val != "未提及":
                values[doc_name] = val
        if len(values) < 2:
            continue
        normalized = {k: normalize_text(v) for k, v in values.items()}
        if len(set(normalized.values())) > 1:
            issues.append(
                ConsistencyIssue(
                    field=field,
                    label=label,
                    severity="warning",
                    values=values,
                    suggestion=f"以下文件中的「{label}」不一致，请核对并统一",
                )
            )
    return issues


def _rule_extract_fields(path: Path, field_defs: list[dict[str, str]], upload_dir: Path) -> dict[str, str]:
    """规则兜底：复用 field_mapping 配置从单文件提取。"""
    if path.suffix.lower() != ".docx":
        return {}

    from core.checker import collect_field_values

    mapping = load_json("field_mapping.json")
    row: dict[str, str] = {}
    for fd in field_defs:
        field = fd["field"]
        cfg = next((f for f in mapping.get("consistency_fields", []) if f["field"] == field), None)
        if not cfg:
            continue
        for src in cfg.get("sources", []):
            src_copy = dict(src)
            src_copy["doc_glob"] = path.name
            vals = collect_field_values(path.parent if path.parent.exists() else upload_dir, {"sources": [src_copy]})
            if path.name in vals:
                row[field] = vals[path.name]
                break
    return row


def run_cross_check(
    upload_dir: Path,
    filled_files: list[str] | None = None,
    *,
    use_llm: bool = True,
) -> CrossCheckResult:
    """
    任务4：结构完整性 + 跨文档一致性 + 格式规范性。

    LLM 策略（启用时）：
    - 结构/格式：逐份文档单独调用（避免 7 份全文一次性塞入）
    - 一致性：逐份提取关键字段 JSON → Python 规则比对
    """
    config = load_json("cross_check_config.json")
    field_defs = config.get("consistency_fields", [])
    docs = _resolve_check_docs(upload_dir, filled_files or [])
    result = CrossCheckResult(llm_used=should_use_llm(use_llm))

    if not docs:
        result.consistency_issues = check_consistency(upload_dir)
        result.structure_issues = check_manual_structure(upload_dir)
        return result

    matrix: dict[str, dict[str, str]] = {}

    if result.llm_used:
        for path in docs:
            if path.suffix.lower() not in (".docx", ".doc"):
                continue
            profile_match = _doc_profile(path, config)
            if profile_match:
                pkey, profile = profile_match
                struct = _llm_structure_check(path, profile)
                if struct:
                    result.structure_issues.append(struct)
                fmt = _llm_format_check(path, pkey, profile)
                if fmt:
                    result.format_issues.append(fmt)
            fields = _llm_extract_fields(path, field_defs)
            if fields:
                matrix[path.name] = fields
        result.field_matrix = matrix
        result.consistency_issues = _compare_field_matrix(matrix, field_defs)
        from core.run_logger import get_run_logger

        logger = get_run_logger()
        if logger and matrix:
            logger.python_only(
                "阶段4 · 跨文档一致性比对",
                f"Python 拿 {len(matrix)} 份文件的提取结果做字符串比对，"
                f"发现 {len(result.consistency_issues)} 处不一致（不由大模型判定，避免幻觉）。",
            )
    else:
        from core.run_logger import get_run_logger

        logger = get_run_logger()
        if logger:
            logger.python_only(
                "阶段4 · 任务4 核查",
                f"未启用大模型，Python 用规则检查 {len(docs)} 份文档的章节/格式，并用 field_mapping 做一致性比对。",
            )
        for path in docs:
            profile_match = _doc_profile(path, config)
            if profile_match:
                pkey, profile = profile_match
                struct = _rule_structure_check(path, profile)
                if struct:
                    result.structure_issues.append(struct)
                fmt = _rule_format_check(path, pkey, profile)
                if fmt:
                    result.format_issues.append(fmt)
            row = _rule_extract_fields(path, field_defs, upload_dir)
            if row:
                matrix[path.name] = row
        if matrix:
            result.consistency_issues = _compare_field_matrix(matrix, field_defs)
        if not result.consistency_issues:
            result.consistency_issues = check_consistency(upload_dir)
        if not result.structure_issues:
            result.structure_issues = check_manual_structure(upload_dir)

    result.field_matrix = matrix
    return result
