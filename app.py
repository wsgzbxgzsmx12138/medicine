#!/usr/bin/env python3
"""Streamlit 入口：NMPA 注册文件准备与审核 Agent Demo。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.llm_client import llm_available
from core.pipeline import run_pipeline
from core.utils import DEFAULT_OUTPUT, DEFAULT_UPLOAD, PROJECT_ROOT

st.set_page_config(
    page_title="NMPA 注册文件审核 Agent",
    page_icon="📋",
    layout="wide",
)

st.title("试剂盒 NMPA 注册文件准备与审核 Agent")
st.caption("Demo 轨 · 扫描 → 完整性 → 提取 → 填写 → 一致性 → 预警")

with st.sidebar:
    st.header("运行配置")
    preset = st.radio(
        "数据预设",
        ["normal", "missing", "conflict", "custom"],
        format_func=lambda x: {
            "normal": "正常集 (data/upload/normal)",
            "missing": "缺失集 (缺 CH1.4)",
            "conflict": "冲突集 (产品名称不一致)",
            "custom": "上传文件",
        }[x],
    )
    use_llm = st.checkbox("启用 LLM 润色（需配置 LLM_API_KEY）", value=llm_available())
    if not llm_available():
        st.info("未配置 LLM_API_KEY，将使用规则提取。")

upload_dir: Path
if preset == "custom":
    uploaded = st.file_uploader(
        "上传申报资料 (.docx / .pdf)",
        type=["docx", "pdf", "doc"],
        accept_multiple_files=True,
    )
    if uploaded:
        tmp = Path(tempfile.mkdtemp(prefix="nmpa_upload_"))
        for f in uploaded:
            (tmp / f.name).write_bytes(f.getbuffer())
        upload_dir = tmp
    else:
        upload_dir = DEFAULT_UPLOAD
        st.warning("未上传文件，将使用默认样本目录。")
else:
    upload_dir = PROJECT_ROOT / "data" / "upload" / preset

run = st.button("开始审核", type="primary", use_container_width=True)

if run:
    output_dir = DEFAULT_OUTPUT / preset
    progress = st.progress(0, text="初始化...")
    for pct, msg in [(15, "扫描文件..."), (35, "完整性核查..."), (55, "信息提取..."), (75, "填写与一致性..."), (90, "生成报告...")]:
        progress.progress(pct, text=msg)

    result = run_pipeline(upload_dir, output_dir)
    progress.progress(100, text="完成")
    st.session_state["result"] = result
    st.session_state["output_dir"] = output_dir

if "result" in st.session_state:
    result = st.session_state["result"]
    output_dir = st.session_state["output_dir"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("扫描文件", len(result.file_list))
    c2.metric("完整性问题", len(result.completeness_issues))
    c3.metric("一致性问题", len(result.consistency_issues))
    c4.metric("输出文件", len(result.filled_files) + 1)

    st.subheader("1. 文件目录汇总 (CH1.2)")
    if result.catalog_df is not None:
        st.dataframe(result.catalog_df, use_container_width=True)

    st.subheader("2. 完整性核查")
    if result.completeness_issues:
        comp_df = pd.DataFrame(
            [
                {
                    "严重等级": i.severity,
                    "问题": i.message,
                    "建议": i.suggestion,
                }
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
        rows = [
            {"字段": k, "值": v if not isinstance(v, list) else "、".join(v), "置信度": conf.get(k, "-")}
            for k, v in ext.items()
            if k not in ("targets", "source_file")
        ]
        rows.append({"字段": "source_file", "值": result.extracted.source_file, "置信度": "-"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

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

else:
    st.info('选择数据预设或上传文件，点击「开始审核」运行流水线。')
