from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from core.checker import check_completeness
from core.llm_checker import run_cross_check
from core.extractor import ExtractedInfo, extract_from_upload
from core.filler import fill_templates
from core.reporter import generate_report
from core.run_logger import RunLogger
from core.scanner import (
    FileInfo,
    append_output_files,
    build_catalog_dataframe,
    build_classified_catalog,
    export_ch12_excel,
    scan_directory,
    summarize_classification,
)
from core.utils import DEFAULT_OUTPUT, ensure_dir, save_json


@dataclass
class PipelineResult:
    file_list: list[FileInfo] = field(default_factory=list)
    catalog_df: pd.DataFrame | None = None
    catalog_by_category: dict[str, pd.DataFrame] = field(default_factory=dict)
    extracted: ExtractedInfo | None = None
    completeness_issues: list = field(default_factory=list)
    consistency_issues: list = field(default_factory=list)
    structure_issues: list = field(default_factory=list)
    format_issues: list = field(default_factory=list)
    consistency_matrix: dict = field(default_factory=dict)
    filled_files: list[str] = field(default_factory=list)
    output_files: dict[str, str] = field(default_factory=dict)
    report_path: str | None = None
    use_llm: bool = False
    llm_active: bool = False
    log_path: str | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "files_scanned": len(self.file_list),
            "completeness_issues": len(self.completeness_issues),
            "consistency_issues": len(self.consistency_issues),
            "structure_issues": len(self.structure_issues),
            "format_issues": len(self.format_issues),
            "filled_files": len(self.filled_files),
            "report": self.report_path,
            "use_llm": self.use_llm,
            "llm_active": self.llm_active,
            "log_path": self.log_path,
        }


