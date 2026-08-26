"""리콜체크 Streamlit 조회 화면.

실행 방법(프로젝트 루트에서):
    streamlit run app/streamlit_app.py

화면은 SQLite를 읽기만 하며, 원본 CSV나 DB를 수정하지 않는다.
차량 사진은 나중에 ``assets/vehicles`` 폴더에
``제조사_차종.jpg`` 또는 ``제조사_차종.webp`` 형태로 넣으면 자동으로 찾는다.
"""

from __future__ import annotations

import base64
import html
import re
import sqlite3
import unicodedata
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


# ---------------------------------------------------------------------------
# 프로젝트 경로와 기본 화면 설정
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "processed" / "database" / "recall_checker.sqlite3"
IMAGE_DIR = PROJECT_ROOT / "assets" / "vehicles"
ICON_DIR = PROJECT_ROOT / "assets" / "icons"
IMAGE_ALIAS_PATH = PROJECT_ROOT / "data" / "mappings" / "vehicle_image_aliases.csv"
AD_IMAGE_PATH = PROJECT_ROOT / "assets" / "recall_public_service_ad.png"
HERO_IMAGE_PATH = PROJECT_ROOT / "assets" / "hero" / "korean-family-suv-sunrise-v2.png"
SERVICE_LOGO_PATH = PROJECT_ROOT / "assets" / "brand" / "recall-check-logo-v1.png"
PUBLIC_AD_HIDE_COOKIE = "recall_ad_hide_date"

# 공식 확인 링크
# 정부 자동차리콜센터는 모든 조회 결과에서 공통으로 안내하고,
# 선택한 제조사는 공식 홈페이지의 고객지원 메뉴로 이동할 수 있게 한다.
GOVERNMENT_RECALL_URL = "https://car.go.kr/ri/stat/list.do?menuId=0203010000"
MANUFACTURER_OFFICIAL_URLS = {
    "KG 모빌리티": "https://www.kg-mobility.com/",
    "BMW": "https://www.bmw.co.kr/",
    "기아": "https://www.kia.com/kr/",
    "르노코리아": "https://www.renault.co.kr/",
    "메르세데스 벤츠": "https://www.mercedes-benz.co.kr/",
    "볼보": "https://www.volvocars.com/kr/",
    "토요타": "https://www.toyota.co.kr/",
    "재규어랜드로버": "https://www.jaguarkorea.co.kr/",
    "포드": "https://www.ford.co.kr/",
    "현대자동차": "https://www.hyundai.com/kr/ko",
    "혼다코리아": "https://www.hondakorea.co.kr/",
}
MANUFACTURER_SHORT_NAMES = {
    "현대자동차": "현대",
    "혼다코리아": "혼다",
    "르노코리아": "르노",
    "메르세데스 벤츠": "벤츠",
    "KG 모빌리티": "KGM",
}
MANUFACTURER_ICON_FILES = {
    "KG 모빌리티": "manufacturers/kgm",
    "BMW": "manufacturers/bmw",
    "기아": "manufacturers/kia",
    "르노코리아": "manufacturers/renault",
    "메르세데스 벤츠": "manufacturers/mercedes",
    "볼보": "manufacturers/volvo",
    "토요타": "manufacturers/toyota",
    "재규어랜드로버": "manufacturers/jaguarlandrover",
    "포드": "manufacturers/ford",
    "현대자동차": "manufacturers/hyundai",
    "혼다코리아": "manufacturers/honda",
}

# 조회한 차량을 실제 매물 사이트에서 다시 찾아볼 수 있는 외부 링크
USED_CAR_MARKET_LINKS = [
    ("markets/heydealer", "헤이딜러", "내 차 시세·중고차", "https://www.heydealer.com/"),
    ("markets/danawa", "다나와 자동차", "중고차 매물 검색", "https://auto.danawa.com/usedcar/"),
    ("markets/encar", "엔카", "국내 중고차 매물", "https://www.encar.com/"),
    ("markets/kbchachacha", "KB차차차", "중고차 검색·시세", "https://www.kbchachacha.com/public/search/main.kbc"),
    ("markets/kcar", "K Car", "직영 중고차", "https://www.kcar.com/"),
]
ICON_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}

