from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from core.checker import check_completeness, check_consistency, check_manual_structure
from core.extractor import ExtractedInfo, extract_from_upload
from core.filler import fill_templates
from core.reporter import generate_report
from core.scanner import FileInfo, build_catalog_dataframe, export_ch12_excel, scan_directory
from core.utils import DEFAULT_OUTPUT, ensure_dir, save_json


@dataclass
class PipelineResult:
    file_list: list[FileInfo] = field(default_factory=list)
    catalog_df: pd.DataFrame | None = None
    extracted: ExtractedInfo | None = None
    completeness_issues: list = field(default_factory=list)
    consistency_issues: list = field(default_factory=list)
    structure_issues: list = field(default_factory=list)
    filled_files: list[str] = field(default_factory=list)
    output_files: dict[str, str] = field(default_factory=dict)
    report_path: str | None = None
    use_llm: bool = False
    llm_active: bool = False

    def summary(self) -> dict[str, Any]:
        return {
            "files_scanned": len(self.file_list),
            "completeness_issues": len(self.completeness_issues),
            "consistency_issues": len(self.consistency_issues),
            "structure_issues": len(self.structure_issues),
            "filled_files": len(self.filled_files),
            "report": self.report_path,
            "use_llm": self.use_llm,
            "llm_active": self.llm_active,
        }


def run_pipeline(
    upload_dir: Path,
    output_dir: Path | None = None,
    *,
    use_llm: bool = True,
) -> PipelineResult:
    from core.llm_client import should_use_llm

    output_dir = ensure_dir(output_dir or DEFAULT_OUTPUT)
    result = PipelineResult(use_llm=use_llm, llm_active=should_use_llm(use_llm))

    # 阶段一：Scanner
    result.file_list = scan_directory(upload_dir)
    result.catalog_df = build_catalog_dataframe(result.file_list)
    excel_path = export_ch12_excel(result.file_list, output_dir / "CH1.2_文件目录汇总.xlsx")
    result.output_files["catalog_excel"] = str(excel_path)

    # 阶段二：完整性
    result.completeness_issues = check_completeness(result.file_list)

    # 阶段三：Extractor
    result.extracted = extract_from_upload(upload_dir, use_llm=use_llm)
    save_json(output_dir / "extracted_fields.json", result.extracted.to_dict())

    # 阶段四：Filler + 一致性
    result.filled_files = fill_templates(upload_dir, output_dir, result.extracted)
    result.consistency_issues = check_consistency(upload_dir)
    result.structure_issues = check_manual_structure(upload_dir)

    save_json(
        output_dir / "完整性核查报告.json",
        [issue.__dict__ for issue in result.completeness_issues],
    )
    save_json(
        output_dir / "一致性核查报告.json",
        [issue.__dict__ for issue in result.consistency_issues],
    )

    # 阶段五：Reporter
    report_path = generate_report(
        result.file_list,
        result.extracted,
        result.completeness_issues,
        result.consistency_issues,
        result.structure_issues,
        result.filled_files,
        output_dir / "风险预警报告.md",
        use_llm_polish=use_llm,
    )
    result.report_path = str(report_path)
    result.output_files["report"] = str(report_path)

    return result
