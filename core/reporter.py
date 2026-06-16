from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from core.checker import CompletenessIssue, ConsistencyIssue, StructureIssue
from core.extractor import ExtractedInfo
from core.llm_client import polish_report, should_use_llm
from core.scanner import FileInfo
from core.utils import ensure_dir


def _severity_icon(severity: str) -> str:
    return {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(severity, "⚪")


def build_issues_payload(
    completeness: list[CompletenessIssue],
    consistency: list[ConsistencyIssue],
    structure: list[StructureIssue],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for item in completeness:
        issues.append(
            {
                "type": "completeness",
                "severity": item.severity,
                "message": item.message,
                "suggestion": item.suggestion,
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
            }
        )
    for item in structure:
        issues.append(
            {
                "type": "structure",
                "severity": item.severity,
                "message": f"{item.doc_name} 缺少章节: {', '.join(item.missing_sections)}",
                "suggestion": "请按 NMPA 说明书编写指导原则补全必检章节",
            }
        )
    return issues


def generate_report(
    file_list: list[FileInfo],
    extracted: ExtractedInfo,
    completeness: list[CompletenessIssue],
    consistency: list[ConsistencyIssue],
    structure: list[StructureIssue],
    filled_files: list[str],
    output_path: Path,
    use_llm_polish: bool = True,
) -> Path:
    ensure_dir(output_path.parent)
    issues = build_issues_payload(completeness, consistency, structure)
    critical = sum(1 for i in issues if i["severity"] == "critical")
    warning = sum(1 for i in issues if i["severity"] == "warning")
    llm_on = should_use_llm(use_llm_polish)

    lines = [
        "# 合规风险预警报告",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 大模型：{'已启用（提取增强 + 报告润色）' if llm_on else '未启用（仅规则引擎）'}",
        "",
        "## 执行摘要",
        "",
        f"- 扫描文件数：**{len(file_list)}**",
        f"- 发现问题：**{len(issues)}**（严重 {critical} / 警告 {warning}）",
        f"- 已生成输出文件：**{len(filled_files)}**",
        f"- 提取阶段 LLM：**{'是' if getattr(extracted, 'llm_used', False) else '否'}**",
        "",
        "## 一、文件完整性问题",
        "",
    ]

    if completeness:
        lines.append("| 等级 | 问题 | 处理建议 |")
        lines.append("|------|------|----------|")
        for item in completeness:
            lines.append(
                f"| {_severity_icon(item.severity)} {item.severity} | {item.message} | {item.suggestion} |"
            )
    else:
        lines.append("未发现完整性缺失项（在当前 Demo 规则范围内）。")

    lines.extend(["", "## 二、信息提取结果", "", "| 字段 | 提取值 | 置信度 |", "|------|--------|--------|"])
    for key, val in extracted.to_dict().items():
        if key in ("confidence", "targets", "llm_used"):
            continue
        conf = extracted.confidence.get(key, "-")
        display = val if not isinstance(val, list) else "、".join(val)
        if len(str(display)) > 80:
            display = str(display)[:77] + "..."
        lines.append(f"| {key} | {display} | {conf} |")

    lines.extend(["", "## 三、一致性问题", ""])
    if consistency:
        lines.append("| 等级 | 字段 | 详情 | 处理建议 |")
        lines.append("|------|------|------|----------|")
        for item in consistency:
            detail = "; ".join(f"{k}: {v[:40]}..." if len(v) > 40 else f"{k}: {v}" for k, v in item.values.items())
            lines.append(
                f"| {_severity_icon(item.severity)} {item.severity} | {item.label} | {detail} | {item.suggestion} |"
            )
    else:
        lines.append("未发现跨文档一致性问题。")

    lines.extend(["", "## 四、说明书章节规范性", ""])
    if structure:
        for item in structure:
            lines.append(f"- **{item.doc_name}**：缺少 {', '.join(item.missing_sections)}")
    else:
        lines.append("说明书必检章节完整。")

    lines.extend(["", "## 五、已生成文件", ""])
    for f in filled_files:
        lines.append(f"- `{f}`")

    lines.extend(["", "## 六、处理建议汇总", ""])
    if issues:
        for i, issue in enumerate(issues, 1):
            lines.append(f"{i}. [{issue['severity']}] {issue['message']} → {issue['suggestion']}")
    else:
        lines.append("当前未发现需处理的合规风险。")

    if use_llm_polish:
        polished = polish_report(issues, enabled=use_llm_polish)
        if polished:
            lines.extend(["", "## 七、LLM 润色建议（非判定依据）", "", polished])

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
