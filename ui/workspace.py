"""Audit workspace — upload, run pipeline, show results."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core.llm_client import llm_available, set_runtime_llm_config, should_use_llm
from core.pipeline import run_pipeline
from core.scanner import build_catalog_dataframe, build_classified_catalog, scan_directory
from core.upload_helper import SUPPORTED_EXTENSIONS, save_uploaded_files, upload_signature
from core.utils import DEFAULT_OUTPUT, PROJECT_ROOT

_CATALOG_HINTS = {
    "核心数据源": "说明书、技术要求、临床/检验资料、法规参考等——提取与核查的实质内容来源",
    "申报原始模版": "用户上传的 CH1 监管信息表格与声明类文件——自动填写的输入底稿",
    "输出文档模版": "流水线填写后生成的申报文件（审核完成后出现在此）",
}


def _render_classified_catalog(catalog: dict[str, pd.DataFrame]) -> None:
    for label, hint in _CATALOG_HINTS.items():
        df = catalog.get(label)
        st.markdown(f"**{label}**")
        st.caption(hint)
        if df is not None and len(df) > 0:
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.caption("（暂无）")
        st.markdown("")


def render_workspace(*, preset_demo: str | None = None) -> bool:
    """Render audit workspace. Returns True if user clicked back to home."""
    st.markdown(
        """
        <div class="workspace-header">
            <div>
                <p class="workspace-breadcrumb">首页 / 审核工作台</p>
                <h2 class="workspace-title">申报资料审核</h2>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    back_col, _ = st.columns([1, 5])
    with back_col:
        if st.button("← 返回首页", use_container_width=True):
            return True

    with st.sidebar:
        st.header("运行配置")

        for key in ("llm_api_key", "llm_base_url", "llm_model"):
            if key not in st.session_state:
                st.session_state[key] = ""

        set_runtime_llm_config(
            api_key=st.session_state.llm_api_key,
            base_url=st.session_state.llm_base_url or None,
            model=st.session_state.llm_model or None,
        )

        with st.expander("大模型设置", expanded=not llm_available()):
            st.caption("API Key 仅保存在当前浏览器会话，不会写入服务器或环境变量。")
            st.text_input(
                "DeepSeek API Key",
                type="password",
                key="llm_api_key",
                placeholder="sk-…",
                help="在 [DeepSeek 开放平台](https://platform.deepseek.com) 获取",
            )
            with st.expander("高级（可选）", expanded=False):
                st.text_input(
                    "API Base URL",
                    key="llm_base_url",
                    placeholder="https://api.deepseek.com",
                )
                st.text_input(
                    "模型",
                    key="llm_model",
                    placeholder="deepseek-chat",
                )
            if st.session_state.llm_api_key:
                if st.button("清除 API Key", use_container_width=True):
                    st.session_state.llm_api_key = ""
                    st.rerun()

        if preset_demo:
            source_mode = "demo"
            demo_preset = preset_demo
            st.info(f"示例模式：**{demo_preset}**")
        else:
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
            "启用 LLM（提取 + 任务4逐份分析 + 任务5 RA 报告）",
            value=llm_available(),
            disabled=not llm_available(),
            help="开启后：任务4逐份分析；任务5由 LLM 将规则结论撰写为四维度 RA 报告",
        )
        if not llm_available():
            st.info("未配置 DeepSeek API Key，请在上方「大模型设置」中填写；未填写时仅使用规则引擎。")
        elif use_llm:
            st.success("大模型：已启用")
        else:
            st.warning("大模型：已关闭")

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
                st.caption("流水线已按规则自动归类（Python 规则引擎，见 config/file_catalog.json）")
                _render_classified_catalog(build_classified_catalog(preview))
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
        if upload_ready:
            st.info(f"使用内置示例：`{upload_dir}`（共 {len(scan_directory(upload_dir))} 个文件）")
        else:
            st.warning(f"示例目录不存在或为空：`{upload_dir}`，请改用自由上传。")

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
            (80, "自动填写 + 结构/一致性/格式核查..." + ("（LLM逐份）" if llm_on else "（规则）")),
            (92, "生成合规风险预警报告..." + ("（RA四维度+LLM）" if llm_on else "（RA模板）")),
        ]:
            progress.progress(pct, text=msg)

        result = run_pipeline(upload_dir, output_dir, use_llm=use_llm, log_source="Streamlit 网页")
        progress.progress(100, text="完成")
        st.session_state["result"] = result
        st.session_state["output_dir"] = output_dir
        st.session_state["use_llm"] = use_llm
        st.session_state["source_mode"] = source_mode

    if "result" in st.session_state:
        _render_results()

    elif source_mode == "upload" and not upload_ready:
        st.info("↑ 请先上传申报资料，系统将自动统计文件数与页数，再点击「开始审核」。")

    return False


