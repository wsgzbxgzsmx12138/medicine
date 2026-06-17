#!/usr/bin/env python3
"""CLI 入口：一键运行 NMPA 注册文件审核流水线。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.pipeline import run_pipeline
from core.utils import DEFAULT_OUTPUT, DEFAULT_UPLOAD


def main() -> int:
    parser = argparse.ArgumentParser(description="NMPA 注册文件准备与审核 Agent")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_UPLOAD,
        help="上传资料目录",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="输出目录",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="禁用大模型（仅规则引擎）",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="显式启用大模型（默认：已配置 API Key 时启用）",
    )
    args = parser.parse_args()

    from core.llm_client import llm_available, should_use_llm

    if args.no_llm:
        use_llm = False
    elif args.llm:
        use_llm = True
    else:
        use_llm = llm_available()

    if not args.input.exists():
        print(f"输入目录不存在: {args.input}")
        return 1

    print(f"扫描目录: {args.input}")
    print(f"LLM: {'启用' if should_use_llm(use_llm) else '禁用'}")
    result = run_pipeline(args.input, args.output, use_llm=use_llm, log_source="CLI 命令行")
    print(json.dumps(result.summary(), ensure_ascii=False, indent=2))
    print(f"\n报告: {result.report_path}")
    if result.log_path:
        print(f"运行日志: {result.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
