"""폰 화면 (2026-10-02): 폰으로 접속하면 사이드바 없이 위에서부터 조건 → 생성 → 근무표 순서로 보여 준다.

컴퓨터 화면은 그대로다. 폰 판단은 브라우저가 보내는 User-Agent로 하고, 주소 끝 ?view=pc / ?view=mobile 로
직접 바꿀 수 있다 (화면 맨 아래 전환 버튼).
"""
from __future__ import annotations

import re

import streamlit as st

_PHONE = re.compile(r"Mobi|Android|iPhone|iPod", re.IGNORECASE)

MOBILE_CSS = """<style>
section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
[data-testid="stExpandSidebarButton"] { display: none !important; }
.block-container, [data-testid="stMainBlockContainer"] {
  padding: 3rem .7rem 4rem !important; max-width: 100% !important; }
h1 { font-size: 1.45rem !important; line-height: 1.3 !important; padding: .2rem 0 .4rem !important; }
h2 { font-size: 1.2rem !important; } h3 { font-size: 1.08rem !important; } h4 { font-size: 1rem !important; }
.stButton button, .stDownloadButton button { min-height: 2.9rem; }
[data-testid="stTabs"] button p { font-size: .9rem; }
</style>"""

NIGHT_MOBILE_CSS = """<style>
.block-container, [data-testid="stMainBlockContainer"] {
  padding: .45rem .3rem 1.5rem !important; max-width: 100% !important; }
[data-testid="stHeader"] { display:none !important; }
[data-testid="stVerticalBlock"] { gap:.35rem !important; }
[data-testid="stCaptionContainer"] p { font-size:.72rem !important; }
[data-testid="stTabs"] [data-baseweb="tab-list"] { gap:.5rem; }
[data-testid="stTabs"] [data-baseweb="tab"] { height:2rem; padding:0 .3rem; }
[data-testid="stExpander"] summary { min-height:2rem; padding:.2rem .4rem; }
h1 { font-size: 1.05rem !important; line-height: 1.15 !important; padding: 0 !important; }
[data-testid="stMarkdownContainer"]:has(h1) { margin-bottom:0 !important; }
</style>"""


def phone_agent() -> bool:
    """접속한 브라우저가 폰인지 (User-Agent 기준)."""
    try:
        agent = st.context.headers.get("User-Agent", "") or ""
    except Exception:
        return False
    return bool(_PHONE.search(agent))


def is_mobile() -> bool:
    """폰 화면으로 그릴지. 주소의 ?view= 값이 있으면 그것을 따른다."""
    view = st.query_params.get("view")
    if view in ("pc", "mobile"):
        return view == "mobile"
    return phone_agent()


def apply_style() -> None:
    st.markdown(MOBILE_CSS, unsafe_allow_html=True)


def apply_night_style() -> None:
    st.markdown(NIGHT_MOBILE_CSS, unsafe_allow_html=True)


def controls(expanded: bool):
    """사이드바 대신 본문 맨 위 '근무 조건' 칸."""
    return st.expander("⚙️ 근무 조건 · 생성", expanded=expanded)


def summary_line(items) -> None:
    """컴퓨터 화면의 큰 숫자 5개 대신 한 줄 요약."""
    st.caption(" · ".join(str(item) for item in items if item))


def view_switch() -> None:
    """폰으로 접속했을 때만 화면 맨 아래에 PC 화면 ↔ 폰 화면 전환 버튼."""
    if not phone_agent() and st.query_params.get("view") != "mobile":
        return
    mobile = is_mobile()
    st.divider()
    if st.button("🖥 PC 화면으로 보기" if mobile else "📱 폰 화면으로 보기", key="view_switch", width="stretch"):
        st.query_params["view"] = "pc" if mobile else "mobile"
        st.rerun()


from contextlib import contextmanager


@contextmanager
def action_columns(key, spec=2):
    """Keep confirmation and regeneration adjacent even on narrow phones."""
    st.markdown("<style>@media(max-width:640px){"
                "div[class*='st-key-shift_actionbar_'] [data-testid='stHorizontalBlock']{flex-flow:row nowrap!important;gap:.5rem}"
                "div[class*='st-key-shift_actionbar_'] [data-testid='stColumn']{width:0!important;min-width:0!important;flex:1 1 0!important}"
                "}</style>", unsafe_allow_html=True)
    with st.container(key=f"shift_actionbar_{key}"):
        yield st.columns(spec)
