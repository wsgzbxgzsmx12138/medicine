from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from docx import Document

from core.extractor import ExtractedInfo
from core.utils import ensure_dir, glob_files, load_json


def _set_table_cell_by_label(doc: Document, row_label: str, value: str) -> bool:
    label_norm = re.sub(r"\s+", "", row_label)
    for table in doc.tables:
        for row in table.rows:
            cells = row.cells
            if len(cells) < 2:
                continue
            row_text = "".join(c.text for c in cells[:2])
            if label_norm in re.sub(r"\s+", "", row_text):
                cells[1].text = value
                return True
    return False


def fill_ch14(template: Path, output: Path, info: ExtractedInfo, cfg: dict[str, Any]) -> Path:
    ensure_dir(output.parent)
    shutil.copy2(template, output)
    doc = Document(str(output))

    mapping = {
        "产品名称": info.product_name,
        "预期用途": info.intended_use,
        "包装规格": info.pack_specs,
        "产品储存条": info.storage_condition,
    }
    for label, val in mapping.items():
        if val and val != "未提及":
            _set_table_cell_by_label(doc, label, val)

    doc.save(str(output))
    return output


def fill_ch1111(template: Path, output: Path, info: ExtractedInfo) -> Path:
    ensure_dir(output.parent)
    shutil.copy2(template, output)
    doc = Document(str(output))

    if info.product_name and info.product_name != "未提及":
        for p in doc.paragraphs:
            if "申请境内第三类" in p.text:
                p.text = re.sub(
                    r"申请境内第三类体外诊断试剂.+?(产品注册|注册)",
                    lambda m: f"申请境内第三类体外诊断试剂{info.product_name}{m.group(1)}",
                    p.text,
                    count=1,
                )
                break

    doc.save(str(output))
    return output


def fill_templates(upload_dir: Path, output_dir: Path, info: ExtractedInfo) -> list[str]:
    mapping_cfg = load_json("field_mapping.json")
    filled: list[str] = []
    targets = mapping_cfg.get("targets", {})

    ch14_cfg = targets.get("CH1.4", {})
    tpl14 = glob_files(upload_dir, ch14_cfg.get("template_glob", "CH1.4*.docx"))
    if tpl14:
        out = output_dir / ch14_cfg.get("output", "CH1.4_申请表_已填写.docx")
        fill_ch14(tpl14[0], out, info, ch14_cfg)
        filled.append(str(out))

    ch111_cfg = targets.get("CH1.11.1", {})
    tpl111 = glob_files(upload_dir, ch111_cfg.get("template_glob", "CH1.11.1*.docx"))
    if tpl111:
        out = output_dir / ch111_cfg.get("output", "CH1.11.1_标准清单_已填写.docx")
        fill_ch1111(tpl111[0], out, info)
        filled.append(str(out))

    return filled