def run_pipeline(
    upload_dir: Path,
    output_dir: Path | None = None,
    *,
    use_llm: bool = True,
    log_source: str = "CLI / 脚本",
) -> PipelineResult:
    from core.llm_client import should_use_llm

    output_dir = ensure_dir(output_dir or DEFAULT_OUTPUT)
    result = PipelineResult(use_llm=use_llm, llm_active=should_use_llm(use_llm))

    with RunLogger(upload_dir, output_dir, use_llm=use_llm, source=log_source) as log:
        # 阶段一：Scanner
        log.section("扫描申报文件夹", "阶段 1/5")
        log.doing("遍历您上传的文件夹，找出所有 docx / pdf / doc，并统计页数。")
        log.engine("Python", "core/scanner.py — 纯程序扫描，不调用大模型")
        log.think("审核第一步必须先搞清楚「有哪些文件」，后面才能对照 NMPA 清单查缺。")

        result.file_list = scan_directory(upload_dir)
        counts = summarize_classification(result.file_list)
        log.engine("Python 规则引擎", "config/file_catalog.json — 自动归类为三类目录")
        log.think(
            "上传文件按业务角色拆分：核心数据源（说明书等）、申报原始模版（CH1 表格）、"
            "输出文档模版（流水线填写后生成，此阶段先留空）。"
        )
        for label, n in counts.items():
            if n:
                log.bullet(f"{label}：{n} 个")
        result.catalog_by_category = build_classified_catalog(result.file_list)
        result.catalog_df = build_catalog_dataframe(result.file_list)
        excel_path = export_ch12_excel(result.file_list, output_dir / "CH1.2_文件目录汇总.xlsx")
        result.output_files["catalog_excel"] = str(excel_path)

        log.result(f"共扫描到 {len(result.file_list)} 个文件，已导出 CH1.2 目录表。")
        for fi in result.file_list[:8]:
            log.bullet(f"{fi.file_name} — {fi.page_count} 页 · {fi.file_format}")
        if len(result.file_list) > 8:
            log.bullet(f"…… 还有 {len(result.file_list) - 8} 个文件")
        log.stage_done(f"阶段1完成：共 {len(result.file_list)} 个文件，CH1.2 目录表已导出。")

        # 阶段二：完整性
        log.section("完整性核查", "阶段 2/5")
        log.doing("对照 CMDE 2021年第121号公告及附件4，检查申报资料是否齐全。")
        log.engine(
            "Python 规则引擎",
            "config/nmpa_rules.json — 含公告7个附件配置 + 附件4各章必交项 + CH1 监管信息",
        )
        log.think(
            "法规来源：https://www.cmde.org.cn/flfg/fgwj/ggtg/20210930163300622.html；"
            "缺失项将标注法规依据并通知注册事务负责人。"
        )

        result.completeness_issues = check_completeness(result.file_list)

        if result.completeness_issues:
            log.result(f"发现 {len(result.completeness_issues)} 个完整性问题。")
            for issue in result.completeness_issues:
                ref = f" [{issue.regulation_ref}]" if issue.regulation_ref else ""
                log.bullet(f"[{issue.severity}] {issue.message}{ref} → 通知 {issue.notify}")
        else:
            log.result("在当前 Demo 规则范围内，未发现缺失项。")
        log.stage_done(
            f"阶段2完成：完整性核查结束，{'发现 ' + str(len(result.completeness_issues)) + ' 个问题' if result.completeness_issues else '未发现缺失'}（纯 Python 规则，未用大模型）。"
        )

        # 阶段三：Extractor
        log.section("从产品说明书提取关键信息", "阶段 3/5")
        log.doing("打开「产品说明书」类 docx，用正则抽取产品名称、预期用途等字段。")
        if result.llm_active:
            log.engine("Python 规则 + 大模型 DeepSeek", "规则先抽，大模型再精炼语义字段（预期用途、检测原理等）")
            log.think("结构化章节用正则最稳；长段落语义理解交给大模型，但规则结果仍作对照。")
        else:
            log.engine("Python 规则引擎", "core/extractor.py — 纯正则提取，未配置或未启用大模型")
            log.think("没有 API Key 或您关闭了 LLM 时，只靠规则也能完成 Demo。")

        result.extracted = extract_from_upload(upload_dir, use_llm=use_llm)
        save_json(output_dir / "extracted_fields.json", result.extracted.to_dict())

        if result.extracted.confidence.get("_error"):
            log.result(result.extracted.confidence["_error"])
        else:
            ex = result.extracted
            log.result(f"已从「{ex.source_file}」提取信息。")
            log.bullet(f"产品名称：{ex.product_name}")
            log.bullet(f"预期用途：{str(ex.intended_use)[:80]}{'…' if len(str(ex.intended_use)) > 80 else ''}")
            log.bullet(f"包装规格：{ex.pack_specs}")
            if ex.llm_used:
                llm_fields = [k for k, v in ex.confidence.items() if "LLM" in str(v)]
                log.bullet(f"大模型参与精炼的字段：{', '.join(llm_fields) or '无'}")
            else:
                log.bullet("本次提取未调用大模型。")
        log.stage_done(
            f"阶段3完成：说明书字段已提取"
            f"{'（含大模型精炼）' if result.extracted and result.extracted.llm_used else '（纯规则）'}。"
        )

        # 阶段四：Filler + 任务4（结构/一致性/格式）
        log.section("自动填写模板 + 结构/一致性/格式核查", "阶段 4/5")
        log.doing("用提取结果填写 CH1.4 / CH1.5 / CH1.11.x 等申报模版（Python 按 field_mapping.json 写入）。")
        log.engine("Python + 配置映射", "说明书→ExtractedInfo（规则+可选LLM）；填表不读 CH 模版模拟数据")
        log.think("方案B：大模型只理解说明书；Python 复制模版并按配置替换单元格/声明段落。")

        result.filled_files = fill_templates(
            upload_dir,
            output_dir,
            result.extracted,
            file_list=result.file_list,
        )
        result.file_list = append_output_files(result.file_list, result.filled_files)
        result.catalog_by_category = build_classified_catalog(result.file_list)
        result.catalog_df = build_catalog_dataframe(result.file_list)
        export_ch12_excel(result.file_list, output_dir / "CH1.2_文件目录汇总.xlsx")

        if result.llm_active:
            log.engine(
                "大模型逐份分析 + Python 比对",
                "结构/格式：每份文档单独调用 LLM；一致性：逐份提取字段 JSON 后程序比对（非 7 份全文一次塞入）",
            )
            log.think(
                "任务4 三步：① 章节/性能必检项 ② 跨文档字段一致性 ③ 附件4 格式规范；"
                "比对结论由 Python normalize 判定，LLM 只负责理解与提取。"
            )
        else:
            log.engine("Python 规则引擎", "config/cross_check_config.json + field_mapping.json")

        cross = run_cross_check(upload_dir, result.filled_files, use_llm=use_llm)
        result.consistency_issues = cross.consistency_issues
        result.structure_issues = cross.structure_issues
        result.format_issues = cross.format_issues
        result.consistency_matrix = cross.field_matrix

        if result.filled_files:
            log.result(f"已生成 {len(result.filled_files)} 份已填写模板。")
            for fp in result.filled_files:
                log.bullet(Path(fp).name)
        else:
            log.result("未生成已填写模板（可能缺少源模板文件）。")

        if result.consistency_issues:
            log.result(f"发现 {len(result.consistency_issues)} 处一致性问题。")
            for issue in result.consistency_issues:
                vals = "；".join(f"{k}「{v[:40]}」" for k, v in issue.values.items())
                log.bullet(f"{issue.label}：{vals}")
        else:
            log.result("跨文档字段一致，未发现冲突。")

        if result.structure_issues:
            for s in result.structure_issues:
                log.bullet(f"「{s.doc_name}」缺少：{', '.join(s.missing_sections)}")
        else:
            log.bullet("章节/必检项检查通过。")

        if result.format_issues:
            log.result(f"发现 {len(result.format_issues)} 处格式规范问题。")
            for f in result.format_issues:
                log.bullet(f"{f.doc_name}：{'; '.join(f.problems[:2])}")
        else:
            log.bullet("附件4 格式规范检查通过。")

        save_json(
            output_dir / "完整性核查报告.json",
            [issue.__dict__ for issue in result.completeness_issues],
        )
        save_json(
            output_dir / "一致性核查报告.json",
            [issue.__dict__ for issue in result.consistency_issues],
        )
        save_json(
            output_dir / "格式规范核查报告.json",
            [issue.__dict__ for issue in result.format_issues],
        )
        if result.consistency_matrix:
            save_json(output_dir / "一致性字段矩阵.json", result.consistency_matrix)

        log.stage_done(
            f"阶段4完成：填写 {len(result.filled_files)} 份 Word，"
            f"一致性 {len(result.consistency_issues)} 处、章节 {len(result.structure_issues)} 处、格式 {len(result.format_issues)} 处问题。"
        )

        # 阶段五：Reporter（任务5）
        log.section("合规风险预警与处理建议", "阶段 5/5")
        log.doing("将完整性、一致性、章节/格式问题汇总为四维度 RA 风格报告。")
        if result.llm_active:
            log.engine(
                "四维度结构化 JSON + 大模型 RA 撰写",
                "规则引擎提供判定事实；DeepSeek 按 RA 话术输出预警与 Action Items",
            )
            log.think(
                "任务5 四维度：① 法规完整性 ② 跨文档一致性 ③ 章节/格式规范性 ④ To-Do List；"
                "LLM 不得编造或改变严重等级。"
            )
        else:
            log.engine("Python RA 模板", "core/reporter.py — 规则引擎结论 + 注册专员话术模板")

        report_path = generate_report(
            result.file_list,
            result.extracted,
            result.completeness_issues,
            result.consistency_issues,
            result.structure_issues,
            result.format_issues,
            result.filled_files,
            output_dir / "风险预警报告.md",
            use_llm_polish=use_llm,
        )
        result.report_path = str(report_path)
        result.output_files["report"] = str(report_path)
        log.result(f"报告已保存：{report_path.name}")
        log.stage_done("阶段5完成：四维度合规风险预警报告已生成，详见上文大模型/模板撰写记录。")

        log.finish(result)
        result.log_path = str(log.log_path)

    return result
