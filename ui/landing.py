"""Landing page — fullscreen hero only."""

from __future__ import annotations

import streamlit as st

from core.llm_client import llm_available


def render_landing() -> str | None:
    """Render homepage. Returns 'start' | 'demo' when user clicks a CTA."""
    llm_ready = llm_available()
    llm_stat = "DeepSeek" if llm_ready else "规则引擎"
    llm_desc = "语义增强已接入" if llm_ready else "工作台内自行配置 API Key"

    st.markdown(
        f"""
        <div class="lp-fullscreen">
            <div class="lp-hero-content">
                <p class="lp-hero-eyebrow">NMPA · 第三类体外诊断试剂 · 注册申报</p>
                <h1>注册申报资料合规审核，<br>决策有据可依</h1>
                <p class="lp-hero-lead">
                    面向注册事务团队的专业审核工作台。自动完成 CH1 目录汇总、
                    资料完整性核查、跨文档一致性校验与风险预警报告输出。
                </p>
                <dl class="lp-hero-meta">
                    <div><dt>5</dt><dd>阶段审核流水线</dd></div>
                    <div><dt>15+</dt><dd>说明书字段提取</dd></div>
                    <div><dt>100%</dt><dd>合规结论规则判定</dd></div>
                    <div><dt>{llm_stat}</dt><dd>{llm_desc}</dd></div>
                </dl>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _, cta1, cta2, _ = st.columns([2, 1.4, 1.2, 2])
    with cta1:
        st.markdown('<div class="lp-btn-primary lp-hero-cta">', unsafe_allow_html=True)
        start = st.button("立即进入审核平台", type="primary", use_container_width=True, key="hero_start")
        st.markdown("</div>", unsafe_allow_html=True)
    with cta2:
        st.markdown('<div class="lp-btn-secondary lp-hero-cta">', unsafe_allow_html=True)
        demo = st.button("查看演示案例", use_container_width=True, key="hero_demo")
        st.markdown("</div>", unsafe_allow_html=True)

    if start:
        return "start"
    if demo:
        return "demo"
    return None
