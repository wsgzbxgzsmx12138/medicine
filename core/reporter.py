from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from core.checker import CompletenessIssue, ConsistencyIssue, StructureIssue
from core.extractor import ExtractedInfo
from core.llm_checker import FormatIssue
from core.llm_client import generate_risk_report_llm, should_use_llm
from core.scanner import FileInfo
from core.utils import ensure_dir, save_json


def _severity_label(severity: str) -> str:
    return {
        "critical": "严重风险",
        "warning": "警告风险",
        "info": "提示",
    }.get(severity, "提示")


def _severity_icon(severity: str) -> str:
    return {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(severity, "⚪")


def _severity_badge(severity: str) -> str:
    """醒目标识：图标 + 等级文字（用于报告条目前缀）。"""
    return f"{_severity_icon(severity)} **{_severity_label(severity)}**"


def _book(name: str) -> str:
    return f"《{name}》"


def build_issues_payload(
    completeness: list[CompletenessIssue],
    consistency: list[ConsistencyIssue],
    structure: list[StructureIssue],
    format_issues: list[FormatIssue] | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for item in completeness:
        issues.append(
            {
                "type": "completeness",
                "severity": item.severity,
                "message": item.message,
                "suggestion": item.suggestion,
                "regulation_ref": item.regulation_ref,
                "notify": item.notify,
                "category": item.category,
            }
        )
    for item in consistency:
        issues.append(
            {
                "type": "consistency",
                "severity": item.severity,
                "message": f"{item.label} 不一致",
                "suggestion": item.suggestion,
                "values": item.values,
                "field": item.field,
                "label": item.label,
            }
        )
    for item in structure:
        issues.append(
            {
                "type": "structure",
                "severity": item.severity,
                "message": f"{item.doc_name} 缺少章节: {', '.join(item.missing_sections)}",
                "suggestion": "请按 NMPA 说明书编写指导原则补全必检章节",
                "doc_name": item.doc_name,
                "missing_sections": item.missing_sections,
            }
        )
    for item in format_issues or []:
        issues.append(
            {
                "type": "format",
                "severity": item.severity,
                "message": f"{item.doc_name} 格式问题: {'; '.join(item.problems)}",
                "suggestion": item.suggestion,
                "regulation_ref": item.regulation_ref,
                "doc_name": item.doc_name,
                "problems": item.problems,
            }
        )
    return issues


def build_structured_report_data(
    file_list: list[FileInfo],
    extracted: ExtractedInfo,
    completeness: list[CompletenessIssue],
    consistency: list[ConsistencyIssue],
    structure: list[StructureIssue],
    format_issues: list[FormatIssue],
    filled_files: list[str],
) -> dict[str, Any]:
    """四维度结构化 payload，供 LLM 或规则模板消费。"""
    completeness_items = [
        {
            "severity": i.severity,
            "category": i.category,
            "message": i.message,
            "suggestion": i.suggestion,
            "regulation_ref": i.regulation_ref,
            "notify": i.notify,
        }
        for i in completeness
    ]
    consistency_items = [
        {
            "severity": i.severity,
            "field": i.field,
            "label": i.label,
            "values": i.values,
            "suggestion": i.suggestion,
        }
        for i in consistency
    ]
    structure_items = [
        {
            "severity": i.severity,
            "doc_name": i.doc_name,
            "missing_sections": i.missing_sections,
        }
        for i in structure
    ]
    format_items = [
        {
            "severity": i.severity,
            "doc_name": i.doc_name,
            "problems": i.problems,
            "suggestion": i.suggestion,
            "regulation_ref": i.regulation_ref,
        }
        for i in format_issues
    ]

    all_issues = build_issues_payload(completeness, consistency, structure, format_issues)
    critical = sum(1 for i in all_issues if i["severity"] == "critical")
    warning = sum(1 for i in all_issues if i["severity"] == "warning")

    return {
        "meta": {
            "scan_count": len(file_list),
            "filled_count": len(filled_files),
            "product_name": extracted.product_name if extracted else "未提及",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "summary_stats": {
            "total": len(all_issues),
            "critical": critical,
            "warning": warning,
            "info": len(all_issues) - critical - warning,
        },
        "completeness": completeness_items,
        "consistency": consistency_items,
        "normative": {
            "structure": structure_items,
            "format": format_items,
        },
        "filled_files": [Path(f).name for f in filled_files],
    }


def _build_action_items(data: dict[str, Any]) -> list[str]:
    """维度四：To-Do List（规则生成，与 LLM 输出格式一致）。"""
    items: list[tuple[int, str, str]] = []

    def _prio(sev: str) -> int:
        return {"critical": 0, "warning": 1, "info": 2}.get(sev, 9)

    for item in data.get("completeness", []):
        msg = item["message"]
        sug = item.get("suggestion", "请补充")
        items.append((_prio(item["severity"]), msg, f"**{msg}**，{sug}"))

    for item in data.get("consistency", []):
        label = item.get("label", item.get("field", "字段"))
        parts = [f"{_book(k)}为「{v}」" for k, v in item.get("values", {}).items()]
        detail = "，".join(parts[:4])
        if len(parts) > 4:
            detail += " 等"
        items.append(
            (
                _prio(item.get("severity", "warning")),
                label,
                f"**{label}**跨文档不一致（{detail}），请核对并全量统一",
            )
        )

    for item in data.get("normative", {}).get("structure", []):
        doc = item["doc_name"]
        missing = "、".join(item.get("missing_sections", [])[:5])
        items.append(
            (
                _prio(item.get("severity", "warning")),
                doc,
                f"{_book(doc)}章节不完整，缺失 {missing}，请参照指导原则补充撰写",
            )
        )

    for item in data.get("normative", {}).get("format", []):
        doc = item["doc_name"]
        prob = "；".join(item.get("problems", [])[:2])
        items.append(
            (
                _prio(item.get("severity", "warning")),
                doc,
                f"{_book(doc)}格式不规范（{prob}），{item.get('suggestion', '请对照附件4修正')}",
            )
        )

    items.sort(key=lambda x: x[0])
    sev_map = {0: "critical", 1: "warning", 2: "info"}
    return [
        f"- [ ] {_severity_icon(sev_map.get(p, 'info'))} {text}" for p, _, text in items
    ]


def _render_executive_summary(data: dict[str, Any]) -> str:
    stats = data["summary_stats"]
    meta = data["meta"]
    total = stats["total"]
    critical = stats["critical"]
    warning = stats["warning"]

    if total == 0:
        verdict = "当前申报资料包在系统核查范围内未发现合规风险，建议仍由注册事务人员人工复核后提交。"
    elif critical > 0:
        verdict = (
            f"存在 🔴 **{critical}** 项严重风险（主要为法规要求的必要文件缺失），"
            "暂不具备直接提交条件，须优先补齐后再行申报。"
        )
    elif warning > 0:
        verdict = (
            f"未发现致命文件缺失，但存在 🟡 **{warning}** 项警告级问题"
            "（跨文档信息不一致或章节/格式不规范），建议在补正统一后再提交。"
        )
    else:
        verdict = "仅存在 🔵 提示级事项，整体风险可控，建议逐项确认后提交。"

    lines = [
        f"本次共扫描申报文件 **{meta['scan_count']}** 份，"
        f"自动生成输出文件 **{meta['filled_count']}** 份；"
        f"共识别合规风险 **{total}** 项（🔴 严重 {critical} / 🟡 警告 {warning}）。",
        "",
        verdict,
    ]
    if meta.get("product_name") and meta["product_name"] != "未提及":
        lines.append("")
        lines.append(f"核查对象产品：**{meta['product_name']}**")
    return "\n".join(lines)


def _render_completeness_dimension(data: dict[str, Any]) -> str:
    items = data.get("completeness", [])
    if not items:
        return "未发现法规完整性缺失项（对照 CMDE 2021年第121号公告附件4及 CH1 监管信息要求）。"

    lines: list[str] = []
    for item in items:
        badge = _severity_badge(item["severity"])
        ref = item.get("regulation_ref", "")
        ref_txt = f"（依据：{ref}）" if ref else ""
        notify = item.get("notify", "注册事务负责人")
        lines.append(
            f"- {badge} {item['message']}{ref_txt}。"
            f" {item.get('suggestion', '请补充提交')}。"
            f" → 通知 **{notify}**"
        )
    return "\n".join(lines)


def _render_consistency_dimension(data: dict[str, Any]) -> str:
    items = data.get("consistency", [])
    if not items:
        return "未发现跨文档核心字段冲突，产品名称、注册人信息等关键字段在各申报文件中保持一致。"

    lines: list[str] = []
    for item in items:
        label = item.get("label", "字段")
        sev = item.get("severity", "warning")
        values = item.get("values", {})
        parts = [f"在{_book(k)}中为「{v}」" for k, v in values.items()]
        body = "，".join(parts)
        lines.append(
            f"- {_severity_badge(sev)} **{label}**跨文档不一致。{body}。"
            " 存在套用旧模板或填写遗漏风险，请严格核对并全量替换统一。"
        )
    return "\n".join(lines)


def _render_normative_dimension(data: dict[str, Any]) -> str:
    norm = data.get("normative", {})
    structure = norm.get("structure", [])
    fmt = norm.get("format", [])
    if not structure and not fmt:
        return "各文档章节结构与格式符合附件4及 NMPA 说明书编写指导原则的基本要求。"

    lines: list[str] = []
    for item in structure:
        doc = item["doc_name"]
        missing = "、".join(item.get("missing_sections", []))
        sev = item.get("severity", "warning")
        lines.append(
            f"- {_severity_badge(sev)} {_book(doc)}章节结构不规范，"
            f"缺失法定必检项：{missing}。请参照《体外诊断试剂说明书编写指导原则》补充撰写。"
        )
    for item in fmt:
        doc = item["doc_name"]
        prob = "；".join(item.get("problems", []))
        ref = item.get("regulation_ref", "附件4")
        sev = item.get("severity", "warning")
        lines.append(
            f"- {_severity_badge(sev)} {_book(doc)}格式不符合 {ref} 要求：{prob}。"
            f" {item.get('suggestion', '请对照附件4修正')}。"
        )
    return "\n".join(lines)


def _normalize_severity_badges(text: str) -> str:
    """将 LLM 可能输出的 [严重风险] 括号格式统一为图标徽章。"""
    pairs = (
        ("critical", r"\[?\*?\[?严重风险\]?\*?\]?"),
        ("warning", r"\[?\*?\[?警告风险\]?\*?\]?"),
        ("info", r"\[?\*?\[?提示\]?\*?\]?"),
    )
    for sev, pat in pairs:
        badge = _severity_badge(sev)
        text = re.sub(rf"-\s*\*\*{pat}\*\*", f"- {badge}", text)
        text = re.sub(rf"-\s*{pat}", f"- {badge}", text)
    return text


def render_ra_report_body(data: dict[str, Any]) -> str:
    """规则模板：生成四维度 RA 风格正文（无 LLM）。"""
    sections = [
        "## 执行摘要",
        "",
        _render_executive_summary(data),
        "",
        "## 维度一：法规完整性缺失预警",
        "",
        _render_completeness_dimension(data),
        "",
        "## 维度二：跨文档一致性预警",
        "",
        _render_consistency_dimension(data),
        "",
        "## 维度三：文档章节与格式规范性预警",
        "",
        _render_normative_dimension(data),
        "",
        "## 维度四：风险分级与处理建议汇总（Action Items）",
        "",
    ]
    actions = _build_action_items(data)
    if actions:
        sections.extend(actions)
    else:
        sections.append("当前未发现需处理的合规风险事项。")
    return "\n".join(sections)


def generate_report(
    file_list: list[FileInfo],
    extracted: ExtractedInfo,
    completeness: list[CompletenessIssue],
    consistency: list[ConsistencyIssue],
    structure: list[StructureIssue],
    format_issues: list[FormatIssue],
    filled_files: list[str],
    output_path: Path,
    use_llm_polish: bool = True,
) -> Path:
    ensure_dir(output_path.parent)
    data = build_structured_report_data(
        file_list, extracted, completeness, consistency, structure, format_issues, filled_files
    )
    save_json(output_path.parent / "合规风险预警.json", data)

    llm_on = should_use_llm(use_llm_polish)
    body = generate_risk_report_llm(data, enabled=use_llm_polish) if llm_on else None
    report_source = "大模型 RA 报告"
    if not body:
        body = render_ra_report_body(data)
        report_source = "规则引擎 RA 模板" if not llm_on else "规则引擎 RA 模板（LLM 不可用时的兜底）"
    else:
        body = _normalize_severity_badges(body)

    header = [
        "# 合规风险预警与处理建议报告",
        "",
        f"> 生成时间：{data['meta']['generated_at']}",
        f"> 报告来源：{report_source}",
        f"> 法规依据：[CMDE 2021年第121号公告](https://www.cmde.org.cn/flfg/fgwj/ggtg/20210930163300622.html) "
        "及附件4《体外诊断试剂注册申报资料要求及说明》",
        "",
    ]

    appendix = [
        "",
        "---",
        "",
        "## 附录：扫描与输出统计",
        "",
        f"- 扫描文件数：{data['meta']['scan_count']}",
        f"- 已生成输出文件：{data['meta']['filled_count']}",
        f"- 问题统计：🔴 严重 {data['summary_stats']['critical']} / "
        f"🟡 警告 {data['summary_stats']['warning']} / "
        f"🔵 提示 {data['summary_stats']['info']}",
    ]
    if data.get("filled_files"):
        appendix.append("- 已生成文件：" + "、".join(f"`{n}`" for n in data["filled_files"]))

    from core.run_logger import get_run_logger

    logger = get_run_logger()
    if logger:
        stats = data["summary_stats"]
        logger.python_only(
            "阶段5 · 生成合规报告",
            f"{'大模型撰写四维度 RA 报告' if report_source.startswith('大模型') else 'Python RA 话术模板'}；"
            f"共 {stats['total']} 个问题 → 报告已写入 {output_path.name}",
        )

    output_path.write_text("\n".join(header) + body + "\n".join(appendix), encoding="utf-8")
    return output_path
