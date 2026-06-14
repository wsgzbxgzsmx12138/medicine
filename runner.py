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
    args = parser.parse_args()

    if not args.input.exists():
        print(f"输入目录不存在: {args.input}")
        return 1

    print(f"扫描目录: {args.input}")
    result = run_pipeline(args.input, args.output)
    print(json.dumps(result.summary(), ensure_ascii=False, indent=2))
    print(f"\n报告: {result.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
