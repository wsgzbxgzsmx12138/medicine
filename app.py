#!/usr/bin/env python3
"""Streamlit 入口：NMPA 注册文件准备与审核 Agent Demo。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.llm_client import llm_available, should_use_llm
from core.pipeline import run_pipeline
from core.scanner import build_catalog_dataframe, scan_directory
from core.upload_helper import SUPPORTED_EXTENSIONS, save_uploaded_files, upload_signature
from core.utils import DEFAULT_OUTPUT, PROJECT_ROOT

st.set_page_config(
    page_title="NMPA 注册文件审核 Agent",
    page_icon="📋",
    layout="wide",
)

st.title("试剂盒 NMPA 注册文件准备与审核 Agent")
st.caption("自动扫描文件夹 → 统计目录与页数 → 完整性/一致性核查 → 信息提取 → 合规预警")

# ── 侧边栏 ──
with st.sidebar:
    st.header("运行配置")
    source_mode = st.radio(
        "数据来源",
        ["upload", "demo"],
        format_func=lambda x: "自由上传文件夹" if x == "upload" else "内置示例数据",
        index=0,
    )
    demo_preset = None
    if source_mode == "demo":
        demo_preset = st.selectbox(
            "示例集",
            ["normal", "missing", "conflict"],
            format_func=lambda x: {
                "normal": "正常集（10 份样本）",
                "missing": "缺失集（缺 CH1.4）",
                "conflict": "冲突集（名称不一致）",
            }[x],
        )

    use_llm = st.checkbox(
        "启用 LLM（提取增强 + 报告润色）",
        value=llm_available(),
        disabled=not llm_available(),
        help="开启后调用 DeepSeek 精炼说明书字段并润色报告；完整性/一致性仍由规则判定",
    )
    if not llm_available():
        st.info("未配置 LLM_API_KEY，仅使用规则引擎。")
    elif use_llm:
        st.success("大模型：已启用")
    else:
        st.warning("大模型：已关闭")

# ── 主区：上传或示例说明 ──
upload_dir: Path | None = None
upload_ready = False

if source_mode == "upload":
    st.subheader("上传申报资料")
    st.markdown(
        "请上传您的注册申报文件夹内容。支持 **多选文件** 或 **整包 .zip 压缩包**（可保留子目录）。"
        f" 支持格式：`{', '.join(sorted(SUPPORTED_EXTENSIONS))}`"
    )

    col_a, col_b = st.columns(2)
    with col_a:
        uploaded_files = st.file_uploader(
            "方式一：选择多个文件",
            type=["docx", "pdf", "doc"],
            accept_multiple_files=True,
            key="multi_files",
        )
    with col_b:
        zip_upload = st.file_uploader(
            "方式二：上传文件夹压缩包 (.zip)",
            type=["zip"],
            key="zip_folder",
        )

    sig = upload_signature(uploaded_files, zip_upload)

    if sig:
        if st.session_state.get("upload_sig") != sig:
            upload_dir = save_uploaded_files(uploaded_files or [], zip_file=zip_upload)
            st.session_state["upload_sig"] = sig
            st.session_state["upload_dir"] = str(upload_dir)
            st.session_state.pop("result", None)
        else:
            upload_dir = Path(st.session_state["upload_dir"])

        preview = scan_directory(upload_dir)
        upload_ready = len(preview) > 0

        st.success(f"已载入 **{len(preview)}** 个文件，目录：`{upload_dir}`")
        if preview:
            st.dataframe(build_catalog_dataframe(preview), use_container_width=True, height=min(400, 35 * len(preview) + 38))
        else:
            st.warning("压缩包/文件列表中未识别到支持的文档格式，请检查内容。")

        if st.button("清除上传并重新选择"):
            for key in ("upload_sig", "upload_dir", "result", "output_dir", "use_llm"):
                st.session_state.pop(key, None)
            st.rerun()
    else:
        st.info("上传文件或 zip 后，系统将自动统计文件数量与页数，再点击「开始审核」。")
        if "upload_dir" in st.session_state:
            del st.session_state["upload_dir"]

else:
    upload_dir = PROJECT_ROOT / "data" / "upload" / demo_preset
    upload_ready = upload_dir.exists() and len(scan_directory(upload_dir)) > 0
    st.info(f"使用内置示例：`{upload_dir}`（共 {len(scan_directory(upload_dir))} 个文件）")

run = st.button(
    "开始审核",
    type="primary",
    use_container_width=True,
    disabled=(source_mode == "upload" and not upload_ready),
)

if run:
    if source_mode == "upload" and not upload_ready:
        st.error("请先上传至少一个支持的申报文件。")
        st.stop()

    assert upload_dir is not None
    if source_mode == "upload":
        output_dir = DEFAULT_OUTPUT / "custom" / datetime.now().strftime("%Y%m%d_%H%M%S")
    else:
        output_dir = DEFAULT_OUTPUT / demo_preset

    progress = st.progress(0, text="初始化...")
    llm_on = should_use_llm(use_llm)
    for pct, msg in [
        (10, f"扫描 {upload_dir.name} 内文件..."),
        (30, "统计页数并生成 CH1.2 目录表..."),
        (45, "完整性核查（规则）..."),
        (60, "信息提取..." + (" + DeepSeek" if llm_on else "（仅规则）")),
        (80, "自动填写与一致性核查..."),
        (92, "生成风险预警报告..." + (" + LLM润色" if llm_on else "")),
    ]:
        progress.progress(pct, text=msg)

    result = run_pipeline(upload_dir, output_dir, use_llm=use_llm)
    progress.progress(100, text="完成")
    st.session_state["result"] = result
    st.session_state["output_dir"] = output_dir
    st.session_state["use_llm"] = use_llm
    st.session_state["source_mode"] = source_mode

if "result" in st.session_state:
    result = st.session_state["result"]
    output_dir = st.session_state["output_dir"]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("扫描文件", len(result.file_list))
    c2.metric("完整性问题", len(result.completeness_issues))
    c3.metric("一致性问题", len(result.consistency_issues))
    c4.metric("输出文件", len(result.filled_files) + 1)
    c5.metric("LLM", "已启用" if result.llm_active else "未启用")

    if st.session_state.get("source_mode") == "upload":
        st.caption("本次分析基于您上传的文件；目录汇总与页数为自动统计结果。")
    if result.extracted and result.extracted.llm_used:
        st.caption("信息提取已调用 DeepSeek；置信度含「规则+LLM」或「LLM」的字段为大模型参与。")

    st.subheader("1. 文件目录汇总 (CH1.2)")
    if result.catalog_df is not None:
        st.dataframe(result.catalog_df, use_container_width=True)

    st.subheader("2. 完整性核查")
    if result.completeness_issues:
        comp_df = pd.DataFrame(
            [
                {"严重等级": i.severity, "问题": i.message, "建议": i.suggestion}
                for i in result.completeness_issues
            ]
        )

        def _highlight(row):
            color = "#ffcccc" if row["严重等级"] == "critical" else "#fff3cd"
            return [f"background-color: {color}"] * len(row)

        st.dataframe(comp_df.style.apply(_highlight, axis=1), use_container_width=True)
    else:
        st.success("未发现完整性缺失。")

    st.subheader("3. 信息提取结果")
    if result.extracted:
        ext = result.extracted.to_dict()
        conf = ext.pop("confidence", {})
        ext.pop("llm_used", None)
        rows = [
            {"字段": k, "值": v if not isinstance(v, list) else "、".join(v), "置信度": conf.get(k, "-")}
            for k, v in ext.items()
            if k not in ("targets", "source_file")
        ]
        rows.append({"字段": "source_file", "值": result.extracted.source_file, "置信度": "-"})
        if result.extracted.llm_used:
            rows.append({"字段": "_llm_status", "值": "DeepSeek 已参与提取", "置信度": conf.get("_llm", "ok")})
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
    elif result.extracted and result.extracted.confidence.get("_error"):
        st.error(result.extracted.confidence["_error"])

    st.subheader("4. 一致性问题")
    if result.consistency_issues:
        for issue in result.consistency_issues:
            with st.expander(f"⚠️ {issue.label}", expanded=True):
                for fname, val in issue.values.items():
                    st.write(f"**{fname}**: {val}")
                st.caption(issue.suggestion)
    else:
        st.success("未发现跨文档一致性问题。")

    st.subheader("5. 说明书章节检查")
    if result.structure_issues:
        for s in result.structure_issues:
            st.warning(f"{s.doc_name} 缺少: {', '.join(s.missing_sections)}")
    else:
        st.success("说明书必检章节完整。")

    st.subheader("6. 下载输出")
    report_path = Path(result.report_path) if result.report_path else None
    if report_path and report_path.exists():
        st.download_button(
            "下载风险预警报告 (.md)",
            data=report_path.read_text(encoding="utf-8"),
            file_name="风险预警报告.md",
            mime="text/markdown",
        )
    excel = output_dir / "CH1.2_文件目录汇总.xlsx"
    if excel.exists():
        st.download_button(
            "下载 CH1.2 目录汇总 (.xlsx)",
            data=excel.read_bytes(),
            file_name="CH1.2_文件目录汇总.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    for fp in result.filled_files:
        p = Path(fp)
        if p.exists():
            st.download_button(
                f"下载 {p.name}",
                data=p.read_bytes(),
                file_name=p.name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=p.name,
            )

    with st.expander("查看完整报告"):
        if report_path and report_path.exists():
            st.markdown(report_path.read_text(encoding="utf-8"))

elif source_mode == "upload" and not upload_ready:
    st.info("↑ 请先上传申报资料，系统将自动统计文件数与页数，再点击「开始审核」。")
