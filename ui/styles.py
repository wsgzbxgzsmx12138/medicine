"""Shared Streamlit CSS for landing and workspace."""

from __future__ import annotations

import streamlit as st


def inject_global_css(*, hide_sidebar: bool = False, landing: bool = False) -> None:
    sidebar_rule = """
    [data-testid="stSidebar"] { display: none; }
    [data-testid="stSidebarCollapsedControl"] { display: none; }
    """ if hide_sidebar else ""

    landing_container = """
    .main .block-container {
        padding: 0 48px !important;
        max-width: 100% !important;
        min-height: 100vh;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    header[data-testid="stHeader"] {
        background: transparent;
    }
    footer { visibility: hidden; height: 0; }
    [data-testid="stToolbar"] { display: none; }
    [data-testid="stDecoration"] { display: none; }
    """ if landing else """
    .main .block-container {
        padding-top: 2.75rem !important;
        max-width: 1200px;
    }

    [data-testid="stMarkdown"],
    [data-testid="stMarkdownContainer"],
    [data-testid="element-container"] {
        overflow: visible !important;
    }
    """

    landing_styles = """
        [data-testid="stAppViewContainer"] {
            background: linear-gradient(180deg, #eff6ff 0%, #ffffff 55%);
        }

        .lp-fullscreen {
            width: 100%;
            text-align: center;
        }

        .lp-hero-content {
            max-width: 820px;
            margin: 0 auto;
            padding: 0 24px;
        }

        .lp-hero-eyebrow {
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            color: #2563eb;
            margin-bottom: 28px;
        }

        .lp-fullscreen h1 {
            font-family: 'Noto Serif SC', serif;
            font-size: clamp(2rem, 5vw, 3rem);
            font-weight: 600;
            line-height: 1.35;
            color: #0f172a;
            margin: 0 auto 24px;
            letter-spacing: 0.02em;
        }

        .lp-hero-lead {
            font-size: 16px;
            line-height: 1.85;
            color: #64748b;
            max-width: 560px;
            margin: 0 auto 48px;
        }

        .lp-hero-meta {
            display: flex;
            justify-content: center;
            flex-wrap: wrap;
            gap: 40px 56px;
            margin: 0 auto 56px;
            padding-top: 48px;
            border-top: 1px solid #dbeafe;
            max-width: 720px;
        }

        .lp-hero-meta dt {
            font-family: 'Noto Serif SC', serif;
            font-size: clamp(1.5rem, 3vw, 2rem);
            font-weight: 600;
            color: #1d4ed8;
            margin: 0 0 6px;
        }

        .lp-hero-meta dd {
            font-size: 12px;
            color: #64748b;
            margin: 0;
            letter-spacing: 0.04em;
        }

        .lp-hero-cta {
            margin-top: 0 !important;
        }

        div[data-testid="column"]:has(.lp-btn-primary) div[data-testid="stButton"] > button[kind="primary"] {
            background: #2563eb !important;
            color: #ffffff !important;
            border: 1px solid #2563eb !important;
            border-radius: 2px !important;
            font-weight: 600 !important;
            font-size: 14px !important;
            letter-spacing: 0.06em !important;
            padding: 0.65rem 2rem !important;
            min-height: 48px !important;
            transition: background 0.25s ease, box-shadow 0.25s ease !important;
            box-shadow: none !important;
        }

        div[data-testid="column"]:has(.lp-btn-primary) div[data-testid="stButton"] > button[kind="primary"]:hover {
            background: #1d4ed8 !important;
            box-shadow: 0 4px 16px rgba(37, 99, 235, 0.25) !important;
        }

        div[data-testid="column"]:has(.lp-btn-secondary) div[data-testid="stButton"] > button {
            background: #ffffff !important;
            color: #2563eb !important;
            border: 1px solid #2563eb !important;
            border-radius: 2px !important;
            font-weight: 500 !important;
            font-size: 13px !important;
            min-height: 48px !important;
            transition: background 0.25s ease !important;
        }

        div[data-testid="column"]:has(.lp-btn-secondary) div[data-testid="stButton"] > button:hover {
            background: #eff6ff !important;
        }
    """ if landing else ""

    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;600&family=Noto+Serif+SC:wght@500;600;700&display=swap');

        html, body, [class*="css"] {{
            font-family: 'Noto Sans SC', -apple-system, BlinkMacSystemFont, sans-serif;
            -webkit-font-smoothing: antialiased;
        }}

        {sidebar_rule}
        {landing_container}
        {landing_styles}

        /* Workspace */
        .main [data-testid="stCaptionContainer"] p {{
            font-size: 0.85rem;
            color: #64748b;
            line-height: 1.5;
            margin: 0;
            padding-top: 2px;
        }}

        .workspace-header-divider {{
            border-bottom: 1px solid #e2e8f0;
            margin: 0.25rem 0 1.5rem;
        }}

        div[data-testid="stButton"] > button[kind="primary"] {{
            background: #2563eb;
            border-radius: 2px;
            transition: background 0.25s ease;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
