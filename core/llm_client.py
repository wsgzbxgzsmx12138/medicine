from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv

from core.utils import PROJECT_ROOT, read_prompt

load_dotenv(PROJECT_ROOT / ".env")

# Streamlit 等 UI 注入的运行时配置（优先于环境变量，不落盘）
_runtime_llm: dict[str, str | None] = {
    "api_key": None,
    "base_url": None,
    "model": None,
}


def set_runtime_llm_config(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> None:
    """由 Streamlit 设置页写入；传 None 表示不修改该项。"""
    if api_key is not None:
        _runtime_llm["api_key"] = api_key.strip() or None
    if base_url is not None:
        _runtime_llm["base_url"] = base_url.strip() or None
    if model is not None:
        _runtime_llm["model"] = model.strip() or None


def get_llm_api_key() -> str:
    runtime = (_runtime_llm.get("api_key") or "").strip()
    if runtime:
        return runtime
    return os.getenv("LLM_API_KEY", "").strip()


def get_llm_base_url() -> str:
    runtime = (_runtime_llm.get("base_url") or "").strip()
    if runtime:
        return runtime
    return os.getenv("LLM_BASE_URL", "https://api.deepseek.com").strip()


def get_llm_model() -> str:
    runtime = (_runtime_llm.get("model") or "").strip()
    if runtime:
        return runtime
    return os.getenv("LLM_MODEL", "deepseek-chat").strip()


def llm_available() -> bool:
    return bool(get_llm_api_key())


def _clip(text: str, limit: int = 150) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _log_llm_round(
    purpose: str,
    *,
    request_brief: str = "",
    prompt_file: str = "",
    success: bool,
    response_brief: str = "",
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


def _log_llm(purpose: str, *, success: bool, detail: str = "") -> None:
    _log_llm_round(
        purpose,
        success=success,
        response_brief=detail,
        fallback="自动退回规则引擎结果，主流程继续。" if not success else "",
    )


def should_use_llm(enabled: bool = True) -> bool:
    """UI/CLI 开关与 API Key 同时满足时才调用大模型。"""
    return enabled and llm_available()


def call_llm(
    prompt: str,
    *,
    purpose: str = "大模型调用",
    request_brief: str = "",
    prompt_file: str = "",
) -> str | None:
    if not llm_available():
        _log_llm_round(
            purpose,
            request_brief=request_brief or "（未配置 API Key，请在侧边栏设置中填写 DeepSeek API Key）",
            prompt_file=prompt_file,
            success=False,
            response_brief="未配置 API Key",
            fallback="跳过本步大模型，使用规则引擎。",
        )
        return None

    api_key = get_llm_api_key()
    base_url = get_llm_base_url()
    model = get_llm_model()

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url.rstrip("/") + "/v1")
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        content = resp.choices[0].message.content
        return content
    except Exception as exc:
        _log_llm_round(
            purpose,
            request_brief=request_brief,
            prompt_file=prompt_file,
            success=False,
            response_brief=str(exc),
            fallback="本步大模型失败，Python 将使用规则结果继续。",
        )
        return None


def extract_with_llm(text: str) -> dict[str, Any]:
    purpose = "阶段3 · 从说明书提取结构化字段"
    request_brief = (
        "阅读说明书全文，提取产品名称、预期用途、包装规格、检测原理、储存条件、"
        "注册人信息、检出限、符合率等字段；找不到必须填「未提及」，禁止编造；输出合法 JSON。"
    )
    prompt = read_prompt("extraction_prompt.md", TEXT=text[:12000])
    raw = call_llm(
        prompt,
        purpose=purpose,
        request_brief=request_brief,
        prompt_file="prompts/extraction_prompt.md",
    )
    if not raw:
        return {}
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        data = json.loads(raw)
        keys = [k for k in data if data.get(k) not in (None, "", "未提及")]
        preview_parts = []
        for k in keys[:6]:
            v = data[k]
            if isinstance(v, list):
                v = "、".join(str(x) for x in v[:3])
            preview_parts.append(f"{k}={_clip(v, 40)}")
        preview = "；".join(preview_parts)
        _log_llm_round(
            purpose,
            request_brief=request_brief,
            prompt_file="prompts/extraction_prompt.md",
            success=True,
            response_brief=f"解析 JSON 成功，{len(keys)} 个有效字段 — {preview}",
        )
        return data
    except json.JSONDecodeError:
        _log_llm_round(
            purpose,
            request_brief=request_brief,
            prompt_file="prompts/extraction_prompt.md",
            success=False,
            response_brief="返回内容不是合法 JSON",
            fallback="沿用阶段3规则正则已提取的字段，不覆盖已有结果。",
        )
        return {}


def generate_risk_report_llm(data: dict[str, Any], *, enabled: bool = True) -> str | None:
    """将四维度结构化 JSON 转为 RA 风格 Markdown 报告正文。"""
    if not should_use_llm(enabled):
        return None
    stats = data.get("summary_stats", {})
    purpose = "阶段5 · 撰写四维度合规风险预警报告"
    request_brief = (
        f"根据规则引擎已确认的 {stats.get('total', 0)} 个问题（严重 {stats.get('critical', 0)} / "
        f"警告 {stats.get('warning', 0)}），按 RA 专员口吻写四维度报告："
        "执行摘要、完整性预警、一致性预警、章节/格式预警、Action Items 待办清单；"
        "不得编造新问题，不得改变严重等级。"
    )
    if stats.get("total", 0) == 0 and not (
        data.get("completeness")
        or data.get("consistency")
        or data.get("normative", {}).get("structure")
        or data.get("normative", {}).get("format")
    ):
        return None

    prompt = read_prompt("risk_report_prompt.md", REPORT_JSON=json.dumps(data, ensure_ascii=False, indent=2))
    text = call_llm(
        prompt,
        purpose=purpose,
        request_brief=request_brief,
        prompt_file="prompts/risk_report_prompt.md",
    )
    if text:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        preview = _clip(text.replace("\n", " "), 200)
        _log_llm_round(
            purpose,
            request_brief=request_brief,
            prompt_file="prompts/risk_report_prompt.md",
            success=True,
            response_brief=f"报告正文约 {len(text)} 字，开头：{preview}",
        )
        return text
    _log_llm_round(
        purpose,
        request_brief=request_brief,
        prompt_file="prompts/risk_report_prompt.md",
        success=False,
        response_brief="未生成报告正文",
        fallback="Python 改用内置 RA 话术模板生成报告（结论与规则引擎一致）。",
    )
    return None


def polish_report(issues: list[dict[str, Any]], *, enabled: bool = True) -> str | None:
    if not issues or not should_use_llm(enabled):
        return None
    prompt = read_prompt("risk_summary_prompt.md", ISSUES_JSON=json.dumps(issues, ensure_ascii=False, indent=2))
    text = call_llm(
        prompt,
        purpose="报告措辞润色（旧版兼容）",
        request_brief="把已确认的问题列表改写成更顺的中文建议段落，不得新增问题。",
        prompt_file="prompts/risk_summary_prompt.md",
    )
    if text:
        _log_llm_round("报告措辞润色", success=True, response_brief=f"约 {len(text)} 字")
    else:
        _log_llm_round("报告措辞润色", success=False, response_brief="跳过")
    return text
