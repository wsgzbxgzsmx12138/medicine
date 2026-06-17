from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from core.extractor import ExtractedInfo
from core.llm_client import call_llm, should_use_llm
from core.utils import load_json, read_prompt


@dataclass
class StandardEntry:
    std_no: str
    name: str
    source: str = "本地标准库"
    category: str = "通用"


@dataclass
class GuidanceEntry:
    title: str
    source: str
    note: str = ""


@dataclass
class StandardsFillData:
    standards: list[StandardEntry] = field(default_factory=list)
    guidance: list[GuidanceEntry] = field(default_factory=list)
    standard_products: list[str] = field(default_factory=list)
    standard_products_note: str = ""
    match_summary: str = ""
    source: str = "规则+本地库"


def _product_text(info: ExtractedInfo) -> str:
    parts = [
        info.product_name,
        info.intended_use,
        info.detection_principle,
        " ".join(info.targets),
        info.pos_rate,
        info.neg_rate,
        info.lod,
    ]
    return " ".join(p for p in parts if p and p != "未提及")


def _dedupe_standards(items: list[StandardEntry]) -> list[StandardEntry]:
    seen: set[str] = set()
    out: list[StandardEntry] = []
    for item in items:
        key = item.std_no.strip().upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _match_guidance(text: str, cfg: dict[str, Any]) -> list[GuidanceEntry]:
    out: list[GuidanceEntry] = []
    for doc in cfg.get("guidance_documents", []):
        keywords = doc.get("keywords") or []
        if any(kw in text for kw in keywords):
            out.append(
                GuidanceEntry(
                    title=str(doc.get("title", "")),
                    source=str(doc.get("source", "CMDE 本地库")),
                    note=str(doc.get("note", "")),
                )
            )
    return out


def _match_extra_standards(text: str, cfg: dict[str, Any]) -> list[StandardEntry]:
    out: list[StandardEntry] = []
    for item in cfg.get("target_specific_standards", []):
        keywords = item.get("keywords") or []
        if any(kw in text for kw in keywords):
            out.append(
                StandardEntry(
                    std_no=str(item.get("std_no", "")),
                    name=str(item.get("name", "")),
                    source=str(item.get("source", "靶标相关标准（本地库）")),
                    category="产品相关",
                )
            )
    return out


def _extract_standard_products(info: ExtractedInfo) -> tuple[list[str], str]:
    text = _product_text(info)
    items: list[str] = []
    if "国家参考品" in text:
        if "2019-nCoV" in text or "新冠" in text:
            items.append("2019-nCoV核酸检测试剂国家参考品（说明书【产品性能指标】性能评价引用）")
        else:
            items.append("国家参考品（说明书【产品性能指标】章节引用，具体名称见说明书）")
    if re.search(r"企业(阳性|阴性)(参考品|对照品)", text):
        items.append("企业阳性/阴性参考品（说明书性能评价中使用）")
    if items:
        return items, ""
    note = (
        "【系统检索说明】说明书中未单独列明「注册专用标准品清单」；"
        "如检验过程使用国家参考品或企业参考品，详见说明书【产品性能指标】章节。"
    )
    return [], note


def resolve_standards(info: ExtractedInfo, *, use_llm: bool = True) -> StandardsFillData:
    cfg = load_json("standards_list.json")
    text = _product_text(info)
    data = StandardsFillData()

    for item in cfg.get("universal_standards", []):
        data.standards.append(
            StandardEntry(
                std_no=str(item.get("std_no", "")),
                name=str(item.get("name", "")),
                source="通用 IVD 标准（本地库）",
                category="通用",
            )
        )

    method = "荧光PCR法" if "PCR" in info.product_name or "荧光" in info.product_name else "核酸检测"
    for key, std_nos in (cfg.get("method_specific") or {}).items():
        if key in text or key in method:
            for std_no in std_nos:
                for u in cfg.get("universal_standards", []):
                    if u.get("std_no") == std_no:
                        break
                else:
                    data.standards.append(
                        StandardEntry(
                            std_no=std_no,
                            name=f"方法学相关标准（{key}）",
                            source="方法学匹配（本地库）",
                            category="方法学",
                        )
                    )

    data.standards.extend(_match_extra_standards(text, cfg))
    data.standards = _dedupe_standards(data.standards)
    data.guidance = _match_guidance(text, cfg)
    products, prod_note = _extract_standard_products(info)
    data.standard_products = products
    data.standard_products_note = prod_note

    targets = "、".join(info.targets[:4]) if info.targets else "见说明书"
    data.match_summary = (
        f"方法学：{method}；检测靶标：{targets}；"
        f"匹配适用标准 {len(data.standards)} 项、指导原则 {len(data.guidance)} 项、"
        f"标准品 {len(data.standard_products)} 项。"
    )

    if should_use_llm(use_llm):
        llm_extra = _llm_supplement_standards(text, data)
        if llm_extra:
            data.source = "规则+本地库+LLM"

    return data


def _llm_supplement_standards(text: str, data: StandardsFillData) -> bool:
    existing = [{"std_no": s.std_no, "name": s.name} for s in data.standards]
    prompt = read_prompt(
        "standards_match_prompt.md",
        TEXT=text[:8000],
        EXISTING_JSON=json.dumps(existing, ensure_ascii=False),
    )
    raw = call_llm(
        prompt,
        purpose="阶段4 · 大模型补充 CH1.11.1 适用标准",
        request_brief="根据产品说明书补充可能遗漏的 GB/YY 标准或 CMDE 指导原则；找不到则返回空数组，禁止编造标准号。",
        prompt_file="prompts/standards_match_prompt.md",
    )
    if not raw:
        return False
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False

    added = False
    for item in payload.get("additional_standards", []) or []:
        std_no = str(item.get("std_no", "")).strip()
        name = str(item.get("name", "")).strip()
        if std_no and name:
            data.standards.append(
                StandardEntry(std_no=std_no, name=name, source="大模型补充", category="补充")
            )
            added = True
    for item in payload.get("additional_guidance", []) or []:
        title = str(item.get("title", "")).strip()
        if title:
            data.guidance.append(
                GuidanceEntry(
                    title=title,
                    source=str(item.get("source", "大模型补充")),
                    note=str(item.get("note", "")),
                )
            )
            added = True
    if added:
        data.standards = _dedupe_standards(data.standards)
        data.match_summary += "（含大模型补充项）"
    return added
