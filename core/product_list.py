from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document

from core.extractor import ExtractedInfo, read_docx_full_text
from core.llm_client import call_llm, should_use_llm
from core.utils import read_prompt


@dataclass
class ProductComponent:
    category: str
    name: str
    composition: str
    qty_24: str = ""
    qty_48: str = ""
    qty_96: str = ""


@dataclass
class ProductListData:
    pack_labels: dict[str, str] = field(default_factory=dict)
    catalog_numbers: dict[str, str] = field(default_factory=dict)
    spec_a: list[ProductComponent] = field(default_factory=list)
    spec_b: list[ProductComponent] = field(default_factory=list)
    comparison: list[dict[str, str]] = field(default_factory=list)
    source: str = "规则"

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_labels": self.pack_labels,
            "catalog_numbers": self.catalog_numbers,
            "spec_a": [c.__dict__ for c in self.spec_a],
            "spec_b": [c.__dict__ for c in self.spec_b],
            "comparison": self.comparison,
            "source": self.source,
        }


_PACK_KEYS = (
    "spec_a_24",
    "spec_a_48",
    "spec_a_96",
    "spec_b_24",
    "spec_b_48",
    "spec_b_96",
)

_CATEGORY_RULES = (
    (r"增强剂", "增强剂"),
    (r"阳性对照|阴性对照|对照品", "质控品"),
    (r"处理液|保存液", "处理液"),
    (r"反应液|PCR", "反应液"),
)


def _guess_category(name: str) -> str:
    for pat, cat in _CATEGORY_RULES:
        if re.search(pat, name, re.I):
            return cat
    return "其他"