st.set_page_config(
    page_title="리콜체크 | 중고차 결함·리콜 조회",
    page_icon=str(SERVICE_LOGO_PATH),
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# 화면 스타일
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    :root {
        --navy: #10213d;
        --blue: #245ccb;
        --sky: #fff5ed;
        --line: #ecd9c9;
        --muted: #707486;
        --green: #2b7d67;
        --orange: #e98666;
        --cream: #fffaf5;
        --coral: #f0a06e;
    }
    .stApp { background: var(--cream); }
    /* 탭마다 세로 스크롤이 생겼다 사라지며 본문 가로가 달라지지 않게 한다. */
    html {
        scrollbar-gutter: stable;
    }
    /* Streamlit 상단 Deploy 바와 겹치지 않도록 본문 위쪽 여백을 확보한다. */
    header[data-testid="stHeader"] {
        background: transparent;
    }
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"] {
        width: 100%;
        max-width: 100%;
    }
    .block-container {
        padding-top: 4.25rem !important;
        padding-bottom: 1.6rem !important;
        width: 100% !important;
        max-width: 100% !important;
        box-sizing: border-box;
    }
    /* 탭 버튼은 내용 너비로 두고, 탭 안의 배너·검색칸은 본문 전체 너비를 쓴다. */
    [data-testid="stTabs"] {
        width: 100% !important;
        max-width: 100% !important;
        margin-top: -3.35rem !important;
    }
    [data-testid="stTabs"] [role="tabpanel"],
    [data-testid="stTabs"] [data-testid="stTabPanel"] {
        width: 100% !important;
        max-width: 100% !important;
        min-width: 0 !important;
    }
    /* 검색 조건은 리콜 조회 본문에 있으므로 사이드바는 공통 메뉴로 사용하지 않는다. */
    section[data-testid="stSidebar"] {
        background: #ffffff;
        border-right: 1px solid var(--line);
    }
    div[role="listbox"] * { font-size: 1rem !important; }
    /* 본문 비교 화면의 제조사·차종·연식 선택 상자도 같은 크기로 맞춘다. */
    [data-testid="stWidgetLabel"] p {
        font-size: 0.9rem !important;
        font-weight: 700 !important;
    }
    [data-testid="stSelectbox"] [data-baseweb="select"] > div {
        min-height: 42px;
        font-size: 0.92rem;
    }
    [data-testid="stSelectbox"] [data-baseweb="select"] * {
        font-size: 0.92rem !important;
    }
    div[data-testid="stButton"] > button {
        min-height: 42px;
        padding: 0.35rem 0.85rem;
        font-size: 0.92rem;
    }
    /* FAQ와 리콜 사유는 긴 문장을 읽는 영역이므로 일반 본문보다 크게 표시한다. */
    [data-testid="stExpander"] summary p {
        font-size: 1.08rem !important;
        font-weight: 700 !important;
    }
    [data-testid="stExpander"] [data-testid="stMarkdownContainer"] p {
        font-size: 1rem !important;
        line-height: 1.75 !important;
    }
    .link-note {
        color: var(--muted); font-size: .86rem; line-height: 1.6;
        margin: .35rem 0 .65rem;
    }
    .brand { display:flex; align-items:center; gap:.65rem; margin-bottom:.2rem; }
    .brand-mark {
        width: 38px; height: 38px; border-radius: 12px;
        display:flex; align-items:center; justify-content:center;
        background: linear-gradient(135deg, var(--navy), #31517b);
        color:white; font-size: 1.25rem;
        box-shadow: 0 8px 20px rgba(47,111,206,.25);
    }
    .brand-title { font-size: 1.35rem; font-weight: 800; color: var(--navy); }
    .brand-subtitle { color: var(--muted); font-size: .78rem; margin: .1rem 0 1.2rem 3.05rem; }
    .top-brand {
        display:flex; align-items:center; gap:.78rem; padding:.2rem 0 .5rem;
        border-bottom: none; margin-bottom: 0;
    }
    .top-brand-mark {
        width: 44px; height: 44px;
        display:flex; align-items:center; justify-content:center;
        flex-shrink: 0;
    }
    .shield-car-icon { display:block; width:42px; height:46px; }
    .service-logo-icon { display:block; width:44px; height:44px; object-fit:contain; }
    .top-brand-title { font-size: 1.18rem; font-weight: 800; letter-spacing: -.025em; color: var(--navy); }
    .top-brand-subtitle { color: var(--muted); font-size: .82rem; margin-top: .08rem; }
    .search-panel-title { color: var(--navy); font-size: 1.08rem; font-weight: 800; margin-bottom: .45rem; }
    .hero {
        position: relative; overflow: hidden; min-height: 220px;
        padding: 1.35rem 1.5rem; border-radius: 18px;
        color: white; margin: .25rem 0 .7rem;
        box-shadow: 0 14px 30px rgba(61, 45, 49, .18);
        border: 1px solid rgba(255, 214, 185, .3);
        background-color: #0a1b34;
        background-repeat: no-repeat;
        background-position: center, center 75%;
        background-size: 100% 100%, cover;
        width: 100%; box-sizing: border-box;
    }
    .hero-inner { position: relative; z-index: 1; max-width: 56%; }
    .hero h1 { font-size: clamp(1.55rem, 2.25vw, 2.25rem); line-height: 1.2; letter-spacing: -.045em; margin: 0 0 .5rem; }
    .hero p { color: #fff3e9; margin: 0; font-size: .98rem; line-height: 1.6; }
    .eyebrow { font-size: .7rem; letter-spacing: .13em; color: #ffd19f; font-weight: 800; margin-bottom: .45rem; }
    /* 상단 메뉴를 묶인 버튼형 탭으로 보이게 한다. Streamlit 1.61은 data-selected를 쓴다. */
    [data-testid="stTabs"] [role="tablist"] {
        gap: 4px !important;
        background: #fff3e7 !important;
        border: 1px solid var(--line) !important;
        border-radius: 15px !important;
        padding: 4px !important;
        width: fit-content !important;
        margin-bottom: .15rem;
        margin-right: 11rem;
        position: relative;
        z-index: 9;
        pointer-events: auto;
    }
    [data-testid="stTabs"] [role="tablist"]::after {
        display: none !important;
    }
    [data-testid="stTabs"] [data-testid="stTab"],
    [data-testid="stTabs"] [role="tab"] {
        background: transparent !important;
        color: var(--navy) !important;
        border: none !important;
        border-radius: 10px !important;
        height: auto !important;
        padding: .45rem .95rem !important;
        font-weight: 700 !important;
        font-size: .92rem !important;
    }
    [data-testid="stTabs"] [data-testid="stTab"] p,
    [data-testid="stTabs"] [data-testid="stTab"] span,
    [data-testid="stTabs"] [role="tab"] p,
    [data-testid="stTabs"] [role="tab"] span {
        color: inherit !important;
        font-weight: 700 !important;
        font-size: .92rem !important;
    }
    [data-testid="stTabs"] [data-testid="stTab"]:hover,
    [data-testid="stTabs"] [role="tab"]:hover {
        background: #ffe3cf !important;
    }
    [data-testid="stTabs"] [data-testid="stTab"][data-selected],
    [data-testid="stTabs"] [role="tab"][data-selected],
    [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
        background: var(--navy) !important;
        color: #fff !important;
        box-shadow: 0 4px 12px rgba(20, 33, 61, .18);
    }
    [data-testid="stTabs"] [data-testid="stTab"][data-selected] p,
    [data-testid="stTabs"] [data-testid="stTab"][data-selected] span,
    [data-testid="stTabs"] [data-testid="stTab"][data-selected] *,
    [data-testid="stTabs"] [role="tab"][data-selected] p,
    [data-testid="stTabs"] [role="tab"][data-selected] span,
    [data-testid="stTabs"] [role="tab"][data-selected] *,
    [data-testid="stTabs"] [role="tab"][aria-selected="true"] p,
    [data-testid="stTabs"] [role="tab"][aria-selected="true"] span,
    [data-testid="stTabs"] [role="tab"][aria-selected="true"] * {
        color: #fff !important;
    }
    [data-testid="stTabs"] .react-aria-SelectionIndicator {
        display: none !important;
        background: transparent !important;
    }
    .section-title { color: var(--navy); font-size: 1.35rem; font-weight: 800; margin: .2rem 0 .2rem; }
    .section-caption { color: var(--muted); font-size: .9rem; margin: 0 0 .8rem; }
    .card {
        background: #fff; border: 1px solid var(--line); border-radius: 18px;
        padding: 1.25rem 1.35rem; box-shadow: 0 8px 26px rgba(87, 55, 39, .06);
    }
    .car-card {
        min-height: 180px; border-radius: 18px; overflow: hidden;
        background: linear-gradient(145deg, #fff7ee, #ffe6d1);
        display:flex; align-items:center; justify-content:center;
        border: 1px solid var(--line);
    }
    .car-placeholder { text-align:center; color:#566987; }
    .car-placeholder .emoji { font-size: 4.1rem; display:block; margin-bottom:.3rem; }
    .metric-label { color: var(--muted); font-size: .82rem; margin-bottom: .25rem; }
    .metric-value { color: var(--navy); font-size: 1.65rem; font-weight: 800; }
    .metric-note { color: var(--muted); font-size: .73rem; margin-top:.25rem; }
    .notice {
        border-left: 4px solid var(--orange); background: #fff3e9;
        color: #75452e; padding: .6rem .8rem; border-radius: 12px;
        font-size: .8rem; line-height: 1.5; margin: .45rem 0 .55rem;
        word-break: keep-all; overflow-wrap: break-word;
    }
    .source-note { color: var(--muted); font-size: .76rem; margin-top: .45rem; }
    .empty-state { text-align:center; padding: 4rem 1rem; color:var(--muted); }
    .empty-state .emoji { font-size: 3rem; display:block; margin-bottom:.6rem; }
    .market-title { color: var(--navy); font-size: 1.02rem; font-weight: 800; margin: .45rem 0 .4rem; }
    .official-grid { display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap:.5rem; }
    .market-grid { display:grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap:.5rem; }
    .market-card {
        display:flex; flex-direction:column; align-items:center; justify-content:center;
        min-height:86px; padding:.55rem .4rem; border:1px solid var(--line);
        border-radius:13px; background:#fff; color:var(--navy); text-decoration:none !important;
        transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
    }
    .market-card-copy { display:flex; flex-direction:column; align-items:center; min-width:0; }
    .official-grid .market-card {
        flex-direction:row; align-items:center; justify-content:center; gap:.68rem;
        min-height:78px; padding:.62rem .72rem;
    }
    .market-card:hover { transform:translateY(-2px); border-color:#efb18a; box-shadow:0 7px 18px rgba(112,65,35,.12); }
    .market-card-disabled { opacity:.55; pointer-events:none; }
    .market-icon {
        width:34px; height:34px; display:flex; align-items:center; justify-content:center;
        margin-bottom:.3rem; border-radius:9px; background:#fff0e4; color:#bd6545;
        font-size:.82rem; font-weight:800; overflow:hidden;
    }
    .market-icon-image { background:#fff; border:1px solid var(--line); }
    .market-icon-image img {
        width:100%; height:100%; object-fit:contain; display:block;
    }
    .official-grid .market-icon { flex:0 0 auto; width:40px; height:40px; margin:0; }
    .market-card strong { font-size:.78rem; white-space:nowrap; }
    .official-grid .market-card strong {
        white-space:normal; word-break:keep-all; text-align:left; line-height:1.25;
    }
    .market-card small { color:var(--muted); font-size:.64rem; margin-top:.12rem; white-space:nowrap; }
    .official-grid .market-card-copy { align-items:flex-start; }
    .official-grid .market-card small { white-space:normal; word-break:keep-all; }
    .interest-help { color:var(--muted); font-size:.78rem; margin-top:.15rem; }
    .st-key-interest-register-button button,
    .st-key-interest-register-button-added button {
        min-width: 0 !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    .st-key-interest-register-button-added button {
        background: #f5c542 !important; border-color: #dca900 !important; color: #4a3500 !important;
        font-weight: 800 !important;
    }
    .st-key-interest-register-button-added button:hover {
        background: #e9b62d !important; border-color: #c89400 !important;
    }
    div[data-testid="stMetric"] {
        background: #fffdfb; border: 1px solid var(--line); border-radius: 15px;
        padding: .8rem 1rem;
    }
    div[data-testid="stButton"] > button[kind="primary"] {
        background: var(--blue); border-color: var(--blue); border-radius: 10px;
        font-weight: 700;
    }
    .small-pill {
        display:inline-block; background:#fff0e4; color:#bd6545; border-radius:999px;
        padding:.25rem .65rem; font-size:.75rem; font-weight:700; margin-right:.25rem;
    }
    .result-header { margin: .15rem 0 .7rem; }
    .result-title {
        display:flex; align-items:center; gap:.5rem; color: var(--navy); font-size: 1.38rem;
        font-weight: 800; margin: 0 0 .48rem; line-height: 1.3; letter-spacing:-.035em;
    }
    .result-title-icon {
        display:flex; align-items:center; justify-content:center; width:1.62rem; height:1.62rem;
        flex:0 0 auto; line-height:0;
    }
    .result-title-icon svg {
        display:block; width:100%; height:100%; overflow:visible;
        stroke:var(--navy); fill:#fffaf5; stroke-width:1.8;
    }
    .result-emphasis {
        color: #1f3a68; font-size: .88rem; font-weight: 700; line-height: 1.5;
        background: #fff2e7; border-left: 4px solid var(--orange);
        padding: .5rem .7rem; border-radius: 8px; margin: 0;
        word-break: keep-all; overflow-wrap: break-word;
    }
    .result-safety-heading {
        display:flex; align-items:center; min-height:1.62rem; gap:.45rem; color:var(--navy);
        font-size:1.14rem; font-weight:800; line-height:1.3; margin:.05rem 0 .48rem;
    }
    .result-safety-heading svg {
        display:block; flex:0 0 auto; width:1.5rem; height:1.5rem; overflow:visible;
        stroke:var(--blue); fill:#eef4ff; stroke-width:1.8;
    }
    .result-metrics { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:.6rem; margin:0 0 .62rem; }
    .result-metric {
        display:grid; grid-template-columns:2.48rem minmax(0, 1fr); grid-template-rows:auto 1fr;
        column-gap:.54rem; row-gap:.28rem; min-width:0; min-height:8.25rem;
        background:linear-gradient(145deg, #fffefd 0%, #fbfcff 100%); border:1px solid var(--line);
        border-radius:16px; padding:.78rem .7rem .68rem; box-shadow:0 6px 16px rgba(47, 37, 29, .045);
    }
    .result-metric-icon {
        grid-column:1; grid-row:1; display:flex; align-items:center; justify-content:center;
        width:2.48rem; height:2.48rem; border-radius:50%; background:linear-gradient(145deg, #2854bf, #173c99);
        box-shadow:0 5px 11px rgba(28, 72, 176, .18);
    }
    .result-metric-icon svg { width:1.4rem; height:1.4rem; stroke:#fff; fill:none; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }
    .result-metric-label {
        grid-column:2; grid-row:1; align-self:center; display:block; color:var(--navy); font-size:.78rem;
        font-weight:800; line-height:1.28; word-break:keep-all; min-height:0;
    }
    .result-metric-value {
        grid-column:1 / -1; grid-row:2; align-self:end; display:flex; align-items:baseline; gap:.2rem;
        color:var(--blue); font-weight:800; line-height:1; margin-top:.2rem; letter-spacing:-.05em; white-space:nowrap;
    }
    .result-metric-number { font-size:2.18rem; }
    .result-metric-unit { color:var(--navy); font-size:.92rem; font-weight:700; letter-spacing:-.02em; }
    .st-key-result-top-right .notice { margin: .1rem 0 .55rem; }
    .st-key-result-top-right .official-grid { margin-top:.05rem; }
    .st-key-result-top-right .market-title { margin-top: .68rem; }
    .st-key-result-top-right .source-note { margin-top: .35rem; }
    .result-interpretation {
        display:grid; grid-template-columns:minmax(11rem, .78fr) minmax(0, 1fr) minmax(0, 1fr);
        gap:.65rem; align-items:stretch; margin:.8rem 0 .9rem; padding:.72rem;
        border:1px solid #efcfad; border-radius:18px;
        background:linear-gradient(105deg, #fff7ee 0%, #fffdf9 48%, #fff8ef 100%);
        box-shadow:0 8px 20px rgba(111, 69, 35, .055);
    }
    .result-interpretation-intro {
        display:flex; flex-direction:column; justify-content:center; padding:.32rem .52rem .32rem .18rem;
    }
    .result-interpretation-kicker {
        display:flex; align-items:center; gap:.38rem; color:#b85b38; font-size:.72rem; font-weight:800;
        letter-spacing:.02em; margin-bottom:.22rem;
    }
    .result-interpretation-kicker svg { width:1.08rem; height:1.08rem; stroke:#c96842; fill:#fffaf5; stroke-width:1.9; }
    .result-interpretation-title { color:var(--navy); font-size:1rem; font-weight:800; line-height:1.3; word-break:keep-all; }
    .result-interpretation-caution { color:#9b4d34; font-size:.73rem; font-weight:700; line-height:1.45; margin-top:.3rem; word-break:keep-all; }
    .result-interpretation-card {
        display:flex; align-items:center; gap:.56rem; min-width:0; padding:.72rem .72rem .66rem;
        border:1px solid var(--line); border-radius:13px; background:rgba(255,255,255,.78);
    }
    .result-interpretation-icon {
        flex:0 0 auto; display:flex; align-items:center; justify-content:center; width:2.15rem; height:2.15rem;
        border-radius:50%; background:#edf3ff;
    }
    .result-interpretation-icon svg { width:1.23rem; height:1.23rem; stroke:var(--blue); fill:none; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }
    .result-interpretation-card-report .result-interpretation-icon { background:#fff0e8; }
    .result-interpretation-card-report .result-interpretation-icon svg { stroke:#c96842; }
    .result-interpretation-card strong { display:block; color:var(--navy); font-size:.84rem; line-height:1.28; margin:.04rem 0 .16rem; word-break:keep-all; }
    .result-interpretation-card p { color:#65708a; font-size:.72rem; line-height:1.45; margin:0; word-break:keep-all; }
    .vehicle-visual {
        position:relative; width:100%; overflow:hidden; border-radius:18px;
        background-color:#e9e1d8; background-position:center; background-size:cover;
        box-shadow:inset 0 0 0 1px rgba(255,255,255,.24);
    }
    .result-vehicle-visual { min-height:clamp(24rem, 31vw, 31rem); }
    .preview-vehicle-visual { min-height:15rem; border-radius:16px; }
    .vehicle-visual-overlay {
        position:absolute; right:0; bottom:0; left:0; padding:1.15rem 1.2rem 1rem;
        background:linear-gradient(180deg, transparent 0%, rgba(8, 23, 45, .58) 38%, rgba(8, 23, 45, .97) 100%);
        color:#fff;
    }
    .vehicle-visual-brand { display:block; color:#e0eaff; font-size:.8rem; font-weight:700; margin-bottom:.18rem; }
    .vehicle-visual-title { display:block; color:#fff; font-size:1.42rem; font-weight:800; line-height:1.22; letter-spacing:-.035em; }
    .preview-vehicle-visual .vehicle-visual-overlay { padding:.88rem 1rem .8rem; }
    .preview-vehicle-visual .vehicle-visual-title { font-size:1.18rem; }
    .preview-vehicle-visual .vehicle-visual-brand { font-size:.72rem; }
    .st-key-interest-register-button,
    .st-key-interest-register-button-added { width:100% !important; margin-top:.8rem; }
    .st-key-interest-register-button button,
    .st-key-interest-register-button-added button {
        width:100% !important; min-height:3.2rem !important; border-radius:14px !important;
        font-size:1rem !important; font-weight:800 !important;
    }
    .st-key-interest-register-button button {
        background:#fffefd !important; border-color:#d4ae27 !important; color:var(--navy) !important;
        box-shadow:0 4px 11px rgba(100, 76, 12, .08);
    }
    .st-key-interest-register-button button:hover {
        background:#fff8dc !important; border-color:#bd970f !important;
    }
    .st-key-interest-register-button-added button,
    .st-key-interest-register-button-added button:disabled {
        background:#f5c542 !important; border-color:#dca900 !important; color:#4a3500 !important;
        box-shadow:0 5px 12px rgba(182, 139, 0, .18); opacity:1 !important;
    }
    .st-key-interest-register-button button:focus-visible,
    .st-key-interest-register-button-added button:focus-visible {
        outline:3px solid rgba(36,92,203,.3) !important; outline-offset:2px !important;
    }
    .report-heading { display:flex; align-items:flex-start; gap:.68rem; margin:.05rem 0 .78rem; }
    .report-heading-icon {
        display:flex; align-items:center; justify-content:center; flex:0 0 auto;
        width:2.28rem; height:2.28rem; border-radius:11px; background:#edf3ff;
    }
    .report-heading-icon svg {
        display:block; width:1.52rem; height:1.52rem; stroke:var(--blue); fill:none;
        stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round;
    }
    .report-heading-report .report-heading-icon { background:#fff0e8; }
    .report-heading-report .report-heading-icon svg { stroke:#d56f48; }
    .report-heading h3 { color:var(--navy); font-size:1.18rem; font-weight:800; line-height:1.25; margin:0; letter-spacing:-.035em; }
    .report-heading p { color:#68728a; font-size:.8rem; line-height:1.5; margin:.22rem 0 0; word-break:keep-all; }
    .report-notice {
        display:flex; align-items:center; gap:.55rem; padding:.66rem .78rem; margin:.05rem 0 .72rem;
        border:1px solid #f3c8b8; border-radius:14px; background:linear-gradient(100deg,#fff5f0,#fffbf8);
        color:#75452e; font-size:.79rem; line-height:1.5; word-break:keep-all;
    }
    .report-notice-icon { flex:0 0 auto; color:#d86b45; font-size:1.02rem; font-weight:800; line-height:1.2; }
    .chart-legend {
        display:flex; align-items:center; justify-content:center; gap:.45rem; width:max-content; min-width:8.2rem;
        margin:-.1rem auto .1rem; padding:.34rem .72rem; border:1px solid #eadbcc; border-radius:999px;
        background:#fffefd; color:var(--navy); font-size:.78rem; font-weight:700;
    }
    .chart-legend-swatch { width:.88rem; height:.88rem; border-radius:3px; background:var(--blue); box-shadow:0 2px 5px rgba(36,92,203,.2); }
    .report-table-wrap { width:100%; overflow:hidden; border:1px solid #eadbcc; border-radius:15px; background:#fffefd; }
    .report-table { width:100%; border-collapse:separate; border-spacing:0; table-layout:fixed; color:var(--navy); }
    .report-table th, .report-table td {
        padding:.72rem .62rem; border-right:1px solid #eee3d8; border-bottom:1px solid #eee3d8;
        overflow-wrap:anywhere; word-break:keep-all; vertical-align:middle;
    }
    .report-table th:last-child, .report-table td:last-child { border-right:0; }
    .report-table tbody tr:last-child td { border-bottom:0; }
    .report-table th { background:linear-gradient(180deg,#fbfcff,#f7faff); color:#53627b; font-size:.76rem; font-weight:800; text-align:left; }
    .report-table td { font-size:.8rem; font-weight:700; line-height:1.45; }
    .recall-report-table tbody tr:first-child td { background:#eef6ff; }
    .recall-report-table tbody tr:first-child td:last-child { color:var(--blue); font-weight:800; }
    .recall-report-table th:nth-child(1) { width:24%; }
    .recall-report-table th:nth-child(2) { width:36%; }
    .recall-report-table th:nth-child(3) { width:20%; }
    .recall-report-table th:nth-child(4) { width:20%; }
    .st-key-recall-report-panel [data-testid="stExpander"] {
        border:1px solid #eadbcc !important; border-radius:14px !important; overflow:hidden; background:#fffefd !important;
        margin-top:.68rem;
    }
    .st-key-recall-report-panel [data-testid="stExpander"] summary { padding:.18rem .22rem; }
    .st-key-recall-report-panel [data-testid="stExpander"] summary p { color:var(--navy) !important; font-size:.88rem !important; }
    .st-key-defect-report-panel .js-plotly-plot { border-radius:12px; }
    .comparison-report-intro { margin:.7rem 0 .72rem; color:#68728a; font-size:.84rem; line-height:1.55; }
    .comparison-report-table th, .comparison-report-table td { text-align:center; padding:.64rem .42rem; }
    .comparison-report-table th:first-child, .comparison-report-table td:first-child {
        width:15%; text-align:left; background:#fbfcff; color:var(--navy); font-weight:800;
    }
    .comparison-report-table th:not(:first-child), .comparison-report-table td:not(:first-child) { width:auto; }
    .comparison-report-table th { font-size:.72rem; }
    .comparison-report-table td { font-size:.76rem; }
    .comparison-report-table tbody tr:nth-child(4) td:not(:first-child),
    .comparison-report-table tbody tr:nth-child(5) td:not(:first-child),
    .comparison-report-table tbody tr:nth-child(6) td:not(:first-child) { color:var(--blue); font-weight:800; white-space:nowrap; }
    /* 시작 공익광고 모달: 화면 중앙에 두고, 확대해도 배너 오른쪽에 빈 칸이 생기지 않게 한다. */
    [data-testid="stDialog"] {
        align-items: center !important;
        justify-content: center !important;
        padding: 0.4rem !important;
        overflow: hidden !important;
        width: 100% !important;
        height: 100% !important;
        inset: 0 !important;
    }
    [data-testid="stDialog"]:has(.st-key-public-ad-dialog) > div {
        width: min(31.25rem, calc((100dvh - 5.8rem) * 1086 / 1448)) !important;
        min-width: 0 !important;
        max-width: calc(100vw - 0.8rem) !important;
        margin: 0 !important;
        max-height: calc(100dvh - 0.8rem) !important;
        overflow: hidden !important;
    }
    [data-testid="stDialog"]:has(.st-key-compare-preview-dialog) > div {
        width: min(38rem, calc(100vw - 1.2rem)) !important;
        min-width: 0 !important;
        max-width: calc(100vw - 1.2rem) !important;
        margin: 0 !important;
        max-height: calc(100dvh - 0.8rem) !important;
        overflow-y: auto !important;
    }
    [data-testid="stDialog"]:has(.st-key-compare-preview-dialog) [slot="title"] {
        color: var(--navy) !important; font-size: 1.68rem !important;
        font-weight: 800 !important; letter-spacing: -.04em;
        padding: .85rem 3.25rem .55rem 1.15rem !important;
    }
    [data-testid="stDialog"]:has(.st-key-compare-preview-dialog) button[aria-label="Close"] {
        top: .7rem !important; right: .9rem !important; transform: scale(1.15);
    }
    [data-testid="stDialog"]:has(.st-key-compare-preview-dialog) [slot="title"] + div {
        padding: 0 1.15rem 1.05rem !important;
    }
    [data-testid="stDialog"] [slot="title"] {
        font-size: 0.95rem !important;
        line-height: 1.25 !important;
        padding: 0.45rem 2.2rem 0.2rem 0.9rem !important;
    }
    [data-testid="stDialog"] [slot="title"] * {
        font-size: inherit !important;
        line-height: inherit !important;
    }
    [data-testid="stDialog"] button[aria-label="Close"] {
        top: 0.4rem !important;
        right: 0.6rem !important;
        z-index: 20 !important;
        cursor: pointer !important;
        pointer-events: auto !important;
    }
    [data-testid="stDialog"] [data-testid="stElementToolbar"],
    [data-testid="stDialog"] [data-testid="stElementToolbarButtonContainer"] {
        display: none !important;
    }
    [data-testid="stDialog"]:has(.st-key-public-ad-dialog) [data-testid="stImage"] {
        pointer-events: none;
    }
    [data-testid="stDialog"] [slot="title"] + div {
        padding: 0 0.55rem 0.4rem !important;
    }
    [data-testid="stDialog"]:has(.st-key-public-ad-dialog) [data-testid="stImage"] img {
        display: block;
        width: 100% !important;
        max-height: calc(100dvh - 5.8rem) !important;
        height: auto !important;
        object-fit: contain;
    }
    [data-testid="stDialog"]:has(.st-key-compare-preview-dialog) [data-testid="stImage"] {
        display: flex !important;
        justify-content: center !important;
        width: 100% !important;
        background: #10213d;
        border: 0;
        border-radius: 16px 16px 0 0;
        padding: 0;
        margin: 0;
        overflow: hidden;
        box-sizing: border-box;
    }
    /* Streamlit 이미지 래퍼가 원본 사진 폭으로 줄어드는 경우를 막는다. */
    .st-key-compare-preview-dialog [data-testid="stElementContainer"]:has([data-testid="stImage"]),
    .st-key-compare-preview-dialog [data-testid="stFullScreenFrame"],
    .st-key-compare-preview-dialog [data-testid="stFullScreenFrame"] > div,
    .st-key-compare-preview-dialog [data-testid="stImage"],
    .st-key-compare-preview-dialog [data-testid="stImage"] [data-testid="stImageContainer"] {
        width: 100% !important;
        align-self: stretch !important;
    }
    [data-testid="stDialog"]:has(.st-key-compare-preview-dialog) [data-testid="stImage"] > div,
    [data-testid="stDialog"]:has(.st-key-compare-preview-dialog) [data-testid="stImage"] [data-testid="stImageContainer"] {
        width: 100% !important;
        display: flex !important;
        justify-content: center !important;
    }
    [data-testid="stDialog"]:has(.st-key-compare-preview-dialog) [data-testid="stImage"] img {
        display: block;
        width: 100% !important;
        max-width: 100% !important;
        height: 15rem !important;
        max-height: 15rem !important;
        margin: 0 auto;
        object-fit: cover;
        border-radius: 0;
    }
    .st-key-compare-preview-dialog .car-card {
        min-height: 15rem;
        width: 100%;
        margin: 0 auto;
        border-radius: 16px 16px 0 0;
    }
    .preview-identity {
        background: linear-gradient(110deg, #10213d, #193761);
        color: #fff; padding: .9rem 1.05rem .98rem; border-radius: 0 0 18px 18px;
        margin: 0 0 .85rem;
    }
    .preview-identity-brand {
        display: block; color: #cbdcff; font-size: .72rem; font-weight: 700;
        letter-spacing: .04em; margin-bottom: .1rem;
    }
    .preview-identity-title {
        color: #fff; font-size: 1.3rem; font-weight: 800; line-height: 1.25;
        letter-spacing: -.025em;
    }
    .preview-safety-callout {
        display: flex; gap: .82rem; align-items: center;
        background: linear-gradient(100deg, #fff9f4, #fff4ec);
        border: 1px solid #f5d6c7; border-radius: 15px; padding: .78rem .9rem;
        margin: 0 0 .85rem; color: #a94f39;
    }
    .preview-safety-badge {
        flex: 0 0 auto; display: flex; align-items: center; justify-content: center;
        width: 2.65rem; height: 2.65rem;
    }
    .preview-safety-badge svg {
        width: 100%; height: 100%; stroke: #df7257; fill: #fff8f2;
    }
    .preview-safety-title {
        display: block; color: #ce644c; font-size: .94rem; font-weight: 800;
        line-height: 1.3; margin-bottom: .08rem;
    }
    .preview-safety-copy {
        display: block; color: #78655d; font-size: .78rem; line-height: 1.4;
        word-break: keep-all;
    }
    .preview-metrics {
        display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0; margin: 0 0 .85rem; border: 1px solid var(--line);
        border-radius: 16px; overflow: hidden; background: #fffdfb;
    }
    .preview-metric {
        background: #fffdfb; padding: .8rem .32rem .75rem; text-align: center;
        min-width: 0;
    }
    .preview-metric + .preview-metric {
        border-left: 1px solid var(--line);
    }
    .preview-metric-label {
        display: block; color: var(--navy); font-size: .72rem; font-weight: 800;
        line-height: 1.25; word-break: keep-all; margin-bottom: .14rem;
    }
    .preview-metric-context {
        display: none;
    }
    .preview-metric-icon {
        width: 2.55rem; height: 2.55rem; border-radius: 50%; margin: 0 auto .45rem;
        display: flex; align-items: center; justify-content: center; background: #fbf1e4;
    }
    .preview-metric-icon svg {
        width: 1.45rem; height: 1.45rem; stroke: var(--navy); fill: none;
        stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round;
    }
    .preview-metric-value {
        display: block; color: var(--blue); font-size: 1.52rem; font-weight: 800;
        line-height: 1.2;
    }
    .st-key-compare-register-button,
    .st-key-compare-register-button-added {
        margin-top: .05rem;
    }
    .st-key-compare-register-button button,
    .st-key-compare-register-button-added button {
        width: 100% !important; min-height: 3.25rem !important; border-radius: 14px !important;
        font-size: 1.12rem !important; font-weight: 800 !important;
    }
    .st-key-compare-register-button button {
        background:#fffefd !important; border-color:#d4ae27 !important; color:var(--navy) !important;
        box-shadow:0 4px 11px rgba(100, 76, 12, .08);
    }
    .st-key-compare-register-button button:hover {
        background:#fff8dc !important; border-color:#bd970f !important;
    }
    .st-key-compare-register-button-added button,
    .st-key-compare-register-button-added button:disabled {
        background: #f5c542 !important; border-color: #dca900 !important; color: #4a3500 !important;
        box-shadow:0 5px 12px rgba(182, 139, 0, .18); opacity: 1 !important;
    }
    .st-key-compare-list-link {
        display: flex !important; justify-content: center !important; margin-top: -.25rem;
    }
    .st-key-compare-list-link button {
        border: 0 !important; background: transparent !important; color: var(--navy) !important;
        text-decoration: underline !important; font-size: .85rem !important; font-weight: 700 !important;
        min-height: 2rem !important; padding: .25rem .5rem !important;
    }
    .public-ad-card {
        background: linear-gradient(145deg, #10213d 0%, #1d345a 55%, #b85f4f 155%);
        border-radius: 18px; overflow: hidden; color: #fff; padding: 1.35rem;
        box-shadow: 0 12px 28px rgba(16, 33, 61, .22);
    }
    .public-ad-top { display:flex; align-items:center; gap:.8rem; margin-bottom: 1.15rem; }
    .public-ad-icon { width:46px; height:50px; flex: 0 0 auto; }
    .public-ad-eyebrow { color:#ffd0a3; font-size:.72rem; letter-spacing:.12em; font-weight:800; }
    .public-ad-title { font-size:1.48rem; line-height:1.25; letter-spacing:-.04em; margin:.2rem 0 .45rem; }
    .public-ad-copy { color:#fff1e4; font-size:.93rem; line-height:1.65; margin:0; }
    .public-ad-points { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:.6rem; margin-top:1.15rem; }
    .public-ad-point { background:rgba(255,255,255,.11); border:1px solid rgba(255,223,199,.28); border-radius:13px; padding:.8rem; }
    .public-ad-point strong { display:block; color:#fff; font-size:.92rem; margin-bottom:.2rem; }
    .public-ad-point span { color:#ffe9d9; font-size:.77rem; line-height:1.45; }
    [data-testid="stDialog"] [data-testid="stCheckbox"] {
        display: flex;
        justify-content: flex-end;
        margin-top: 0.2rem;
    }
    [data-testid="stDialog"] [data-testid="stCheckbox"] label {
        justify-content: flex-end;
        width: 100%;
    }
    [data-testid="stDialog"] [data-testid="stCheckbox"] p {
        font-size: 0.78rem !important;
        color: var(--muted) !important;
        white-space: nowrap;
    }
    .st-key-header-interest {
        display: flex !important;
        justify-content: flex-end !important;
        align-items: center !important;
        position: relative;
        z-index: 8;
        min-height: 3.15rem;
        margin: 0 !important;
        padding: 0 !important;
        width: 100% !important;
        pointer-events: none;
    }
    .st-key-header-interest [data-testid="stVerticalBlock"],
    .st-key-header-interest [data-testid="stVerticalBlockBorderWrapper"],
    .st-key-header-interest [data-testid="stHorizontalBlock"] {
        width: fit-content !important;
        max-width: fit-content !important;
        margin-left: auto !important;
        gap: 0 !important;
        min-height: 0 !important;
        pointer-events: none;
    }
    .st-key-header-interest button {
        width: auto !important;
        min-width: 0 !important;
        white-space: nowrap !important;
        padding: 0.35rem 0.85rem !important;
        pointer-events: auto;
    }
    [data-testid="stPopoverBody"] {
        min-width: 22.5rem;
    }
    .interest-item {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: .65rem;
        padding: .45rem 0;
        border-bottom: 1px solid var(--line);
    }
    .interest-item:last-of-type { border-bottom: none; }
    .interest-item-text { min-width: 0; flex: 1; }
    .interest-item-text strong {
        display: block; color: var(--navy); font-size: .82rem; line-height: 1.3;
        word-break: keep-all;
    }
    .interest-item-text small {
        display: block; color: var(--muted); font-size: .72rem; margin-top: .12rem;
    }
    .interest-item-photo {
        width: 76px; height: 50px; object-fit: cover; border-radius: 8px;
        flex-shrink: 0; background: #fff2e7; border: 1px solid var(--line);
    }
    .interest-item-photo-empty {
        display: flex; align-items: center; justify-content: center; font-size: 1.15rem;
    }
    .st-key-compare-tag-list button {
        border-radius: 999px !important;
        min-height: 2rem !important;
        padding: 0.15rem 0.8rem !important;
        font-size: 0.82rem !important;
        font-weight: 700 !important;
    }
    @media (max-width: 720px) {
        .block-container { padding-top: 3.6rem !important; }
        .hero { min-height: 200px; padding: 1.2rem 1.1rem; }
        .hero-inner { max-width: 78%; }
        .hero h1 { font-size: 1.45rem; }
        .hero p { font-size: .9rem; }
        [data-testid="stTabs"] { margin-top: 0 !important; }
        [data-testid="stTabs"] [role="tablist"] { margin-right: 0; width:100% !important; }
        [data-testid="stTabs"] [role="tab"] { flex:1; justify-content:center; padding:.45rem .35rem !important; }
        .public-ad-points { grid-template-columns:1fr; }
        .result-interpretation { grid-template-columns:1fr; gap:.48rem; padding:.7rem; }
        .result-interpretation-intro { padding:.12rem .16rem .3rem; }
        .result-interpretation-card { padding:.64rem .68rem; }
        .report-heading h3 { font-size:1.06rem; }
        .report-table th, .report-table td { padding:.58rem .42rem; font-size:.72rem; word-break:break-all; }
        .comparison-report-table th { font-size:.64rem; }
        .comparison-report-table td { font-size:.67rem; }
        .comparison-report-table th:first-child, .comparison-report-table td:first-child { width:18%; }
    }
    [data-testid="stHtml"] {
        display: none !important;
        height: 0 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# SQLite 공통 함수
# ---------------------------------------------------------------------------
@st.cache_resource
def get_connection() -> sqlite3.Connection:
    """앱이 실행되는 동안 재사용할 SQLite 연결을 연다."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"SQLite DB를 찾지 못했습니다: {DB_PATH}")
    connection = sqlite3.connect(DB_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


@st.cache_data(ttl=300)
def read_query(query: str, params: tuple | dict = ()) -> pd.DataFrame:
    """읽기 전용 SQL을 실행하고 DataFrame으로 돌려준다."""
    connection = get_connection()
    return pd.read_sql_query(query, connection, params=params)


def clean_key(value: str) -> str:
    """사진 파일을 찾을 때 사용할 비교용 문자열."""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


@st.cache_data(show_spinner=False)
def load_image_aliases() -> list[dict[str, str]]:
    """차종 변형이 대표 사진을 함께 쓰도록 매핑표를 읽는다."""
    if not IMAGE_ALIAS_PATH.exists():
        return []

    aliases = pd.read_csv(IMAGE_ALIAS_PATH, encoding="utf-8-sig").fillna("")
    required = {"manufacturer_name", "model_pattern", "image_filename"}
    if not required.issubset(aliases.columns):
        return []

    return [
        {
            "manufacturer_key": clean_key(row["manufacturer_name"]),
            "model_pattern_key": clean_key(row["model_pattern"]),
            "image_filename": str(row["image_filename"]).strip(),
        }
        for _, row in aliases.iterrows()
        if clean_key(row["manufacturer_name"])
        and clean_key(row["model_pattern"])
        and str(row["image_filename"]).strip()
    ]


def find_car_image(manufacturer: str, model: str) -> Path | None:
    """assets/vehicles에서 제조사·차종에 맞는 첫 번째 사진을 찾는다."""
    if not IMAGE_DIR.exists():
        return None

    manufacturer_key = clean_key(manufacturer)
    model_key = clean_key(model)
    extensions = {".jpg", ".jpeg", ".png", ".webp"}

    # 파일 이름 전체에 제조사와 차종이 들어간 경우를 우선 찾는다.
    candidates = sorted(
        path for path in IMAGE_DIR.rglob("*") if path.is_file() and path.suffix.lower() in extensions
    )
    for path in candidates:
        key = clean_key(path.stem)
        if manufacturer_key in key and model_key in key:
            return path

    # 제조사 폴더 안에 차종 파일을 넣는 방식도 지원한다.
    for path in candidates:
        if model_key in clean_key(path.stem) and manufacturer_key in clean_key(path.parent.name):
            return path

    # 같은 기본 차종의 하이브리드·구동방식·트림은 대표 사진을 함께 사용한다.
    # 실제로 다른 차종인 경우에는 매핑 CSV에 행을 추가하지 않는다.
    for alias in load_image_aliases():
        if (
            alias["manufacturer_key"] == manufacturer_key
            and alias["model_pattern_key"] in model_key
        ):
            alias_path = IMAGE_DIR / alias["image_filename"]
            if alias_path.is_file() and alias_path.suffix.lower() in extensions:
                return alias_path
    return None


def format_number(value: object) -> str:
    """숫자를 화면용 천 단위 구분 문자열로 표시한다."""
    if value is None or pd.isna(value):
        return "0"
    return f"{int(value):,}"


def format_date(value: object) -> str:
    if value is None or pd.isna(value) or str(value) in {"", "None"}:
        return "-"
    return str(value).replace("-", ".")


def resolve_icon_path(relative_stem: str) -> str:
    """png/svg 등 실제 존재하는 아이콘 파일 경로를 고른다."""
    if not relative_stem:
        return ""
    stem = Path(relative_stem)
    if stem.suffix.lower() in ICON_MIME_TYPES:
        return relative_stem if (ICON_DIR / relative_stem).is_file() else ""
    for extension in (".png", ".svg", ".webp", ".jpg", ".jpeg"):
        relative_path = f"{relative_stem}{extension}"
        if (ICON_DIR / relative_path).is_file():
            return relative_path
    return ""


def file_to_data_uri(relative_path: str) -> str:
    """아이콘 파일을 카드 HTML에 넣을 data URI로 바꾼다."""
    if not relative_path:
        return ""
    path = ICON_DIR / relative_path
    mime = ICON_MIME_TYPES.get(path.suffix.lower(), "")
    if not mime or not path.is_file():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def image_file_to_data_uri(path: Path) -> str:
    """차량 사진 파일을 목록 HTML에 넣을 data URI로 바꾼다."""
    mime = ICON_MIME_TYPES.get(path.suffix.lower(), "")
    if not mime or not path.is_file():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def shield_car_icon_html(class_name: str = "service-logo-icon") -> str:
    """공통 헤더에 표시할 서비스 로고를 반환한다."""
    logo_uri = image_file_to_data_uri(SERVICE_LOGO_PATH)
    if logo_uri:
        return (
            f"<img class='{html.escape(class_name, quote=True)}' src='{logo_uri}' "
            "alt='자동차 리콜·결함 조회 서비스 로고'>"
        )
    return ""


def brand_icon_html(relative_stem: str, fallback: str) -> str:
    """로고 파일이 있으면 이미지로, 없으면 글자 아이콘으로 표시한다."""
    uri = file_to_data_uri(resolve_icon_path(relative_stem))
    if uri:
        return (
            "<span class='market-icon market-icon-image'>"
            f"<img src='{uri}' alt=''></span>"
        )
    return f"<span class='market-icon'>{html.escape(fallback)}</span>"


def link_card_html(title: str, description: str, url: str | None, icon_html: str) -> str:
    """중고차·공식 사이트 이동용 카드 HTML을 만든다."""
    inner = (
        f"{icon_html}<span class='market-card-copy'>"
        f"<strong>{html.escape(title)}</strong>"
        f"<small>{html.escape(description)}</small></span>"
    )
    if url:
        return (
            f"<a class='market-card' href='{html.escape(url, quote=True)}' "
            "target='_blank' rel='noopener noreferrer'>"
            f"{inner}</a>"
        )
    return f"<span class='market-card market-card-disabled'>{inner}</span>"


def manufacturer_site_label(manufacturer: str) -> str:
    """버튼에 넣을 짧은 제조사 공식 사이트 이름을 만든다."""
    short_name = MANUFACTURER_SHORT_NAMES.get(manufacturer, manufacturer)
    return f"{short_name} 공식 사이트"


def render_official_links(manufacturer: str) -> None:
    """조회한 차량을 공식 사이트에서 다시 확인할 수 있는 카드형 링크를 표시한다."""
    recall_card = link_card_html(
        "리콜센터",
        "정부 자동차리콜센터",
        GOVERNMENT_RECALL_URL,
        brand_icon_html("recall_center.png", "🚨"),
    )
    manufacturer_url = MANUFACTURER_OFFICIAL_URLS.get(manufacturer)
    manufacturer_icon = brand_icon_html(
        MANUFACTURER_ICON_FILES.get(manufacturer, ""),
        manufacturer[:1] if manufacturer else "M",
    )
    manufacturer_card = link_card_html(
        manufacturer_site_label(manufacturer),
        "제조사 홈페이지",
        manufacturer_url,
        manufacturer_icon,
    )
    st.markdown(
        "<div class='official-grid'>" + recall_card + manufacturer_card + "</div>",
        unsafe_allow_html=True,
    )


def render_purchase_links() -> None:
    """중고차 구매 사이트를 카드형 외부 링크로 표시한다."""
    st.markdown("<div class='market-title'>중고차 매물 이어서 보기</div>", unsafe_allow_html=True)
    cards = [
        link_card_html(name, description, url, brand_icon_html(icon_path, name[:1]))
        for icon_path, name, description, url in USED_CAR_MARKET_LINKS
    ]
    st.markdown("<div class='market-grid'>" + "".join(cards) + "</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='source-note'>외부 중고차 매물 사이트로 이동합니다. "
        "매물 정보와 거래 조건은 각 사이트에서 다시 확인하세요.</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# 조회 SQL
# ---------------------------------------------------------------------------
MANUFACTURERS_SQL = """
SELECT manufacturer_id, manufacturer_name
FROM manufacturers
ORDER BY manufacturer_name
"""

MODELS_SQL = """
SELECT model_id, model_name, vehicle_type
FROM vehicle_models
WHERE manufacturer_id = :manufacturer_id
ORDER BY model_name
"""

YEARS_SQL = """
SELECT DISTINCT model_year
FROM defect_reports
WHERE model_id = :model_id AND model_year IS NOT NULL
ORDER BY model_year DESC
"""

OVERVIEW_SQL = """
SELECT model_id, manufacturer_name, model_name, vehicle_type,
       complaint_count, latest_report_date, recall_record_count,
       affected_count_sum, latest_recall_date
FROM model_overview
WHERE model_id = :model_id
"""

RECALLS_SQL = """
SELECT recall_id, raw_model_name, production_start_date, production_end_date,
       recall_start_date, affected_count, recall_reason
FROM recalls
WHERE model_id = :model_id
ORDER BY recall_start_date DESC, recall_id DESC
"""

DEFECT_BY_YEAR_SQL = """
SELECT model_year, COUNT(*) AS complaint_count
FROM defect_reports
WHERE model_id = :model_id AND model_year IS NOT NULL
GROUP BY model_year
ORDER BY model_year
"""

DEFECT_COUNT_SQL = """
SELECT COUNT(*) AS complaint_count
FROM defect_reports
WHERE model_id = :model_id
"""

DEFECT_COUNT_BY_YEAR_SQL = """
SELECT COUNT(*) AS complaint_count
FROM defect_reports
WHERE model_id = :model_id AND model_year = :model_year
"""

VARIANTS_SQL = """
SELECT variant_id, variant_name
FROM vehicle_variants
WHERE model_id = :model_id
ORDER BY variant_name
"""

ALL_MODELS_SQL = """
SELECT vm.model_id, vm.model_name, m.manufacturer_name,
       vm.vehicle_type, mo.complaint_count, mo.recall_record_count,
       mo.affected_count_sum
FROM vehicle_models vm
JOIN manufacturers m ON m.manufacturer_id = vm.manufacturer_id
JOIN model_overview mo ON mo.model_id = vm.model_id
ORDER BY m.manufacturer_name, vm.model_name
"""


# ---------------------------------------------------------------------------
# 공통 데이터: 제조사 목록은 차종 비교와 리콜 조회가 함께 사용한다.
# 검색 조건 자체는 리콜 조회 페이지에서만 렌더링한다.
# ---------------------------------------------------------------------------
try:
    manufacturers = read_query(MANUFACTURERS_SQL)
except FileNotFoundError as error:
    st.error(str(error))
    st.info("프로젝트 루트에서 `python scripts/build_database.py`를 먼저 실행하세요.")
    st.stop()

# 조회 버튼을 누른 조건을 기억한다. 상단 탭을 바꿔도 리콜 조회 결과를 유지한다.
if "search_state" not in st.session_state:
    st.session_state.search_state = None
if "interest_cars" not in st.session_state:
    st.session_state.interest_cars = []
if "compare_preview" not in st.session_state:
    st.session_state.compare_preview = None
if "public_ad_open" not in st.session_state:
    hidden_date = st.context.cookies.get(PUBLIC_AD_HIDE_COOKIE)
    st.session_state.public_ad_open = hidden_date != date.today().isoformat()


# ---------------------------------------------------------------------------
# 공통 헤더
# ---------------------------------------------------------------------------
def render_site_header() -> None:
    """앱 전체에서 공통으로 보이는 서비스 제목을 표시한다."""
    st.markdown(
        f"""
        <div class="top-brand">
          <div class="top-brand-mark">{shield_car_icon_html()}</div>
          <div>
            <div class="top-brand-title">자동차 리콜·결함 조회 서비스</div>
            <div class="top-brand-subtitle">중고차 구매 전 리콜 이력과 소유자 결함 신고를 확인하세요.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_hero() -> None:
    """현재 페이지의 공통 안내 배너를 표시한다."""
    hero_uri = image_file_to_data_uri(HERO_IMAGE_PATH)
    hero_style = (
        "background-image: linear-gradient(90deg, rgba(10, 27, 52, .98) 0%, "
        "rgba(10, 27, 52, .94) 22%, rgba(10, 27, 52, .72) 43%, "
        "rgba(10, 27, 52, .34) 61%, rgba(10, 27, 52, .08) 80%, transparent 100%), "
        f"url('{hero_uri}');"
        if hero_uri
        else "background: linear-gradient(115deg, #10213d 0%, #473d54 65%, #e98666 100%);"
    )
    st.markdown(
        f"""
        <div class="hero" style="{hero_style}">
          <div class="hero-inner">
            <div class="eyebrow">USED CAR SAFETY CHECK</div>
            <h1>중고차 구매 전, 리콜과 결함을 한눈에</h1>
            <p>가족과 함께할 차, 더 안심하고 골라보세요.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_interest_summary() -> None:
    """관심 차량 버튼을 탭과 같은 줄 오른쪽에 두고, 목록에 사진을 함께 보여준다."""
    saved = st.session_state.get("interest_cars", [])
    with st.popover(f"☆ 관심 차량 {len(saved)}/5", width="content"):
        if saved:
            cards = []
            for car in saved:
                image_path = find_car_image(str(car["manufacturer"]), str(car["model_name"]))
                if image_path:
                    uri = image_file_to_data_uri(image_path)
                    photo = (
                        f"<img class='interest-item-photo' src='{uri}' alt=''>"
                        if uri
                        else "<span class='interest-item-photo interest-item-photo-empty'>🚙</span>"
                    )
                else:
                    photo = "<span class='interest-item-photo interest-item-photo-empty'>🚙</span>"
                cards.append(
                    "<div class='interest-item'>"
                    "<div class='interest-item-text'>"
                    f"<strong>{html.escape(str(car['model_name']))}</strong>"
                    f"<small>{html.escape(str(car['manufacturer']))} · {html.escape(str(car['year']))}</small>"
                    f"</div>{photo}</div>"
                )
            st.markdown("".join(cards), unsafe_allow_html=True)
            if st.button("목록 비우기", key="clear_interest_cars", width="stretch"):
                st.session_state.interest_cars = []
                st.rerun()
        else:
            st.caption("차량 조회나 차종 비교에서 등록하면 비교 대상 태그로 표시됩니다.")


def dismiss_public_ad() -> None:
    """광고 모달의 우측 상단 X를 눌렀을 때 다시 자동으로 열리지 않게 한다."""
    st.session_state.public_ad_open = False
    if st.session_state.get("hide_public_ad_today"):
        st.session_state.persist_hide_public_ad = True


def persist_hide_public_ad_today() -> None:
    """오늘 하루 배너를 숨기도록 브라우저 쿠키를 남긴다."""
    today = date.today().isoformat()
    now = datetime.now()
    midnight = datetime.combine(now.date() + timedelta(days=1), time.min)
    max_age = max(60, int((midnight - now).total_seconds()))
    st.html(
        f'<script>document.cookie="{PUBLIC_AD_HIDE_COOKIE}={today};path=/;max-age={max_age};SameSite=Lax";</script>',
        unsafe_allow_javascript=True,
    )


@st.dialog(
    "차량 안전 안내",
    width="small",
    dismissible=True,
    on_dismiss=dismiss_public_ad,
)
def render_public_service_ad() -> None:
    """앱 시작 시 표시하는 자동차 리콜 공익광고 모달."""
    with st.container(key="public-ad-dialog"):
        if AD_IMAGE_PATH.exists():
            st.image(str(AD_IMAGE_PATH), width="stretch")
        else:
            st.warning("공익광고 이미지를 찾지 못했습니다.")
        st.checkbox("오늘 하루동안 보지않기", key="hide_public_ad_today")


def add_interest_car(search: dict[str, object]) -> tuple[bool, str]:
    """조회한 차량을 중복 없이 최대 5대까지 관심 목록에 추가한다."""
    saved = st.session_state.get("interest_cars", [])
    candidate_key = car_identity(search)
    existing_keys = {car_identity(car) for car in saved}
    if candidate_key in existing_keys:
        return False, "이미 등록한 차량입니다."
    if len(saved) >= 5:
        return False, "관심 차량은 최대 5대까지 등록할 수 있습니다."
    st.session_state.interest_cars = [*saved, dict(search)]
    return True, "관심 차량에 등록했습니다."


def car_identity(car: dict[str, object]) -> tuple[int, str]:
    """관심·비교 목록에서 같은 차량인지 비교할 때 쓴다."""
    year = car.get("year", car.get("model_year"))
    return (int(car["model_id"]), str(year))


def car_tag_label(car: dict[str, object]) -> str:
    """비교 화면에 붙일 짧은 차종 태그 문구."""
    year = car.get("year", car.get("model_year"))
    year_label = "전체" if year == "전체 연식" else f"{year}년형"
    return f"{car['model_name']} · {year_label} ×"


def remove_interest_car(model_id: int, year: object) -> None:
    """관심 차량 태그에서 해당 차종을 뺀다."""
    target = (int(model_id), str(year))
    st.session_state.interest_cars = [
        car for car in st.session_state.get("interest_cars", [])
        if car_identity(car) != target
    ]


def complaint_count_help(year: object) -> str:
    """신고 건수 카드에 붙는 설명을 연식 선택에 맞게 반환한다."""
    if year == "전체 연식":
        return "선택한 대표 차종의 모든 모델연도에 접수된 소비자 결함 신고 행의 누적 건수입니다."
    return f"선택한 {year}년형에 접수된 소비자 결함 신고 행의 수입니다."


def get_summary_metrics(model_id: int, year: object) -> tuple[str, int, int, int] | None:
    """조회·비교 팝업에 쓸 요약 숫자를 가져온다."""
    overview = read_query(OVERVIEW_SQL, {"model_id": model_id})
    if overview.empty:
        return None
    summary = overview.iloc[0]
    if year == "전체 연식":
        complaint_count = int(summary["complaint_count"])
        year_label = "누적 소비자 결함 신고수"
    else:
        year_count = read_query(
            DEFECT_COUNT_BY_YEAR_SQL,
            {"model_id": model_id, "model_year": int(year)},
        )
        complaint_count = int(year_count.iloc[0]["complaint_count"])
        year_label = f"{year}년형 신고"
    return (
        year_label,
        complaint_count,
        int(summary["recall_record_count"]),
        int(summary["affected_count_sum"]),
    )


def dismiss_compare_preview() -> None:
    """비교 조회 팝업을 닫으면 다시 자동으로 열리지 않게 한다."""
    st.session_state.compare_preview = None


def preview_icon_svg(icon_name: str) -> str:
    """비교 차량 미리보기의 안내·지표용 선형 아이콘을 반환한다."""
    paths = {
        "shield": (
            '<path d="M12 2.5 21 5.6v7c0 5.3-3.4 9.7-9 12.1-5.6-2.4-9-6.8-9-12.1v-7L12 2.5Z"/>'
            '<path d="m8.2 13 2.4 2.4 5.3-5.5"/>'
        ),
        "report": (
            '<path d="M7 3.5h8.5L20 8v12.5H7z"/><path d="M15.5 3.5V8H20"/>'
            '<path d="M10 11h5.5M10 14.5h4"/><circle cx="17.8" cy="17.8" r="3.2"/><path d="m20.1 20.1 1.9 1.9"/>'
        ),
        "bell": (
            '<path d="M6 17.5h12l-1.5-2.2v-4.7a4.5 4.5 0 0 0-9 0v4.7z"/>'
            '<path d="M10 21h4M12 3v1.4"/>'
        ),
        "people": (
            '<circle cx="12" cy="8.2" r="3.2"/><path d="M5.4 21v-1.6a5.5 5.5 0 0 1 5.5-5.5h2.2a5.5 5.5 0 0 1 5.5 5.5V21"/>'
            '<path d="M4.4 8.8a2.6 2.6 0 0 1 2-2.5M19.6 8.8a2.6 2.6 0 0 0-2-2.5M2.5 20v-1.2a4.2 4.2 0 0 1 2.7-3.9M21.5 20v-1.2a4.2 4.2 0 0 0-2.7-3.9"/>'
        ),
    }
    return (
        '<svg viewBox="-1 -1 26 26" aria-hidden="true" focusable="false">'
        f"{paths[icon_name]}</svg>"
    )


@st.dialog(
    "비교 차량 미리보기",
    width="small",
    dismissible=True,
    on_dismiss=dismiss_compare_preview,
)
def render_compare_preview_dialog() -> None:
    """비교할 차종의 사진과 안전 요약을 사진 중심 팝업으로 보여준다."""
    preview = st.session_state.get("compare_preview")
    if not preview:
        return

    manufacturer = str(preview["manufacturer"])
    model_name = str(preview["model_name"])
    year = preview["year"]
    metrics = get_summary_metrics(int(preview["model_id"]), year)
    is_registered = any(
        car_identity(car) == car_identity(preview)
        for car in st.session_state.get("interest_cars", [])
    )
    year_text = "전체 연식" if year == "전체 연식" else f"{year}년형"

    with st.container(key="compare-preview-dialog", gap="small"):
        render_vehicle_visual_overlay(
            manufacturer,
            model_name,
            year_text,
            "preview-vehicle-visual",
        )
        if metrics is None:
            st.warning("선택한 차종의 요약 정보를 찾지 못했습니다.")
        else:
            year_label, complaint_count, recall_count, affected_sum = metrics
            st.markdown(
                "<div class='preview-safety-callout'>"
                f"<span class='preview-safety-badge'>{preview_icon_svg('shield')}</span>"
                "<div><span class='preview-safety-title'>구매 전 안전 정보를 함께 살펴보세요</span>"
                "<span class='preview-safety-copy'>결함 신고는 리콜 확정 여부와 다를 수 있어요.</span></div>"
                "</div>"
                "<div class='preview-metrics'>"
                f"<div class='preview-metric' title='{html.escape(complaint_count_help(year), quote=True)}'>"
                f"<span class='preview-metric-icon'>{preview_icon_svg('report')}</span>"
                "<span class='preview-metric-label'>소비자 결함 신고</span>"
                f"<span class='preview-metric-context'>{html.escape(year_label)}</span>"
                f"<strong class='preview-metric-value'>{html.escape(format_number(complaint_count))}건</strong>"
                "</div>"
                "<div class='preview-metric'>"
                f"<span class='preview-metric-icon'>{preview_icon_svg('bell')}</span>"
                "<span class='preview-metric-label'>공식 리콜 기록</span>"
                "<span class='preview-metric-context'>제조사 안전 조치</span>"
                f"<strong class='preview-metric-value'>{html.escape(format_number(recall_count))}건</strong>"
                "</div>"
                "<div class='preview-metric'>"
                f"<span class='preview-metric-icon'>{preview_icon_svg('people')}</span>"
                "<span class='preview-metric-label'>리콜 대상 대수</span>"
                "<span class='preview-metric-context'>공식 리콜 기준</span>"
                f"<strong class='preview-metric-value'>{html.escape(format_number(affected_sum))}대</strong>"
                "</div></div>",
                unsafe_allow_html=True,
            )
        button_key = "compare-register-button-added" if is_registered else "compare-register-button"
        button_label = "비교차량 등록됨" if is_registered else "비교차량 등록"
        with st.container(key=button_key):
            if st.button(
                button_label,
                key="add_compare_car",
                icon=":material/star:",
                width="stretch",
                disabled=is_registered,
            ):
                added, message = add_interest_car(preview)
                if added:
                    st.session_state.compare_preview = None
                    st.rerun()
                else:
                    st.warning(message)
        if is_registered:
            with st.container(key="compare-list-link"):
                if st.button(
                    "비교 목록 확인하기",
                    key="open_compare_list",
                    type="secondary",
                    width="stretch",
                ):
                    st.session_state.compare_preview = None
                    st.rerun()


def render_empty() -> None:
    st.markdown(
        """
        <div class="card empty-state">
          <span class="emoji">🚘</span>
          <h3>확인할 차량을 선택해 주세요</h3>
          <p>왼쪽에서 제조사와 대표 차종을 고른 뒤 <b>조회하기</b>를 누르면<br>
          공식 리콜 이력과 소비자 결함 신고를 함께 보여드립니다.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_car_visual(manufacturer: str, model: str) -> None:
    """사진이 있으면 출력하고, 없으면 나중에 사진을 넣을 위치를 보여준다."""
    image_path = find_car_image(manufacturer, model)
    if image_path:
        st.image(str(image_path), width="stretch")
        return
    st.markdown(
        f"""
        <div class="car-card">
          <div class="car-placeholder">
            <span class="emoji">🚙</span>
            <b>{html.escape(model)}</b><br>
            <small>차량 사진을 assets/vehicles에 추가할 수 있습니다</small>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_recall_search() -> None:
    """차량 조회 페이지 본문에 제조사·차종·연식 조건을 표시한다."""
    if manufacturers.empty:
        st.warning("등록된 제조사 데이터가 없습니다.")
        return

    manufacturer_names = manufacturers["manufacturer_name"].tolist()
    previous = st.session_state.get("search_state") or {}
    previous_manufacturer = previous.get("manufacturer")
    manufacturer_index = (
        manufacturer_names.index(previous_manufacturer)
        if previous_manufacturer in manufacturer_names
        else 0
    )

    with st.container(border=True, gap="small"):
        st.markdown("<div class='search-panel-title'>차량 검색 조건</div>", unsafe_allow_html=True)
        manufacturer_col, model_col, year_col, button_col = st.columns(
            [1.1, 1.35, 1, 0.8],
            vertical_alignment="bottom",
            gap="small",
        )
        with manufacturer_col:
            selected_manufacturer = st.selectbox(
                "제조사",
                manufacturer_names,
                index=manufacturer_index,
                key="recall_manufacturer",
            )

        manufacturer_row = manufacturers.loc[
            manufacturers["manufacturer_name"] == selected_manufacturer
        ]
        if manufacturer_row.empty:
            st.warning("선택한 제조사 정보를 찾지 못했습니다.")
            return
        manufacturer_id = int(manufacturer_row.iloc[0]["manufacturer_id"])
        models = read_query(MODELS_SQL, {"manufacturer_id": manufacturer_id})
        if models.empty:
            st.warning("이 제조사에 등록된 대표 차종이 없습니다.")
            return

        model_labels = models.apply(
            lambda row: f"{row['model_name']}  ·  {row['vehicle_type'] or '차종 미분류'}", axis=1
        ).tolist()
        previous_model_id = previous.get("model_id")
        model_index = 0
        model_ids = models["model_id"].tolist()
        if previous_manufacturer == selected_manufacturer and previous_model_id in model_ids:
            model_index = model_ids.index(previous_model_id)

        with model_col:
            selected_model_label = st.selectbox(
                "대표 차종",
                model_labels,
                index=model_index,
                key="recall_model",
            )
        selected_model_index = model_labels.index(selected_model_label)
        selected_model_id = int(models.iloc[selected_model_index]["model_id"])
        selected_model_name = str(models.iloc[selected_model_index]["model_name"])

        years_df = read_query(YEARS_SQL, {"model_id": selected_model_id})
        years = years_df["model_year"].dropna().astype(int).tolist()
        year_options: list[str | int] = ["전체 연식"] + years
        previous_year = previous.get("year") if previous_manufacturer == selected_manufacturer else None
        year_index = year_options.index(previous_year) if previous_year in year_options else 0
        with year_col:
            selected_year = st.selectbox(
                "모델 연도",
                year_options,
                index=year_index,
                key="recall_year",
            )

        with button_col:
            if st.button("조회하기", type="primary", width="stretch", key="recall_search_button"):
                st.session_state.search_state = {
                    "manufacturer": selected_manufacturer,
                    "model_id": selected_model_id,
                    "model_name": selected_model_name,
                    "year": selected_year,
                }
                st.rerun()

    if not st.session_state.get("search_state"):
        st.markdown(
            "<div class='source-note'>공식 리콜과 소유자 결함신고를 분리해서 보여드립니다. "
            "신고 건수는 리콜 확정 건수가 아닙니다.</div>",
        unsafe_allow_html=True,
    )


def render_vehicle_visual_overlay(
    manufacturer: str,
    model: str,
    year_text: str,
    variant: str,
) -> None:
    """차량 사진 하단에 제조사·차종 정보를 겹쳐 표시한다."""
    image_path = find_car_image(manufacturer, model)
    if image_path:
        image_uri = image_file_to_data_uri(image_path)
        if image_uri:
            st.markdown(
                f"<div class='vehicle-visual {html.escape(variant, quote=True)}' "
                f"style=\"background-image:url('{image_uri}');\">"
                "<div class='vehicle-visual-overlay'>"
                f"<span class='vehicle-visual-brand'>{html.escape(manufacturer)}</span>"
                f"<span class='vehicle-visual-title'>{html.escape(model)} · {html.escape(year_text)}</span>"
                "</div></div>",
                unsafe_allow_html=True,
            )
            return
    render_car_visual(manufacturer, model)


def report_heading_html(title: str, description: str, icon_name: str, tone: str = "blue") -> str:
    """조회·비교 화면에서 재사용하는 리포트형 섹션 제목을 만든다."""
    tone_class = " report-heading-report" if tone == "coral" else ""
    return (
        f"<div class='report-heading{tone_class}'>"
        f"<span class='report-heading-icon'>{preview_icon_svg(icon_name)}</span>"
        "<div>"
        f"<h3>{html.escape(title)}</h3>"
        f"<p>{html.escape(description)}</p>"
        "</div></div>"
    )


def report_table_html(data: pd.DataFrame, table_class: str) -> str:
    """가로 스크롤 없이 셀 너비를 배분하는 읽기 전용 리포트 표를 만든다."""
    headers = "".join(f"<th scope='col'>{html.escape(str(column))}</th>" for column in data.columns)
    rows: list[str] = []
    for _, row in data.iterrows():
        cells = "".join(f"<td>{html.escape(str(value))}</td>" for value in row)
        rows.append(f"<tr>{cells}</tr>")
    return (
        f"<div class='report-table-wrap'><table class='report-table {html.escape(table_class, quote=True)}'>"
        f"<thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def render_recall_history(model_id: int) -> None:
    """공식 리콜 이력 표와 리콜 사유 펼쳐보기를 표시한다."""
    st.markdown(
        report_heading_html(
            "공식 리콜 이력",
            "생산기간, 리콜 개시일, 대상 대수와 리콜 사유를 확인합니다.",
            "report",
        ),
        unsafe_allow_html=True,
    )
    recalls = read_query(RECALLS_SQL, {"model_id": model_id})
    if recalls.empty:
        st.info("등록된 공식 리콜 기록이 없습니다.")
        return

    display_recalls = recalls.copy()
    display_recalls["생산기간"] = display_recalls.apply(
        lambda row: f"{format_date(row['production_start_date'])} ~ {format_date(row['production_end_date'])}",
        axis=1,
    )
    display_recalls["리콜 개시일"] = display_recalls["recall_start_date"].map(format_date)
    display_recalls["대상 대수"] = display_recalls["affected_count"].map(lambda x: f"{format_number(x)}대")
    recall_table = display_recalls[["raw_model_name", "생산기간", "리콜 개시일", "대상 대수"]].rename(
        columns={"raw_model_name": "원본 차명"}
    )
    st.markdown(report_table_html(recall_table, "recall-report-table"), unsafe_allow_html=True)
    for _, recall in recalls.iterrows():
        title = f"{format_date(recall['recall_start_date'])} · {recall['raw_model_name']}"
        with st.expander(title):
            st.write(recall["recall_reason"] or "리콜 사유가 입력되지 않았습니다.")
            st.caption(
                f"생산기간: {format_date(recall['production_start_date'])} ~ {format_date(recall['production_end_date'])}  |  "
                f"대상 대수: {format_number(recall['affected_count'])}대"
            )


def render_defect_reports(model_id: int, year: object, complaint_count: int) -> None:
    """소유자 결함 신고 안내와 연도별 막대그래프를 표시한다."""
    st.markdown(
        report_heading_html(
            "소유자 결함 신고",
            "연식별 신고 흐름을 구매 전 참고 정보로 확인합니다.",
            "report",
            tone="coral",
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div class='report-notice'><span class='report-notice-icon'>!</span><span>"
        "신고 건수는 소유자가 접수한 기록입니다.<br>"
        "리콜 확정·대상 판정과 다를 수 있으며, 판매량을 반영한 비교가 아닙니다."
        "</span></div>",
        unsafe_allow_html=True,
    )
    defect_by_year = read_query(DEFECT_BY_YEAR_SQL, {"model_id": model_id})
    if defect_by_year.empty:
        st.info("모델연도가 있는 결함 신고 기록이 없습니다.")
        return

    chart_data = defect_by_year.copy()
    chart_data["model_year"] = chart_data["model_year"].astype(int)
    chart_data = chart_data.sort_values("model_year")
    chart_data["year_label"] = chart_data["model_year"].map(lambda value: f"{int(value) % 100:02d}")
    # 숫자로만 된 범주(예: "06")는 Plotly 주석에서 연속형 좌표로 해석될 수 있다.
    # 내부 키를 문자 범주로 분리하고, 눈에는 기존처럼 두 자리 연도만 표시한다.
    chart_data["year_axis"] = chart_data["model_year"].map(lambda value: f"year-{int(value)}")

    chart = px.bar(
        chart_data,
        x="year_axis",
        y="complaint_count",
        labels={"year_axis": "연도", "complaint_count": "신고 건수"},
        color_discrete_sequence=["#245ccb"],
    )
    chart.update_layout(
        height=320,
        autosize=True,
        margin=dict(l=12, r=12, t=24, b=18),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        bargap=0.42,
        font=dict(color="#53627b", family="Pretendard, Noto Sans KR, sans-serif"),
        showlegend=False,
    )
    chart.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=chart_data["year_axis"].tolist(),
        tickmode="array",
        tickvals=chart_data["year_axis"].tolist(),
        ticktext=chart_data["year_label"].tolist(),
        tickangle=0,
        fixedrange=True,
        title=None,
        showgrid=False,
    )
    max_count = int(chart_data["complaint_count"].max())
    chart.update_yaxes(
        rangemode="tozero",
        range=[0, max(5, int(max_count * 1.2) + 1)],
        dtick=1 if max_count <= 10 else None,
        tickformat=",d",
        fixedrange=True,
        gridcolor="#e7edf7",
        zeroline=False,
    )
    chart.update_traces(
        width=0.55,
        marker_line_width=0,
        name="신고 건수",
        customdata=chart_data[["year_label"]],
        hovertemplate="연식 %{customdata[0]}<br>신고 %{y:,}건<extra></extra>",
    )
    peak = chart_data.loc[chart_data["complaint_count"].idxmax()]
    chart.add_annotation(
        x=peak["year_axis"],
        y=int(peak["complaint_count"]),
        text=f"최고 {format_number(peak['complaint_count'])}건<br>({int(peak['model_year'])}년형)",
        showarrow=True,
        arrowhead=0,
        arrowcolor="#df8e68",
        ax=42,
        ay=-34,
        bgcolor="#fff8f3",
        bordercolor="#f0b79f",
        borderwidth=1,
        borderpad=5,
        font=dict(color="#c7633d", size=11),
        align="left",
    )
    st.plotly_chart(chart, width="stretch", config={"displayModeBar": False, "scrollZoom": False})
    st.markdown(
        "<div class='chart-legend'><span class='chart-legend-swatch'></span><span>신고 건수</span></div>",
        unsafe_allow_html=True,
    )
    if year != "전체 연식":
        st.info(f"현재 선택: {year}년형 · 신고 {format_number(complaint_count)}건")


def render_dashboard() -> None:
    """선택한 차종의 요약·리콜·신고를 4분할로 표시한다."""
    search = st.session_state.get("search_state")
    if not search:
        return

    model_id = int(search["model_id"])
    manufacturer = str(search["manufacturer"])
    model_name = str(search["model_name"])
    year = search["year"]
    metrics = get_summary_metrics(model_id, year)
    if metrics is None:
        st.warning("선택한 차종의 요약 정보를 찾지 못했습니다.")
        return
    year_label, complaint_count, recall_count, affected_sum = metrics

    is_registered = any(
        car_identity(car) == car_identity(search)
        for car in st.session_state.get("interest_cars", [])
    )
    year_text = "전체 연식" if year == "전체 연식" else f"{year}년형"

    st.markdown(
        f"<div class='result-header'>"
        f"<div class='result-title'><span class='result-title-icon'>{preview_icon_svg('shield')}</span>"
        f"{html.escape(model_name)} 리콜/결함 요약</div>"
        "<div class='result-emphasis'>"
        "공식 리콜과 소유자 결함신고를 분리해서 보여드립니다. "
        "신고 건수는 리콜 확정 건수가 아닙니다."
        "</div></div>",
        unsafe_allow_html=True,
    )

    top_left, top_right = st.columns(2, gap="medium")
    with top_left:
        with st.container(
            border=True,
            height="stretch",
            key="result-top-left",
            gap="small",
        ):
            render_vehicle_visual_overlay(
                manufacturer,
                model_name,
                year_text,
                "result-vehicle-visual",
            )
            button_key = "interest-register-button-added" if is_registered else "interest-register-button"
            button_label = "관심 차량 등록됨" if is_registered else "관심 차량 등록"
            with st.container(key=button_key):
                if st.button(
                    button_label,
                    key="add_interest_car",
                    icon=":material/star:",
                    width="stretch",
                    disabled=is_registered,
                ):
                    added, message = add_interest_car(search)
                    if added:
                        st.rerun()
                    else:
                        st.warning(message)

    with top_right:
        with st.container(
            border=True,
            height="stretch",
            key="result-top-right",
            gap="small",
        ):
            st.markdown(
                "<div class='result-safety-heading'>"
                f"{preview_icon_svg('shield')}<span>구매 전 안전 요약</span></div>"
                "<div class='result-metrics'>"
                f"<div class='result-metric' title='{html.escape(complaint_count_help(year), quote=True)}'>"
                f"<span class='result-metric-icon'>{preview_icon_svg('report')}</span>"
                "<span class='result-metric-label'>누적 소비자 결함 신고수</span>"
                f"<strong class='result-metric-value'><span class='result-metric-number'>{html.escape(format_number(complaint_count))}</span>"
                "<span class='result-metric-unit'>건</span></strong></div>"
                "<div class='result-metric'>"
                f"<span class='result-metric-icon'>{preview_icon_svg('bell')}</span>"
                "<span class='result-metric-label'>공식 리콜 기록</span>"
                f"<strong class='result-metric-value'><span class='result-metric-number'>{html.escape(format_number(recall_count))}</span>"
                "<span class='result-metric-unit'>건</span></strong></div>"
                "<div class='result-metric'>"
                f"<span class='result-metric-icon'>{preview_icon_svg('people')}</span>"
                "<span class='result-metric-label'>리콜 대상 대수 합계</span>"
                f"<strong class='result-metric-value'><span class='result-metric-number'>{html.escape(format_number(affected_sum))}</span>"
                "<span class='result-metric-unit'>대</span></strong></div>"
                "</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div class='notice'>"
                "주의: 대상 대수는 리콜 기록별 합계입니다. "
                "개별 차량 조치 여부는 차대번호로 확인하세요."
                "</div>",
                unsafe_allow_html=True,
            )
            render_official_links(manufacturer)
            render_purchase_links()

    st.markdown(
        "<section class='result-interpretation' aria-label='조회 결과 해석 안내'>"
        "<div class='result-interpretation-intro'>"
        "<div class='result-interpretation-kicker'>"
        f"{preview_icon_svg('shield')}<span>조회 결과 안내</span></div>"
        "<div class='result-interpretation-title'>두 정보는 서로 다른 기준으로 확인하세요</div>"
        "<div class='result-interpretation-caution'>신고 건수만으로 리콜 또는 결함이 확정되지는 않습니다.</div>"
        "</div>"
        "<div class='result-interpretation-card'>"
        f"<span class='result-interpretation-icon'>{preview_icon_svg('bell')}</span>"
        "<div><strong>공식 리콜 이력</strong>"
        "<p>제조사 또는 관계 기관이 진행한 안전 조치 정보를 확인합니다.</p></div>"
        "</div>"
        "<div class='result-interpretation-card result-interpretation-card-report'>"
        f"<span class='result-interpretation-icon'>{preview_icon_svg('report')}</span>"
        "<div><strong>소유자 결함 신고</strong>"
        "<p>구매 전 참고할 수 있는 소비자 반복 신고 흐름을 살펴봅니다.</p></div>"
        "</div>"
        "</section>",
        unsafe_allow_html=True,
    )

    bottom_left, bottom_right = st.columns(2, gap="medium")
    with bottom_left:
        with st.container(border=True, key="recall-report-panel"):
            render_recall_history(model_id)
    with bottom_right:
        with st.container(border=True, key="defect-report-panel"):
            render_defect_reports(model_id, year, complaint_count)


def render_compare() -> None:
    """관심 차량 태그와 한 줄 조회로 차종을 비교한다."""
    st.markdown("## 차종 비교")
    st.markdown(
        "관심 차량을 태그로 모아 비교합니다. 아래에서 차종을 조회해 비교 대상을 추가할 수 있습니다. "
        "판매량을 반영한 결함률은 아닙니다."
    )

    saved = st.session_state.get("interest_cars", [])
    st.markdown("<div class='search-panel-title'>관심 차량</div>", unsafe_allow_html=True)
    if saved:
        with st.container(key="compare-tag-list", horizontal=True, gap="small"):
            for car in saved:
                model_id = int(car["model_id"])
                year = car["year"]
                if st.button(
                    car_tag_label(car),
                    key=f"remove_interest_tag_{model_id}_{year}",
                    type="secondary",
                ):
                    remove_interest_car(model_id, year)
                    st.rerun()
    else:
        st.caption("등록된 관심 차량이 없습니다. 아래에서 차종을 조회해 추가할 수 있습니다.")

    if manufacturers.empty:
        st.warning("등록된 제조사 데이터가 없습니다.")
        return

    with st.container(border=True, gap="small"):
        st.markdown("<div class='search-panel-title'>비교 차량 추가 하기</div>", unsafe_allow_html=True)
        manufacturer_col, model_col, year_col, button_col = st.columns(
            [1.1, 1.35, 1, 0.8],
            vertical_alignment="bottom",
            gap="small",
        )
        manufacturer_options = manufacturers["manufacturer_name"].tolist()
        with manufacturer_col:
            if st.session_state.get("compare_lookup_manufacturer") not in manufacturer_options:
                st.session_state.compare_lookup_manufacturer = manufacturer_options[0]
            manufacturer = st.selectbox(
                "제조사",
                manufacturer_options,
                key="compare_lookup_manufacturer",
            )
        manufacturer_id = int(
            manufacturers.loc[
                manufacturers["manufacturer_name"] == manufacturer,
                "manufacturer_id",
            ].iloc[0]
        )
        models = read_query(MODELS_SQL, {"manufacturer_id": manufacturer_id})
        lookup_ready = not models.empty
        with model_col:
            if not lookup_ready:
                st.warning("이 제조사에 등록된 대표 차종이 없습니다.")
                model_label = ""
                model_id = 0
            else:
                model_labels = models["model_name"].tolist()
                if st.session_state.get("compare_lookup_model") not in model_labels:
                    st.session_state.compare_lookup_model = model_labels[0]
                model_label = st.selectbox(
                    "대표 차종",
                    model_labels,
                    key="compare_lookup_model",
                )
                model_row = models.loc[models["model_name"] == model_label].iloc[0]
                model_id = int(model_row["model_id"])
        year_options: list[str | int] = ["전체 연식"]
        if lookup_ready:
            model_years = read_query(YEARS_SQL, {"model_id": model_id})["model_year"].tolist()
            year_options = ["전체 연식"] + [int(year) for year in model_years]
        with year_col:
            if st.session_state.get("compare_lookup_year") not in year_options:
                st.session_state.compare_lookup_year = year_options[0]
            year = st.selectbox(
                "모델 연도",
                year_options,
                key="compare_lookup_year",
            )
        with button_col:
            if st.button(
                "조회",
                type="primary",
                width="stretch",
                key="compare_lookup_button",
                disabled=not lookup_ready,
            ):
                st.session_state.compare_preview = {
                    "manufacturer": manufacturer,
                    "model_id": model_id,
                    "model_name": model_label,
                    "year": year,
                }
                st.rerun()

    if st.session_state.get("compare_preview") and not st.session_state.get("public_ad_open"):
        render_compare_preview_dialog()

    st.markdown(
        "<div class='notice'>모델연도는 소유자 신고 건수에 적용됩니다. "
        "공식 리콜은 생산기간 기준이라 선택한 모델연도로 억지로 나누지 않고 차종 전체 리콜을 보여줍니다.</div>",
        unsafe_allow_html=True,
    )
    if len(saved) < 2:
        st.info("비교하려면 관심 차량을 2대 이상 등록해 주세요.")
        return

    comparison_rows: list[dict[str, object]] = []
    for car in saved:
        model_id = int(car["model_id"])
        metrics = get_summary_metrics(model_id, car["year"])
        if metrics is None:
            continue
        year_label, complaint_count, recall_count, affected_sum = metrics
        year_text = "전체" if car["year"] == "전체 연식" else f"{car['year']}년형"
        comparison_rows.append(
            {
                "model_id": model_id,
                "display_name": f"{car['manufacturer']} · {car['model_name']} ({year_text})",
                "manufacturer_name": car["manufacturer"],
                "model_name": car["model_name"],
                "model_year": year_text,
                "complaint_count": complaint_count,
                "recall_record_count": recall_count,
                "affected_count_sum": affected_sum,
            }
        )

    comparison = pd.DataFrame(comparison_rows)
    if comparison.empty:
        st.warning("선택한 조건으로 비교할 데이터를 찾지 못했습니다.")
        return

    chart_data = comparison.melt(
        id_vars=["display_name", "model_name"],
        value_vars=["complaint_count", "recall_record_count"],
        var_name="지표",
        value_name="건수",
    )
    chart_data["지표"] = chart_data["지표"].map({"complaint_count": "소유자 신고", "recall_record_count": "공식 리콜 기록"})
    chart_data["chart_label"] = chart_data["model_name"].map(
        lambda value: value if len(str(value)) <= 14 else f"{str(value)[:13]}…"
    )
    chart = px.bar(
        chart_data,
        x="chart_label",
        y="건수",
        color="지표",
        barmode="group",
        hover_name="display_name",
        labels={"chart_label": "선택 차량", "건수": "건수", "지표": ""},
        color_discrete_map={"소유자 신고": "#245ccb", "공식 리콜 기록": "#e98666"},
    )
    chart.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=20, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        bargap=0.35,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    chart.update_xaxes(
        type="category",
        tickangle=0,
        automargin=True,
        tickfont=dict(size=11),
    )
    chart.update_yaxes(rangemode="tozero", tickformat=",d")
    chart.update_traces(width=0.32)

    used_names: set[str] = set()
    transposed_columns: dict[str, list[str]] = {}
    for _, row in comparison.iterrows():
        column_name = str(row["model_name"])
        if column_name in used_names:
            column_name = f"{row['manufacturer_name']} {row['model_name']}"
        suffix = 2
        unique_name = column_name
        while unique_name in used_names:
            unique_name = f"{column_name} {suffix}"
            suffix += 1
        used_names.add(unique_name)
        transposed_columns[unique_name] = [
            str(row["manufacturer_name"]),
            str(row["model_name"]),
            str(row["model_year"]),
            format_number(row["complaint_count"]),
            f"{format_number(row['recall_record_count'])}건",
            f"{format_number(row['affected_count_sum'])}대",
        ]
    comparison_table = pd.DataFrame(
        transposed_columns,
        index=["제조사", "대표 차종", "모델연도", "소유자 신고수", "공식 리콜 기록", "리콜 대상 대수 합계"],
    ).rename_axis("항목").reset_index()

    st.markdown(
        "<div class='comparison-report-intro'>"
        "동일한 기준으로 수치를 비교합니다. 소유자 신고 건수는 결함 확정이나 판매량을 반영한 비율이 아닙니다."
        "</div>",
        unsafe_allow_html=True,
    )
    table_col, chart_col = st.columns([1.08, 0.92], gap="medium")
    with table_col:
        with st.container(border=True, key="compare-table-report"):
            st.markdown(
                report_heading_html(
                    "비교 안전 요약",
                    "선택한 차량의 신고·리콜 정보를 같은 기준으로 비교합니다.",
                    "report",
                ),
                unsafe_allow_html=True,
            )
            st.markdown(
                report_table_html(comparison_table, "comparison-report-table"),
                unsafe_allow_html=True,
            )

    with chart_col:
        with st.container(border=True, key="compare-chart-report"):
            st.markdown(
                report_heading_html(
                    "신고·리콜 비교 그래프",
                    "차종별 신고 기록과 공식 리콜 기록의 건수를 함께 확인합니다.",
                    "report",
                    tone="coral",
                ),
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div class='report-notice'><span class='report-notice-icon'>!</span><span>"
                "두 지표는 성격이 다릅니다. 신고 건수만으로 특정 차량의 결함이나 리콜 여부를 판단하지 마세요."
                "</span></div>",
                unsafe_allow_html=True,
            )
            st.plotly_chart(chart, width="stretch", config={"displayModeBar": False})


def render_help() -> None:
    """데이터 기준과 FAQ를 설명한다."""
    st.markdown("## 도움말 · 데이터 안내")
    st.markdown("### 자주 묻는 질문")
    with st.expander("리콜 대상 차량이면 무조건 수리받을 수 있나요?", expanded=True):
        st.write("공식 리콜 대상이라면 제작사가 안내한 방법에 따라 조치받을 수 있습니다. 다만 이 서비스는 차종·생산기간 기준 정보이므로, 실제 차량의 대상 여부와 조치 완료 여부는 차량번호나 차대번호로 자동차리콜센터에서 다시 확인해야 합니다.")
        st.link_button("자동차리콜센터에서 확인", GOVERNMENT_RECALL_URL, width="stretch")
    with st.expander("리콜 조치가 완료됐는지 어떻게 확인하나요?"):
        st.write("자동차리콜센터에서 차량번호 또는 차대번호를 입력해 확인하세요. 개별 차량의 리콜 조치 여부는 제작사가 국토교통부에 보고한 진행 내역을 기준으로 제공됩니다.")
        st.link_button("리콜 대상·조치 여부 조회", "https://www.car.go.kr/ri/recall/list.do", width="stretch")
    with st.expander("소비자 신고가 많으면 결함이 확정된 건가요?"):
        st.write("아닙니다. 신고 건수는 소유자가 접수한 기록의 수일 뿐, 결함 확정이나 리콜 결정을 의미하지 않습니다. 같은 차종에서 신고가 반복되는지 확인하는 구매 전 참고 신호로 활용하세요.")
    with st.expander("중고차 판매자에게 어떤 서류를 받아야 하나요?"):
        st.write("자동차성능·상태점검기록부를 받아 실제 차량 상태와 비교해야 합니다. 자동차매매업자는 점검 내용을 기재한 기록부를 매수인에게 발급해야 하므로, 계약 전에 기록부와 특약사항을 함께 확인하세요.")
        st.link_button("관련 법령 확인", "https://www.law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joBrNo=00&joNo=0120&lsiSeq=285101&urlMode=lsScJoRltInfoR", width="stretch")
    with st.expander("구매 후 신고된 결함이 발견되면 어떻게 하나요?"):
        st.write("차량 사진, 정비내역, 판매자와 주고받은 문자, 계약서, 성능·상태점검기록부를 보관하고 판매자에게 먼저 서면으로 알리세요. 해결되지 않으면 1372 소비자상담센터에 상담을 신청할 수 있습니다.")
        st.link_button("1372 소비자상담 절차", "https://www.kca.go.kr/odr/pg/ma/cnsutInfo.do", width="stretch")
    with st.expander("소비자도 자동차 결함을 직접 신고할 수 있나요?"):
        st.write("가능합니다. 자동차리콜센터에서 결함 신고를 접수할 수 있습니다. 다만 리콜센터는 결함 정보를 수집·분석하는 기관이므로, 개인 간 판매 분쟁을 직접 해결하거나 중재하는 곳은 아닙니다.")
        st.link_button("자동차 결함신고 안내", "https://www.car.go.kr/ds/dfct/gdnc.do", width="stretch")
    st.markdown("### 공식 사이트 바로가기")
    st.markdown(
        "리콜 대상 여부와 개별 차량의 조치 완료 여부는 아래 공식 사이트에서 다시 확인할 수 있습니다.",
    )
    st.link_button("정부 자동차리콜센터 리콜 현황", GOVERNMENT_RECALL_URL, width="stretch")
    st.markdown("<div class='source-note'>데이터 출처: 한국교통안전공단 자동차리콜센터 제공 자료를 전처리한 프로젝트 DB</div>", unsafe_allow_html=True)


# 앱을 새로 열었을 때만 공익광고를 표시합니다.
# 우측 상단 X를 누르면 현재 세션에서는 닫힌 상태로 유지됩니다.
# "오늘 하루동안 보지않기"를 선택한 뒤 닫으면 자정까지 다시 보이지 않습니다.
if st.session_state.get("persist_hide_public_ad"):
    persist_hide_public_ad_today()
if st.session_state.get("public_ad_open", True):
    render_public_service_ad()

render_site_header()
render_hero()
with st.container(key="header-interest", horizontal=True, horizontal_alignment="right"):
    render_interest_summary()
recall_tab, compare_tab, help_tab = st.tabs([
    ":material/search: 차량 조회",
    ":material/compare_arrows: 차종 비교",
    ":material/help: 도움말",
])

with recall_tab:
    render_recall_search()
    render_dashboard()

with compare_tab:
    render_compare()

with help_tab:
    render_help()