def _render_results() -> None:
    result = st.session_state["result"]
    output_dir = st.session_state["output_dir"]

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("扫描文件", len(result.file_list))
    c2.metric("完整性问题", len(result.completeness_issues))
    c3.metric("一致性问题", len(result.consistency_issues))
    c4.metric("章节/必检项", len(result.structure_issues))
    c5.metric("格式问题", len(getattr(result, "format_issues", [])))
    c6.metric("LLM", "已启用" if result.llm_active else "未启用")

    if st.session_state.get("source_mode") == "upload":
        st.caption("本次分析基于您上传的文件；目录汇总与页数为自动统计结果。")
    if result.log_path:
        st.info(f"本次运行日志已写入：`{result.log_path}`（同目录下 `最新运行日志.txt` 可随时查看）")
    if result.extracted and result.extracted.llm_used:
        st.caption("信息提取已调用 DeepSeek；置信度含「规则+LLM」或「LLM」的字段为大模型参与。")

    st.subheader("1. 文件目录汇总 (CH1.2)")
    st.caption("由流水线自动分为：核心数据源 / 申报原始模版 / 输出文档模版")
    if result.catalog_by_category:
        _render_classified_catalog(result.catalog_by_category)
    elif result.catalog_df is not None:
        st.dataframe(result.catalog_df, use_container_width=True)

    st.subheader("2. 完整性核查")
    st.caption(
        "对照 [CMDE 2021年第121号公告](https://www.cmde.org.cn/flfg/fgwj/ggtg/20210930163300622.html) "
        "及附件4《体外诊断试剂注册申报资料要求及说明》"
    )
    if result.completeness_issues:
        comp_df = pd.DataFrame(
            [
                {
                    "严重等级": i.severity,
                    "分类": i.category,
                    "问题": i.message,
                    "法规依据": i.regulation_ref,
                    "通知责任人": i.notify,
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

    st.subheader("4. 结构、一致性与格式核查（任务4）")
    st.caption(
        "对照附件4：① 章节/性能必检项完整性 ② 跨文档字段一致性 ③ 格式规范性。"
        " LLM 启用时逐份分析文档，一致性比对由程序完成。"
    )

    st.markdown("**4.1 跨文档一致性**")
    if result.consistency_issues:
        for issue in result.consistency_issues:
            with st.expander(f"⚠️ {issue.label}", expanded=True):
                for fname, val in issue.values.items():
                    st.write(f"**{fname}**: {val}")
                st.caption(issue.suggestion)
    else:
        st.success("未发现跨文档一致性问题。")

    matrix = getattr(result, "consistency_matrix", None)
    if matrix:
        with st.expander("查看一致性字段矩阵（各文档提取值）", expanded=False):
            st.dataframe(pd.DataFrame(matrix).T, use_container_width=True)

    st.markdown("**4.2 章节与必检项完整性**")
    if result.structure_issues:
        for s in result.structure_issues:
            st.warning(f"{s.doc_name} 缺少: {', '.join(s.missing_sections)}")
    else:
        st.success("各文档必检章节/性能项完整。")

    st.markdown("**4.3 附件4 格式规范性**")
    format_issues = getattr(result, "format_issues", [])
    if format_issues:
        for f in format_issues:
            with st.expander(f"📋 {f.doc_name}", expanded=False):
                for p in f.problems:
                    st.write(f"- {p}")
                if f.suggestion:
                    st.caption(f.suggestion)
                if f.regulation_ref:
                    st.caption(f"依据：{f.regulation_ref}")
    else:
        st.success("各生成文件格式符合附件4规范要求。")

    st.subheader("5. 合规风险预警与处理建议")
    report_path = Path(result.report_path) if result.report_path else None
    if report_path and report_path.exists():
        st.caption("四维度 RA 报告：完整性 → 一致性 → 规范性 → Action Items（完整正文见页面底部）")
    else:
        st.info("报告尚未生成，请重新运行审核。")

    st.subheader("6. 下载输出")
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

    with st.expander("查看完整报告", expanded=True):
        if report_path and report_path.exists():
            st.markdown(report_path.read_text(encoding="utf-8"))
        else:
            st.info("报告尚未生成，请重新运行审核。")