def _norm_cell(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def _is_covid_product(product_name: str) -> bool:
    return any(k in product_name for k in ("2019-nCoV", "新型冠状病毒", "新冠", "SARS-CoV-2"))


def _canonicalize_component_name(name: str, product_name: str = "") -> str:
    """统一组分命名：新冠类产品中 nCoV 阳性对照等须带 2019- 前缀。"""
    name = _norm_cell(name)
    if not name or not _is_covid_product(product_name):
        return name
    fixed = re.sub(r"(?<![\w-])nCoV(?=\s*阳性|\s*阴性|\s*PCR|阳性|阴性)", "2019-nCoV", name, flags=re.I)
    fixed = re.sub(r"2019-2019-", "2019-", fixed)
    return fixed


def _is_composition_table(header: list[str]) -> bool:
    joined = "".join(header)
    return "组分" in joined and "主要组成成分" in joined and "24人份" in joined


def _parse_composition_table(table: Any, *, product_name: str = "") -> list[ProductComponent]:
    rows = table.rows
    if len(rows) < 2:
        return []
    header = [_norm_cell(c.text) for c in rows[0].cells]
    if not _is_composition_table(header):
        return []

    qty_cols: dict[str, int] = {}
    for i, h in enumerate(header):
        if "24人份" in h:
            qty_cols["24"] = i
        elif "48人份" in h:
            qty_cols["48"] = i
        elif "96人份" in h:
            qty_cols["96"] = i

    name_col = next((i for i, h in enumerate(header) if "组分" in h), 0)
    comp_col = next((i for i, h in enumerate(header) if "主要组成成分" in h), 1)

    components: list[ProductComponent] = []
    for row in rows[1:]:
        cells = [_norm_cell(c.text) for c in row.cells]
        if not any(cells):
            continue
        name = _canonicalize_component_name(cells[name_col] if name_col < len(cells) else "", product_name)
        if not name or name in ("组分", "-", "/"):
            continue
        composition = cells[comp_col] if comp_col < len(cells) else ""
        components.append(
            ProductComponent(
                category=_guess_category(name),
                name=name,
                composition=composition,
                qty_24=cells[qty_cols["24"]] if "24" in qty_cols and qty_cols["24"] < len(cells) else "",
                qty_48=cells[qty_cols["48"]] if "48" in qty_cols and qty_cols["48"] < len(cells) else "",
                qty_96=cells[qty_cols["96"]] if "96" in qty_cols and qty_cols["96"] < len(cells) else "",
            )
        )
    return components


def _parse_pack_labels(pack_specs: str) -> dict[str, str]:
    labels = {k: "" for k in _PACK_KEYS}
    defaults = {
        "spec_a_24": "规格A：24人份/盒",
        "spec_a_48": "规格A：48人份/盒",
        "spec_a_96": "规格A：96人份/盒",
        "spec_b_24": "规格B：24人份/盒",
        "spec_b_48": "规格B：48人份/盒",
        "spec_b_96": "规格B：96人份/盒",
    }
    if not pack_specs or pack_specs == "未提及":
        return defaults

    for spec, letter in (("规格A", "a"), ("规格B", "b")):
        m = re.search(rf"{spec}[：:](.*?)(?=规格[AB]|$)", pack_specs)
        if not m:
            continue
        block = m.group(1)
        bulk_m = re.search(r"大包装[：:]([^；;]+)", block)
        tube_m = re.search(r"分管包装[：:]([^；;]+)", block)
        for size in ("24", "48", "96"):
            size_pat = rf"{size}\s*人份/盒"
            if not re.search(size_pat, block):
                continue
            parts: list[str] = []
            if bulk_m and re.search(size_pat, bulk_m.group(1)):
                parts.append(f"大包装：{size}人份/盒")
            if tube_m and re.search(size_pat, tube_m.group(1)):
                parts.append(f"分管包装：{size}人份/盒")
            if parts:
                labels[f"spec_{letter}_{size}"] = f"{spec}：" + "；".join(parts)
            else:
                labels[f"spec_{letter}_{size}"] = f"{spec}：{size}人份/盒"

    for k, v in defaults.items():
        if not labels.get(k):
            labels[k] = v
    return labels


def _extract_catalog_from_text(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for m in re.finditer(
        r"(规格A|规格B)[：:\s]*(?:大包装|分管包装)?[：:\s]*(\d+)人份/盒[^0-9]{0,20}(601\d{7,8}|\d{10})",
        text,
    ):
        key = f"spec_{'a' if 'A' in m.group(1) else 'b'}_{m.group(2)}"
        found[key] = m.group(3)
    for m in re.finditer(r"货号[：:\s]*(\d{10,12})", text):
        # single catalog without pack mapping — skip
        pass
    return found


def _norm_component_name(name: str) -> str:
    n = _norm_cell(name).lower().replace(" ", "")
    n = re.sub(r"2019[-]?ncov", "ncov", n)
    return n


def _build_comparison(spec_a: list[ProductComponent], spec_b: list[ProductComponent]) -> list[dict[str, str]]:
    a_map = {_norm_component_name(c.name): c for c in spec_a}
    b_map = {_norm_component_name(c.name): c for c in spec_b}
    order = list(dict.fromkeys([_norm_component_name(c.name) for c in spec_a] + [_norm_component_name(c.name) for c in spec_b]))
    rows: list[dict[str, str]] = []

    for key in order:
        a_comp = a_map.get(key)
        b_comp = b_map.get(key)
        if not a_comp and not b_comp:
            continue
        display_name = (a_comp or b_comp).name
        a_text = a_comp.composition if a_comp else "/"
        b_text = b_comp.composition if b_comp else "/"
        if a_comp and b_comp:
            same = "相同" if _norm_cell(a_comp.composition) == _norm_cell(b_comp.composition) else "不同"
        else:
            same = "不同"
        rows.append(
            {
                "name": display_name,
                "spec_a_composition": a_text,
                "spec_b_composition": b_text,
                "same_or_diff": same,
            }
        )
    return rows


def extract_product_list_by_rules(manual: Path, info: ExtractedInfo) -> ProductListData:
    doc = Document(str(manual))
    product_name = info.product_name if info.product_name != "未提及" else ""
    comp_tables: list[list[ProductComponent]] = []
    for table in doc.tables:
        parsed = _parse_composition_table(table, product_name=product_name)
        if parsed:
            comp_tables.append(parsed)

    data = ProductListData()
    data.pack_labels = _parse_pack_labels(info.pack_specs)
    data.catalog_numbers = _extract_catalog_from_text(read_docx_full_text(manual))

    if comp_tables:
        data.spec_a = comp_tables[0]
        data.spec_b = comp_tables[2] if len(comp_tables) >= 3 else (comp_tables[1] if len(comp_tables) >= 2 else comp_tables[0])
        if len(comp_tables) >= 3 and any("增强剂" in c.name for c in comp_tables[2]):
            data.spec_b = comp_tables[2]
        elif any("增强剂" in c.name for c in (comp_tables[-1] if comp_tables else [])):
            data.spec_b = comp_tables[-1]

    data.comparison = _build_comparison(data.spec_a, data.spec_b)
    data.source = "规则"
    return data


def _merge_llm_product_list(data: ProductListData, llm: dict[str, Any], *, product_name: str = "") -> ProductListData:
    if not llm:
        return data

    for key in _PACK_KEYS:
        val = (llm.get("pack_labels") or {}).get(key)
        if val:
            data.pack_labels[key] = str(val).strip()

    for key in _PACK_KEYS:
        val = (llm.get("catalog_numbers") or {}).get(key)
        if val and str(val).lower() not in ("null", "none", "未提及", ""):
            data.catalog_numbers[key] = str(val).strip()

    def _load_components(items: Any) -> list[ProductComponent]:
        if not isinstance(items, list):
            return []
        out: list[ProductComponent] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = _canonicalize_component_name(str(item.get("name", "")).strip(), product_name)
            if not name:
                continue
            out.append(
                ProductComponent(
                    category=str(item.get("category") or _guess_category(name)).strip(),
                    name=name,
                    composition=str(item.get("composition", "")).strip(),
                    qty_24=str(item.get("qty_24", "")).strip(),
                    qty_48=str(item.get("qty_48", "")).strip(),
                    qty_96=str(item.get("qty_96", "")).strip(),
                )
            )
        return out

    llm_a = _load_components(llm.get("spec_a_components"))
    llm_b = _load_components(llm.get("spec_b_components"))
    if llm_a:
        data.spec_a = llm_a
    if llm_b:
        data.spec_b = llm_b

    notes = llm.get("comparison_notes")
    if isinstance(notes, list) and notes:
        data.comparison = [
            {
                "name": str(n.get("name", "")).strip(),
                "spec_a_composition": str(n.get("spec_a_composition", "")).strip(),
                "spec_b_composition": str(n.get("spec_b_composition", "")).strip(),
                "same_or_diff": str(n.get("same_or_diff", "不同")).strip(),
            }
            for n in notes
            if isinstance(n, dict) and n.get("name")
        ]
    elif data.spec_a or data.spec_b:
        data.comparison = _build_comparison(data.spec_a, data.spec_b)

    data.source = "规则+LLM" if (llm_a or llm_b) else data.source + "+LLM"
    return data


def extract_product_list_with_llm(text: str) -> dict[str, Any]:
    purpose = "阶段3 · 提取 CH1.5 产品列表表格数据"
    request_brief = (
        "从说明书【主要组成成分】等章节提取规格A/B各组分、主要组成成分、规格数量、货号；"
        "找不到的货号填 null，禁止编造。"
    )
    prompt = read_prompt("product_list_prompt.md", TEXT=text[:14000])
    raw = call_llm(
        prompt,
        purpose=purpose,
        request_brief=request_brief,
        prompt_file="prompts/product_list_prompt.md",
    )
    if not raw:
        return {}
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def extract_product_list(
    manual: Path,
    info: ExtractedInfo,
    *,
    use_llm: bool = True,
) -> ProductListData:
    data = extract_product_list_by_rules(manual, info)

    from core.run_logger import get_run_logger

    logger = get_run_logger()
    if logger:
        logger.python_only(
            "阶段3 · 规则解析产品列表",
            f"规格A {len(data.spec_a)} 个组分、规格B {len(data.spec_b)} 个组分；"
            f"货号 {len(data.catalog_numbers)} 条（来自说明书原文）。",
        )

    if should_use_llm(use_llm):
        text = read_docx_full_text(manual)
        llm_data = extract_product_list_with_llm(text)
        if llm_data:
            data = _merge_llm_product_list(data, llm_data, product_name=info.product_name)
            if logger:
                logger.python_only(
                    "阶段3 · 大模型补充产品列表",
                    f"合并后规格A {len(data.spec_a)} 项、规格B {len(data.spec_b)} 项，来源={data.source}。",
                )
        elif logger:
            logger.python_only("阶段3 · 产品列表大模型未生效", "沿用规则解析的组成表格。")

    return data


def _qty_for_size(comp: ProductComponent, size: int | str) -> str:
    key = str(size)
    return {"24": comp.qty_24, "48": comp.qty_48, "96": comp.qty_96}.get(key, "")


def _load_product_list_from_info(info: ExtractedInfo) -> ProductListData:
    raw = info.product_list or {}
    if not raw:
        return ProductListData()

    def _comps(items: Any) -> list[ProductComponent]:
        if not isinstance(items, list):
            return []
        out: list[ProductComponent] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            out.append(
                ProductComponent(
                    category=str(item.get("category", "")),
                    name=str(item.get("name", "")),
                    composition=str(item.get("composition", "")),
                    qty_24=str(item.get("qty_24", "")),
                    qty_48=str(item.get("qty_48", "")),
                    qty_96=str(item.get("qty_96", "")),
                )
            )
        return out

    return ProductListData(
        pack_labels=dict(raw.get("pack_labels") or {}),
        catalog_numbers=dict(raw.get("catalog_numbers") or {}),
        spec_a=_comps(raw.get("spec_a")),
        spec_b=_comps(raw.get("spec_b")),
        comparison=list(raw.get("comparison") or []),
        source=str(raw.get("source") or "规则"),
    )


def apply_product_list_to_doc(
    doc: Document,
    info: ExtractedInfo,
    data: ProductListData | None = None,
) -> tuple[list[str], list[str]]:
    """将产品列表数据写入 CH1.5 两个表格。"""
    data = data or _load_product_list_from_info(info)
    written: list[str] = []
    skipped: list[str] = []

    if not doc.tables:
        return written, ["CH1.5 文档无表格"]

    product = info.product_name if info.product_name != "未提及" else ""
    if product:
        for para in doc.paragraphs:
            t = para.text.strip()
            if not t or "CH1.5" in t or "产品列表" in t or "监管信息" in t:
                continue
            if t in product or product in t:
                continue
            if ("呼吸道" in t or "肺炎支" in t) and len(t) < 100:
                if not (t.endswith("）") and "PCR" in t):
                    para.text = product.split("（")[0] if "（" in product else product
                    written.append("封面产品名称段落")
                    break

    if len(doc.tables) >= 1 and data.spec_a:
        table = doc.tables[0]
        blocks = [
            ("spec_a_24", 24, data.spec_a),
            ("spec_a_48", 48, data.spec_a),
            ("spec_a_96", 96, data.spec_a),
            ("spec_b_24", 24, data.spec_b or data.spec_a),
            ("spec_b_48", 48, data.spec_b or data.spec_a),
            ("spec_b_96", 96, data.spec_b or data.spec_a),
        ]
        row_idx = 1
        filled_rows = 0
        for pack_key, size, components in blocks:
            pack_label = data.pack_labels.get(pack_key) or (
                f"{'规格A' if 'spec_a' in pack_key else '规格B'}：{size}人份/盒"
            )
            catalog = data.catalog_numbers.get(pack_key) or "待补充"
            for comp in components:
                if row_idx >= len(table.rows):
                    break
                row = table.rows[row_idx]
                if len(row.cells) >= 6:
                    row.cells[0].text = pack_label
                    row.cells[1].text = catalog
                    row.cells[2].text = comp.category
                    row.cells[3].text = _canonicalize_component_name(comp.name, product)
                    row.cells[4].text = comp.composition
                    row.cells[5].text = _qty_for_size(comp, size)
                    filled_rows += 1
                row_idx += 1
        written.append(f"主表 {filled_rows} 行（包装规格/货号/组成/组分/成分/数量）")

    if len(doc.tables) >= 2 and data.comparison:
        table1 = doc.tables[1]
        for i, item in enumerate(data.comparison, start=1):
            if i >= len(table1.rows):
                break
            row = table1.rows[i]
            if len(row.cells) >= 4:
                row.cells[0].text = item.get("name", "")
                row.cells[1].text = item.get("spec_a_composition", "")
                row.cells[2].text = item.get("spec_b_composition", "")
                row.cells[3].text = item.get("same_or_diff", "")
        for i in range(len(data.comparison) + 1, len(table1.rows)):
            row = table1.rows[i]
            for cell in row.cells:
                cell.text = ""
        written.append(f"对比表 {len(data.comparison)} 行（规格A/B异同）")
    elif not data.comparison:
        skipped.append("对比表（未解析到规格A/B异同）")

    if not data.spec_a:
        skipped.append("主表（说明书未解析到【主要组成成分】表格）")

    return written, skipped
