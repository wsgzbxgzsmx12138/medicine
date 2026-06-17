#!/usr/bin/env python3
"""Streamlit 入口：NMPA 注册文件准备与审核 Agent。"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ui.landing import render_landing
from ui.styles import inject_global_css
from ui.workspace import render_workspace

st.set_page_config(
    page_title="NMPA 注册文件审核 Agent",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "view" not in st.session_state:
    st.session_state.view = "home"
if "preset_demo" not in st.session_state:
    st.session_state.preset_demo = None

is_home = st.session_state.view == "home"
inject_global_css(hide_sidebar=is_home, landing=is_home)

if is_home:
    action = render_landing()
    if action == "start":
        st.session_state.view = "workspace"
        st.session_state.preset_demo = None
        st.rerun()
    elif action == "demo":
        st.session_state.view = "workspace"
        st.session_state.preset_demo = "normal"
        st.rerun()
else:
    if render_workspace(preset_demo=st.session_state.preset_demo):
        st.session_state.view = "home"
        st.session_state.preset_demo = None
        st.rerun()
