from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv

from core.utils import PROJECT_ROOT, read_prompt

load_dotenv(PROJECT_ROOT / ".env")


def llm_available() -> bool:
    return bool(os.getenv("LLM_API_KEY"))


def should_use_llm(enabled: bool = True) -> bool:
    """UI/CLI 开关与 API Key 同时满足时才调用大模型。"""
    return enabled and llm_available()


def call_llm(prompt: str) -> str | None:
    if not llm_available():
        return None

    api_key = os.getenv("LLM_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("LLM_MODEL", "deepseek-chat")

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url.rstrip("/") + "/v1")
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        return resp.choices[0].message.content
    except Exception:
        return None


def extract_with_llm(text: str) -> dict[str, Any]:
    prompt = read_prompt("extraction_prompt.md", TEXT=text[:12000])
    raw = call_llm(prompt)
    if not raw:
        return {}
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def polish_report(issues: list[dict[str, Any]], *, enabled: bool = True) -> str | None:
    if not issues or not should_use_llm(enabled):
        return None
    prompt = read_prompt("risk_summary_prompt.md", ISSUES_JSON=json.dumps(issues, ensure_ascii=False, indent=2))
    return call_llm(prompt)
