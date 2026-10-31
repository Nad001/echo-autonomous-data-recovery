from __future__ import annotations

import json
import csv
import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import streamlit as st

from echo.db.connections import analytics_conn, echo_conn, execution_archive_path, finance_conn
from echo.compare import field_mismatches
from echo.config import (
    LLM_MODE,
    MAX_ESTIMATED_USD,
    MAX_SECONDS,
    MAX_TOOL_CALLS,
    MIN_INVESTIGATION_CONFIDENCE,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    PACKAGE_DIR,
)
from echo.ingest.scenarios import load_case
from echo.ui.workflow import can_start_execution, validate_execution_target
from echo.worker.main import process_one


st.set_page_config(page_title="ECHO · Incident Control Center", page_icon="◈", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
:root { --navy:#08111f; --panel:#101d2e; --line:#263b52; --text:#f2f7fb; --muted:#a9bacb; --mint:#72e0c0; --teal:#35b9b0; --red:#ff7f83; --amber:#f4c86b; }
.stApp { background:var(--navy); color:var(--text); font-family:'DM Sans', sans-serif; }
[data-testid="stHeader"] { background:transparent; }
[data-testid="stSidebar"] { background:#0c1828; border-right:1px solid var(--line); }
[data-testid="stSidebar"] * { color:var(--text); }
h1,h2,h3,h4 { font-family:'Space Grotesk', sans-serif; color:var(--text)!important; letter-spacing:-.02em; }
h1 { font-size:2.35rem!important; margin-bottom:.15rem!important; }
h2 { font-size:1.35rem!important; margin-top:1.5rem!important; }
h3 { font-size:1.02rem!important; }
p, label, .stCaption { color:var(--muted); }
.subtitle { color:var(--muted); font-size:1.03rem; margin-bottom:1.3rem; }
.eyebrow { color:var(--mint); text-transform:uppercase; letter-spacing:.13em; font-size:.72rem; font-weight:700; }
.hero { background:linear-gradient(120deg,#10243a 0%,#102034 58%,#12313a 100%); border:1px solid #2b5260; border-radius:16px; padding:24px 26px; margin:10px 0 20px; }
.hero-title { color:#f5fffc; font-family:'Space Grotesk'; font-size:1.62rem; font-weight:700; margin:5px 0 8px; }
.hero-copy { color:#c9d9e5; line-height:1.55; max-width:900px; }
.metric { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px 17px; min-height:92px; }
.metric-label { color:var(--muted); font-size:.78rem; text-transform:uppercase; letter-spacing:.08em; font-weight:600; }
.metric-value { color:var(--text); font-family:'Space Grotesk'; font-size:1.72rem; font-weight:700; margin-top:5px; }
.metric-note { color:#7e95aa; font-size:.76rem; margin-top:2px; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:17px 19px; height:100%; }
.card-title { color:var(--muted); font-size:.77rem; text-transform:uppercase; letter-spacing:.1em; font-weight:700; margin-bottom:9px; }
.answer { color:var(--text); font-size:1.04rem; line-height:1.5; }
.muted { color:var(--muted); }
.pill { display:inline-block; border-radius:99px; padding:4px 10px; font-size:.74rem; font-weight:700; letter-spacing:.02em; }
.pill-green { color:#09241e; background:var(--mint); }.pill-red { color:#351217; background:var(--red); }.pill-amber { color:#352710; background:var(--amber); }.pill-blue { color:#d5efff; background:#245477; }
.section-rule { height:1px; background:var(--line); margin:24px 0 12px; }
.timeline { border-left:2px solid #31516a; margin:10px 0 10px 9px; padding-left:20px; }
.timeline-item { position:relative; padding:0 0 18px; }
.timeline-item:before { content:''; position:absolute; width:9px; height:9px; background:var(--mint); border:3px solid var(--navy); border-radius:50%; left:-26px; top:4px; box-shadow:0 0 0 1px var(--mint); }
.timeline-kind { color:var(--mint); font-size:.76rem; font-weight:700; text-transform:uppercase; letter-spacing:.06em; }
.timeline-summary { color:var(--text); margin:3px 0; }.timeline-time { color:#7e95aa; font-size:.74rem; }
.stTabs [data-baseweb="tab-list"] { gap:8px; border-bottom:1px solid var(--line); }
.stTabs [data-baseweb="tab"] { color:#b5c8d8; padding:10px 15px; font-weight:600; }
.stTabs [aria-selected="true"] { color:var(--mint)!important; border-bottom-color:var(--mint)!important; }
[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:8px; }
div[data-testid="stExpander"] { border:1px solid var(--line); border-radius:9px; background:#0d1928; }
</style>
""",
    unsafe_allow_html=True,
)

# Final blue-only product layer. This deliberately overrides the earlier
# presentation tokens so every page shares one coherent visual system.
st.markdown(
    """
<style>
:root { --paper:#ffffff; --surface:#ffffff; --ink:#0b1f3a; --subtle:#5f7188; --border:#dce6f2; --lime:#2f6fda; --lime-dark:#174ea6; --soft-lime:#eaf2ff; --danger:#cf554f; --warning:#b57b19; --navy:#0b1f3a; }
.stApp { background:var(--paper); color:var(--ink); font-family:'Manrope','DM Sans',sans-serif; }
[data-testid="stSidebar"] { background:#edf4fc; border-right:1px solid #d5e2f1; }
[data-testid="stSidebar"] * { color:var(--ink); }
h1,h2,h3,h4,.brand-mark { color:var(--ink)!important; font-family:'Space Grotesk','Manrope',sans-serif; }
.eyebrow,.stage-kicker,.timeline-kind { color:#2361b6; }
.hero,.home-hero { background:linear-gradient(135deg,#eaf3ff 0%,#fff 60%,#f4f8fd 100%); border-color:#cddff2; }
.metric,.card,.node,.stage-panel,.action-card,.history-row,.approval-card,.table-wrap { background:#fff; border-color:var(--border); box-shadow:0 10px 28px rgba(23,62,112,.06); }
.history-summary { margin:18px 0 22px; }
.history-table-wrap { width:100%; overflow-x:auto; border:1px solid #dce6f2; border-radius:14px; background:#fff; box-shadow:0 10px 28px rgba(23,62,112,.06); }
.history-table { width:100%; min-width:980px; border-collapse:separate; border-spacing:0; color:#0b1f3a; font-size:.82rem; }
.history-table th { padding:14px 15px; background:#f4f8fd; border-bottom:1px solid #dce6f2; color:#61748b; font-size:.69rem; font-weight:800; letter-spacing:.07em; text-align:left; text-transform:uppercase; white-space:nowrap; }
.history-table td { padding:16px 15px; border-bottom:1px solid #edf2f7; vertical-align:middle; white-space:nowrap; }
.history-table tbody tr { transition:background .15s ease; }
.history-table tbody tr:hover { background:#f7faff; }
.history-table tbody tr:last-child td { border-bottom:0; }
.history-date { color:#516a86; font-variant-numeric:tabular-nums; }
.history-id { color:#174ea6; font-weight:800; }
.history-incident { display:block; margin-top:3px; color:#7a8da3; font-size:.7rem; font-weight:600; }
.history-title { max-width:330px; overflow:hidden; color:#193556; text-overflow:ellipsis; }
.history-view { color:#2361b6; font-weight:800; }
.history-badge { display:inline-flex; align-items:center; gap:5px; padding:6px 9px; border:1px solid transparent; border-radius:7px; font-size:.71rem; font-weight:800; line-height:1; white-space:nowrap; }
.history-badge-icon { display:inline-flex; align-items:center; justify-content:center; width:13px; height:13px; font-size:.72rem; font-weight:900; }
.history-badge-healthy,.history-badge-verified { color:#174ea6; background:#eaf2ff; border-color:#c4d9f5; }
.history-badge-failed { color:#963e3a; background:#fae6e3; border-color:#efc1ba; }
.history-badge-review { color:#805b16; background:#fff1ca; border-color:#efdca4; }
.history-badge-neutral { color:#62748a; background:#f1f4f7; border-color:#dce3eb; }
.history-detail-header { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; padding:4px 0 14px; border-bottom:1px solid #edf2f7; }
.history-detail-header h3 { margin:5px 0 3px!important; }
.history-detail-header p { margin:0; color:#71849a; font-size:.8rem; }
.history-detail-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:16px 0; padding:14px; border:1px solid #e5edf6; border-radius:10px; background:#f8fbff; color:#526b86; font-size:.8rem; line-height:1.5; }
.history-detail-grid b { display:block; color:#6d8095; font-size:.68rem; letter-spacing:.06em; text-transform:uppercase; }
.st-key-workflow_featured_SCENARIO-01 button,.st-key-workflow_featured_SCENARIO-02 button,.st-key-workflow_featured_SCENARIO-05 button { min-height:58px!important; padding:9px 7px!important; border:1px solid #d5e2f1!important; border-radius:10px!important; background:#f7faff!important; color:#174ea6!important; font-size:.72rem!important; font-weight:800!important; line-height:1.2!important; box-shadow:none!important; }
.st-key-workflow_featured_SCENARIO-01 button:hover,.st-key-workflow_featured_SCENARIO-02 button:hover,.st-key-workflow_featured_SCENARIO-05 button:hover { border-color:#8db2e3!important; background:#eaf2ff!important; }
.st-key-workflow_featured_SCENARIO-01 button,.st-key-workflow_featured_SCENARIO-02 button,.st-key-workflow_featured_SCENARIO-05 button,.st-key-scenario_featured_SCENARIO-01 button,.st-key-scenario_featured_SCENARIO-02 button,.st-key-scenario_featured_SCENARIO-05 button { min-height:142px!important; height:142px!important; white-space:pre-line!important; font-size:.88rem!important; line-height:1.35!important; text-align:left!important; padding:15px 16px!important; }
.st-key-workflow_featured_SCENARIO-01 button[kind="primary"],.st-key-workflow_featured_SCENARIO-02 button[kind="primary"],.st-key-workflow_featured_SCENARIO-05 button[kind="primary"],.st-key-scenario_featured_SCENARIO-01 button[kind="primary"],.st-key-scenario_featured_SCENARIO-02 button[kind="primary"],.st-key-scenario_featured_SCENARIO-05 button[kind="primary"] { background:#eaf2ff!important; color:#174ea6!important; border:2px solid #2f6fda!important; box-shadow:0 8px 20px rgba(47,111,218,.14)!important; }
.metric-label,.card-title { color:#61748b; }
.metric-value,.answer,.node-name,.node-stat,.result-title,.example-value { color:var(--ink); }
.muted,.metric-note,.node-note,.story-intro,.stage-copy,.subtitle,p,label,.stCaption { color:var(--subtle); }
.pill-green { color:#174ea6; background:#e7f0ff; border-color:#c4d9f5; }
.pill-blue { color:#174ea6; background:#eaf2ff; border-color:#c4d9f5; }
.pill-red { color:#8f3834; background:#fae6e3; }
.pill-amber { color:#805b16; background:#fff1ca; }
.section-rule { background:#dce6f2; }
.timeline { border-left-color:#b9d1ed; }.timeline-item:before { background:#4d86df; border-color:var(--paper); box-shadow:0 0 0 1px #2361b6; }
.walk-line { background:#dce6f2; }.walk-line.done { background:#6d9fe3; }.walk-step.done,.walk-step.active { color:#174ea6; }
.node-icon { background:#eaf2ff; color:#2361b6; }.node.alerted { border-color:#e8b2ad; }.node.recovered { border-color:#bcd3f1; }
.transfer { color:#2361b6; }.transfer-arrow { color:#2361b6; }
.check { background:#eaf2ff; color:#174ea6; }.check.bad { background:#fae6e3; color:#8f3834; }
.replay-badge { color:#365b87; background:#edf4fc; border-color:#cddff2; }
.id-list { color:#496988; background:#f3f7fc; border-color:#dce6f2; }
.root-cause { border-color:#c4d9f5; background:linear-gradient(135deg,#eaf3ff 0%,#fff 72%); }.root-cause .card-title { color:#2361b6; }
.investigation-field { margin:10px 0 0; }.investigation-field-label { color:#61748b; font-size:.68rem; font-weight:800; letter-spacing:.08em; text-transform:uppercase; margin-bottom:3px; }.investigation-clamp { overflow:hidden; display:-webkit-box; -webkit-box-orient:vertical; color:#193556; line-height:1.45; }.investigation-title-clamp { -webkit-line-clamp:1; font-size:1.08rem; font-weight:800; }.investigation-summary-clamp { -webkit-line-clamp:2; }.investigation-cause-clamp { -webkit-line-clamp:3; }.investigation-next-clamp { -webkit-line-clamp:2; }.investigation-review-clamp { -webkit-line-clamp:2; }.confidence-badge { display:inline-flex; align-items:center; width:max-content; padding:6px 9px; border:1px solid #c4d9f5; border-radius:999px; background:#eaf2ff; color:#174ea6; font-size:.72rem; font-weight:800; }.compact-summary .confidence-badge { flex-direction:row; gap:0; }
.investigation-card { background:#fff; border:1px solid #c4d9f5; border-radius:16px; padding:20px 22px; box-shadow:0 10px 28px rgba(23,62,112,.06); }.investigation-card-top { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:4px; }.investigation-mode { color:#61748b; font-size:.72rem; font-weight:800; letter-spacing:.07em; text-transform:uppercase; }.investigation-decision { margin-top:14px; padding:10px 12px; border-radius:10px; background:#f4f8fd; color:#365b87; font-size:.82rem; line-height:1.4; }.investigation-decision.review { background:#fff6df; color:#805b16; }.investigation-decision.blocked { background:#fae6e3; color:#8f3834; }
.assistant-card { padding:20px 22px; }.assistant-header { display:flex; align-items:center; gap:11px; }.assistant-icon { display:inline-flex; align-items:center; justify-content:center; width:34px; height:34px; border-radius:10px; background:#eaf2ff; color:#2361b6; font-family:'Material Symbols Rounded'; font-size:20px; }.assistant-name { color:#102c52; font-size:1.05rem; font-weight:800; line-height:1.1; }.assistant-mode { margin-top:3px; color:#71849a; font-size:.76rem; }.assistant-header .confidence-badge { margin-left:auto; }.assistant-rule { height:1px; margin:16px 0 4px; background:#e7eef7; }.assistant-field { display:grid; grid-template-columns:22px minmax(0,1fr); gap:9px; margin-top:14px; }.assistant-field-icon { color:#2361b6; font-family:'Material Symbols Rounded'; font-size:19px; line-height:1.4; }.assistant-field-label { color:#102c52; font-size:.91rem; font-weight:800; line-height:1.35; }.assistant-field-copy { margin-top:3px; color:#385574; font-size:.9rem; line-height:1.45; }.assistant-field-copy.investigation-summary-clamp { -webkit-line-clamp:2; }.assistant-field-copy.investigation-cause-clamp { -webkit-line-clamp:2; }.assistant-field-copy.investigation-next-clamp { -webkit-line-clamp:2; }.assistant-review-note { margin:14px 0 0 31px; padding:9px 11px; border-radius:9px; background:#fff6df; color:#805b16; font-size:.8rem; line-height:1.4; }
.assistant-list { margin:4px 0 0; padding-left:18px; color:#385574; font-size:.9rem; line-height:1.45; }.assistant-list li { margin:2px 0; }.assistant-list strong { color:#102c52; }
.pattern-chip { color:#174ea6; background:#e7f0ff; border-color:#c4d9f5; }
.example { background:#fff8e8; border-color:#efda9e; }.example-label { color:#906817; }
.coverage { background:#e7edf5; }.coverage-a { background:#2f6fda; }.coverage-b { background:#78a9e8; }.coverage-c { background:#b8d2f2; }
.workflow-chip.active { color:#174ea6; border-color:#9abbe8; background:#eaf2ff; }
.result-banner { border-color:#bcd3f1; background:linear-gradient(120deg,#eaf3ff,#fff); }.result-banner.bad { border-color:#efc1ba; background:#fff5f3; }
.result-banner.success { border-color:#b9dfc7; background:linear-gradient(120deg,#effbf3,#fff); }.result-banner.success .result-title { color:#187342; }
.recovery-compare { display:grid; grid-template-columns:1fr 54px 1fr; gap:12px; align-items:center; margin:14px 0 18px; }.recovery-value { border:1px solid #dce6f2; border-radius:12px; padding:13px 15px; background:#fff; }.recovery-value .label { color:#61748b; font-size:.68rem; font-weight:800; letter-spacing:.07em; text-transform:uppercase; }.recovery-value .value { margin-top:5px; color:#193556; font-size:1.05rem; font-weight:800; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.recovery-value.incorrect { border-color:#efc1ba; background:#fff7f5; }.recovery-value.incorrect .value { color:#963e3a; }.recovery-value.verified { border-color:#b9dfc7; background:#f3fcf5; }.recovery-value.verified .value { color:#187342; }.recovery-arrow { color:#2361b6; font-size:1.5rem; text-align:center; font-weight:800; }
.sync-progress { margin:16px 0 18px; padding:14px 16px; border:1px solid #dce6f2; border-radius:12px; background:#f8fbff; }.sync-progress-head { display:flex; justify-content:space-between; gap:12px; color:#193556; font-size:.82rem; font-weight:800; }.sync-progress-note { margin-top:4px; color:#61748b; font-size:.78rem; }
.execution-status-card { max-width:680px; margin:34px auto; padding:24px 26px; border:1px solid #cddff2; border-radius:16px; background:#fff; box-shadow:0 12px 30px rgba(23,62,112,.07); }.execution-status-card h2 { margin:0 0 6px!important; }.execution-status-card p { margin:0 0 16px; color:#61748b; }.execution-stage { display:flex; align-items:center; gap:10px; padding:9px 0; color:#61748b; font-size:.84rem; border-top:1px solid #edf2f7; }.execution-stage:first-of-type { border-top:0; }.execution-stage.active { color:#174ea6; font-weight:800; }.execution-stage.done { color:#187342; }.execution-stage.failed { color:#963e3a; }.execution-stage-dot { width:9px; height:9px; border-radius:50%; background:#cdd8e5; }.execution-stage.active .execution-stage-dot { background:#2f6fda; box-shadow:0 0 0 4px #eaf2ff; }.execution-stage.done .execution-stage-dot { background:#2b9a5b; }.execution-stage.failed .execution-stage-dot { background:#cf554f; }
.state-dot { background:#2f6fda; }.state-dot.bad { background:var(--danger); }
.approval-card { border-left-color:var(--warning); }.unavailable { background:#f3f6fa; border-color:#d5e2f1; }
.compare-table th { background:#f1f5fa; color:#60748b; }.compare-table td { border-color:#dce6f2; }.compare-table .good-cell { background:#eaf2ff; color:#174ea6; }
[data-testid="stMainBlockContainer"] button[kind="primary"] { background:linear-gradient(135deg,#071a34 0%,#123f83 58%,#1f66c8 100%); color:#f8fbff!important; border:1px solid #2f7be1; }.creator-credit { color:#94a4b7!important; }
[data-testid="stToolbar"], #MainMenu, footer { visibility:hidden; height:0; }
</style>
""",
    unsafe_allow_html=True,
)

# Premium light presentation layer. The visual language is inspired by modern
# AI product sites such as HUMAIN, without using its branding or assets.
st.markdown(
    """
<style>
:root { --paper:#f7f8f3; --surface:#ffffff; --ink:#14231f; --subtle:#65736d; --border:#e1e8df; --lime:#b7df4f; --lime-dark:#719d25; --soft-lime:#edf6d3; --danger:#d75d51; --warning:#b78019; }
.stApp { background:var(--paper); color:var(--ink); }
[data-testid="stHeader"] { background:rgba(247,248,243,.88); }
[data-testid="stSidebar"] { background:#f0f4ed; border-right:1px solid var(--border); }
[data-testid="stSidebar"] * { color:var(--ink); }
h1,h2,h3,h4 { color:var(--ink)!important; }
h1 { font-size:2.8rem!important; font-weight:700!important; }
h2 { font-size:1.35rem!important; }
p, label, .stCaption { color:var(--subtle); }
.subtitle { color:var(--subtle); max-width:730px; }
.eyebrow { color:var(--lime-dark); }
.hero { background:var(--surface); border:1px solid var(--border); box-shadow:0 14px 35px rgba(30,52,39,.07); }
.hero-title { color:var(--ink); }
.hero-copy { color:var(--subtle); }
.metric,.card { background:var(--surface); border-color:var(--border); box-shadow:0 8px 24px rgba(30,52,39,.045); }
.metric-label,.card-title { color:var(--subtle); }
.metric-value,.answer { color:var(--ink); }
.metric-note,.muted { color:#82908a; }
.pill-green { color:#36520e; background:var(--soft-lime); border:1px solid #d3e8a1; }.pill-red { color:#84372e; background:#fae5e1; }.pill-amber { color:#77540e; background:#fff0c8; }.pill-blue { color:#315c51; background:#e4f1ec; }
.section-rule { background:var(--border); }
.timeline { border-left-color:#c9dbb2; }.timeline-item:before { background:var(--lime); border-color:var(--paper); box-shadow:0 0 0 1px var(--lime-dark); }.timeline-kind { color:var(--lime-dark); }.timeline-summary { color:var(--ink); }.timeline-time { color:#82908a; }
[data-testid="stDataFrame"] { border-color:var(--border); }
div[data-testid="stExpander"] { border-color:var(--border); background:var(--surface); }
.walk-nav { display:flex; justify-content:space-between; align-items:center; gap:10px; margin:20px 0 14px; }
.walk-step { flex:1; text-align:center; font-size:.78rem; color:#8a9891; font-weight:700; }
.walk-step.active { color:var(--ink); }.walk-step.done { color:var(--lime-dark); }
.walk-line { height:3px; background:var(--border); flex:1; border-radius:9px; }.walk-line.done { background:var(--lime); }
.flow { display:grid; grid-template-columns:1fr 110px 1fr; gap:18px; align-items:center; margin:22px 0; }
.node { background:var(--surface); border:1px solid var(--border); border-radius:20px; padding:24px; min-height:205px; box-shadow:0 12px 30px rgba(30,52,39,.06); position:relative; overflow:hidden; }
.node.alerted { border-color:#e9b4a8; box-shadow:0 12px 30px rgba(180,79,61,.10); }.node.recovered { border-color:#cfe59b; }
.node-top { display:flex; justify-content:space-between; align-items:start; }.node-icon { width:52px; height:52px; border-radius:16px; display:grid; place-items:center; background:var(--soft-lime); color:var(--lime-dark); font-size:25px; font-weight:700; }.lucide { width:27px; height:27px; }
.node-label { color:var(--subtle); font-size:.76rem; text-transform:uppercase; letter-spacing:.1em; font-weight:700; margin-top:16px; }.node-name { color:var(--ink); font-size:1.3rem; font-weight:700; margin:3px 0; }.node-note { color:var(--subtle); font-size:.88rem; }
.node-stat { color:var(--ink); font-size:1.55rem; font-weight:700; margin-top:22px; }.node-stat small { color:var(--subtle); font-size:.78rem; font-weight:500; }
.transfer { text-align:center; color:var(--lime-dark); font-weight:700; }.transfer-arrow { font-size:2.4rem; line-height:1; animation:soft-pulse 2.4s ease-in-out infinite; }.transfer-label { font-size:.72rem; color:var(--subtle); margin-top:7px; }
@keyframes soft-pulse { 0%,100% { transform:translateX(-3px); opacity:.65 } 50% { transform:translateX(5px); opacity:1 } }
.stage-panel { background:var(--surface); border:1px solid var(--border); border-radius:18px; padding:22px 24px; box-shadow:0 10px 28px rgba(30,52,39,.05); }
.stage-kicker { color:var(--lime-dark); font-size:.76rem; text-transform:uppercase; letter-spacing:.11em; font-weight:700; }.stage-title { color:var(--ink); font-size:1.55rem; font-weight:700; margin:4px 0 6px; }.stage-copy { color:var(--subtle); line-height:1.55; }
.example { background:#fff9e9; border:1px solid #f0dfae; border-radius:14px; padding:17px 19px; }.example-label { color:#9b711b; text-transform:uppercase; font-size:.72rem; font-weight:700; letter-spacing:.1em; }.example-value { color:var(--ink); font-size:1.15rem; font-weight:700; margin-top:5px; }
.check { background:var(--soft-lime); border-radius:12px; padding:13px 15px; color:#405a21; }.check.bad { background:#fae5e1; color:#84372e; }
.replay-badge { display:inline-flex; align-items:center; gap:7px; color:#52645b; background:#eef3ec; border:1px solid var(--border); border-radius:999px; padding:7px 12px; font-size:.76rem; font-weight:700; }
.id-list { color:#53645c; background:#f3f6f1; border:1px solid var(--border); border-radius:12px; padding:12px 14px; font-size:.78rem; line-height:1.7; word-break:break-word; }
.nav-note { color:var(--subtle); text-align:center; font-size:.8rem; padding-top:9px; }
.story-section { opacity:0; animation:story-reveal .7s cubic-bezier(.2,.75,.25,1) forwards; animation-delay:var(--delay,0s); scroll-margin-top:30px; }
.story-heading { display:flex; align-items:center; gap:12px; margin:26px 0 8px; }.story-number { display:grid; place-items:center; width:30px; height:30px; border-radius:50%; background:var(--ink); color:#fff; font-size:.78rem; font-weight:700; }.story-heading h2 { margin:0!important; }
.story-intro { color:var(--subtle); max-width:760px; line-height:1.55; margin-bottom:14px; }
.story-actions { display:flex; gap:10px; align-items:center; }
.table-wrap { background:var(--surface); border:1px solid var(--border); border-radius:16px; overflow:hidden; box-shadow:0 8px 24px rgba(30,52,39,.04); }
.compare-table { width:100%; border-collapse:collapse; color:var(--ink); font-size:.88rem; }.compare-table th { text-align:left; color:var(--subtle); font-size:.7rem; text-transform:uppercase; letter-spacing:.08em; padding:13px 15px; background:#f5f7f2; }.compare-table td { padding:13px 15px; border-top:1px solid var(--border); }.compare-table .bad-cell { background:#fff0ed; color:#a83f34; font-weight:700; }.compare-table .good-cell { background:#eff8dc; color:#4d7218; font-weight:700; }
.result-banner { border-radius:18px; padding:24px; border:1px solid #cde3a1; background:linear-gradient(120deg,#f1f8df,#fff); }.result-banner.bad { border-color:#efc1b9; background:#fff5f2; }.result-title { color:var(--ink); font-size:1.45rem; font-weight:700; margin-bottom:5px; }.result-copy { color:var(--subtle); line-height:1.55; }
.creator-credit { color:#9ba8a2!important; font-size:.72rem!important; margin-top:80px; text-align:center; }
.page-shell { max-width:1180px; margin:0 auto; }
.topbar { display:flex; justify-content:space-between; align-items:center; gap:20px; padding:8px 0 20px; }
.brand-mark { color:var(--ink); font-family:'Space Grotesk'; font-size:1.55rem; font-weight:700; letter-spacing:.14em; }
.brand-tag { color:var(--subtle); font-size:.84rem; }
.section-lead { max-width:760px; margin-bottom:18px; }
.section-lead h2 { margin-bottom:5px!important; }
.action-card { background:linear-gradient(135deg,#fbfff3,#fff); border:1px solid #dcebbd; border-radius:18px; padding:19px 21px; box-shadow:0 10px 28px rgba(30,52,39,.045); }
.action-card strong { color:var(--ink); }
.state-dot { display:inline-block; width:9px; height:9px; border-radius:50%; background:var(--lime-dark); margin-right:7px; }
.state-dot.bad { background:var(--danger); }
.root-cause { border:1px solid #d5e8ad; border-radius:18px; background:linear-gradient(135deg,#f2f9df 0%,#fff 72%); padding:22px; box-shadow:0 10px 28px rgba(30,52,39,.05); }
.root-cause .card-title { color:var(--lime-dark); }
.evidence-list { margin:10px 0 0; padding-left:18px; color:var(--subtle); line-height:1.7; }
.pattern-chip { display:inline-block; margin-top:12px; padding:7px 11px; border-radius:999px; color:#48671a; background:#e9f5c9; border:1px solid #d4e9a5; font-size:.78rem; font-weight:700; }
.filter-row { background:var(--surface); border:1px solid var(--border); border-radius:16px; padding:13px 15px; margin:12px 0 18px; }
.status-line { display:flex; align-items:center; gap:8px; color:var(--subtle); font-size:.82rem; }
.approval-card { background:var(--surface); border:1px solid var(--border); border-left:4px solid var(--warning); border-radius:16px; padding:19px; margin:12px 0; box-shadow:0 8px 24px rgba(30,52,39,.04); }
.approval-card .title { color:var(--ink); font-size:1.1rem; font-weight:700; }
.approval-card .copy { color:var(--subtle); margin-top:5px; line-height:1.5; }
.empty-card { background:var(--surface); border:1px dashed var(--border); border-radius:18px; padding:28px; text-align:center; color:var(--subtle); }
.home-hero { background:linear-gradient(135deg,#f2f9df 0%,#fff 55%,#edf5ee 100%); border:1px solid #dbe9c5; border-radius:26px; padding:48px 42px; box-shadow:0 18px 45px rgba(30,52,39,.08); margin:12px 0 26px; }
.home-hero h1 { font-size:3.7rem!important; letter-spacing:-.06em; margin:6px 0!important; }
.home-hero p { max-width:650px; font-size:1.08rem; line-height:1.65; }
.coverage { display:flex; height:15px; border-radius:999px; overflow:hidden; background:#edf0eb; margin:17px 0 10px; }.coverage-a { background:#b7df4f; flex:1; }.coverage-b { background:#80cdb2; flex:1; }.coverage-c { background:#f0c975; flex:1; }
.coverage-legend { display:flex; justify-content:space-between; gap:12px; color:var(--subtle); font-size:.8rem; }.coverage-legend b { color:var(--ink); }
.workflow-bar { display:flex; align-items:flex-start; gap:0; margin:18px 0 28px; padding:0 4px; }.workflow-chip { position:relative; flex:1; padding:29px 7px 0; border:0; color:#8b9aae; background:transparent; font-size:.72rem; font-weight:700; text-align:center; }.workflow-chip:before { content:''; position:absolute; top:0; left:50%; width:22px; height:22px; transform:translateX(-50%); border-radius:50%; border:2px solid #c6d3e1; background:#fff; z-index:2; box-sizing:border-box; }.workflow-chip:after { content:''; position:absolute; top:10px; left:50%; width:100%; height:3px; background:#dce6f2; z-index:1; }.workflow-chip:last-child:after { display:none; }.workflow-chip.done,.workflow-chip.active { color:#174ea6; }.workflow-chip.done:before,.workflow-chip.active:before { border-color:#2f6fda; background:#2f6fda; box-shadow:inset 0 0 0 5px #fff; }.workflow-chip.done:after { background:#2f6fda; }.workflow-chip.active { color:#0b1f3a; }
.step-heading { display:flex; align-items:center; gap:13px; margin:22px 0 18px; }.step-heading > span { display:grid; place-items:center; width:34px; height:34px; border-radius:50%; background:#eaf2ff; color:#174ea6; font-size:.78rem; font-weight:800; }.step-heading h2 { margin:0!important; font-size:1.45rem!important; }.step-heading p { margin:3px 0 0; color:#6b7e95; font-size:.86rem; }
[class*="st-key-workflow_step_"] button { min-height:40px!important; padding:7px 8px!important; border-radius:9px!important; border:1px solid #d5e2f1!important; background:#fff!important; color:#5f7188!important; font-size:.74rem!important; font-weight:700!important; box-shadow:none!important; }.st-key-workflow_step_0 button[kind="primary"],.st-key-workflow_step_1 button[kind="primary"],.st-key-workflow_step_2 button[kind="primary"],.st-key-workflow_step_3 button[kind="primary"] { background:#eaf2ff!important; border-color:#9abbe8!important; color:#174ea6!important; }
.result-focus { display:flex; align-items:baseline; justify-content:space-between; gap:18px; padding:20px 22px; border:1px solid #c4d9f5; border-radius:16px; background:linear-gradient(135deg,#edf5ff,#fff); margin-bottom:18px; }.result-focus strong { color:#0b1f3a; font-size:1.3rem; }.result-focus span { color:#5f7188; font-size:.86rem; }.compact-summary { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:16px 0; }.compact-summary span { display:flex; flex-direction:column; gap:4px; padding:12px 14px; border:1px solid #dce6f2; border-radius:11px; background:#fff; color:#365b87; font-size:.8rem; }.compact-summary b { color:#7a8da4; font-size:.66rem; letter-spacing:.08em; text-transform:uppercase; }.prominent-finding { padding:28px!important; }.prominent-finding .answer { font-size:1.35rem; font-weight:700; line-height:1.35; }.quarantine-card { margin:16px 0; border-left:4px solid #d39a32!important; }.next-step-card { border-color:#b9d1ed; background:linear-gradient(135deg,#f1f7ff,#fff); }.next-step-card p { margin:6px 0 0; color:#5f7188; font-size:.84rem; }
.unavailable { color:var(--subtle); background:#f5f6f2; border:1px dashed var(--border); border-radius:14px; padding:14px 16px; }
.metric-strip { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:16px 0; }.metric-strip .metric { min-height:70px; }
.history-row { background:var(--surface); border:1px solid var(--border); border-radius:14px; padding:16px; margin:9px 0; box-shadow:0 6px 20px rgba(30,52,39,.03); }
.history-row strong { color:var(--ink); }
.history-meta { color:var(--subtle); font-size:.82rem; margin-top:6px; }
.search-note { color:var(--subtle); font-size:.78rem; margin-top:5px; }
@keyframes story-reveal { from { opacity:0; transform:translateY(12px); } to { opacity:1; transform:translateY(0); } }
[data-testid="stToolbar"], #MainMenu, footer { visibility:hidden; height:0; }
@media (max-width: 800px) { .flow { grid-template-columns:1fr; }.transfer { transform:rotate(90deg); margin:-8px 0; }.node { min-height:170px; } }
[data-testid="stSidebarCollapseButton"], [data-testid="stSidebarNavCollapse"], [data-testid="stSidebar"] button[aria-label*="sidebar"], [data-testid="stSidebar"] button[title*="sidebar"] { visibility:visible!important; display:flex!important; z-index:1001!important; }
</style>
""",
    unsafe_allow_html=True,
)


st.markdown(
    """
<style>
:root { --paper:#f5f8fc; --surface:#ffffff; --ink:#0b1f3a; --subtle:#5f7188; --border:#dce6f2; --lime:#2f6fda; --lime-dark:#174ea6; --soft-lime:#eaf2ff; --danger:#cf554f; --warning:#b57b19; }
.stApp { background:var(--paper); color:var(--ink); font-family:'Manrope','DM Sans',sans-serif; }
[data-testid="stAppViewContainer"] { background:var(--paper); }
[data-testid="stAppViewContainer"] > .main { background:var(--paper); }
[data-testid="stMainBlockContainer"] { max-width:1080px; padding:28px 28px 52px; }
[data-testid="stHeader"] { background:#ffffff; }
[data-testid="stSidebar"] { background:#f7faff; border-right:1px solid #d5e2f1; width:224px!important; min-width:224px!important; max-width:224px!important; }
[data-testid="stSidebarContent"] { padding:18px 14px 16px!important; }
[data-testid="stSidebarUserContent"] { padding:0!important; }
[data-testid="stSidebar"] * { color:var(--ink); }
h1,h2,h3,h4,.brand-mark { color:var(--ink)!important; font-family:'Space Grotesk','Manrope',sans-serif; }
.eyebrow,.stage-kicker,.timeline-kind { color:#2361b6; }
.hero,.home-hero { background:linear-gradient(135deg,#eaf3ff 0%,#fff 60%,#f4f8fd 100%); border-color:#cddff2; }
.metric,.card,.node,.stage-panel,.action-card,.history-row,.approval-card,.table-wrap { background:#fff; border-color:var(--border); box-shadow:0 10px 28px rgba(23,62,112,.06); }
.metric-label,.card-title { color:#61748b; }.metric-value,.answer,.node-name,.node-stat,.result-title,.example-value { color:var(--ink); }
.muted,.metric-note,.node-note,.story-intro,.stage-copy,.subtitle,p,label,.stCaption { color:var(--subtle); }
.pill-green,.pill-blue { color:#174ea6; background:#e7f0ff; border-color:#c4d9f5; }.pill-red { color:#8f3834; background:#fae6e3; }.pill-amber { color:#805b16; background:#fff1ca; }
.section-rule { background:#dce6f2; }.timeline { border-left-color:#b9d1ed; }.timeline-item:before { background:#4d86df; border-color:var(--paper); box-shadow:0 0 0 1px #2361b6; }
.walk-line { background:#dce6f2; }.walk-line.done { background:#6d9fe3; }.walk-step.done,.walk-step.active { color:#174ea6; }
.node-icon { background:#eaf2ff; color:#2361b6; }.node.alerted { border-color:#e8b2ad; }.node.recovered { border-color:#bcd3f1; }
.transfer,.transfer-arrow { color:#2361b6; }.check { background:#eaf2ff; color:#174ea6; }.check.bad { background:#fae6e3; color:#8f3834; }
.replay-badge { color:#365b87; background:#edf4fc; border-color:#cddff2; }.id-list { color:#496988; background:#f3f7fc; border-color:#dce6f2; }
.root-cause { border-color:#c4d9f5; background:linear-gradient(135deg,#eaf3ff 0%,#fff 72%); }.root-cause .card-title { color:#2361b6; }.pattern-chip { color:#174ea6; background:#e7f0ff; border-color:#c4d9f5; }
.featured-lead { margin-top:8px; }.featured-scenarios { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:14px; margin:14px 0 24px; }.featured-scenario { min-height:190px; padding:18px; border:1px solid #dce6f2; border-radius:16px; background:#fff; box-shadow:0 8px 22px rgba(23,62,112,.05); transition:transform .16s ease, box-shadow .16s ease, border-color .16s ease; }.featured-scenario:hover { transform:translateY(-2px); border-color:#aec9eb; box-shadow:0 13px 28px rgba(23,62,112,.1); }.featured-icon { display:grid; place-items:center; width:38px; height:38px; border-radius:11px; background:#eaf2ff; color:#2361b6; margin-bottom:14px; }.featured-icon .lucide { width:20px; height:20px; }.featured-category { color:#6b7e95; font-size:.68rem; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }.featured-scenario h3 { color:#0b1f3a!important; font-size:1.05rem!important; margin:5px 0 6px!important; }.featured-scenario p { min-height:47px; margin:0 0 13px; color:#60748b; font-size:.78rem; line-height:1.45; }.featured-status { display:inline-flex; padding:4px 8px; border-radius:999px; background:#f1f6fd; color:#416b9c; font-size:.64rem; font-weight:800; }.launch-note { margin:8px auto 0; text-align:center; color:#74869a; font-size:.76rem; }
.coverage { background:#e7edf5; }.coverage-a { background:#2f6fda; }.coverage-b { background:#78a9e8; }.coverage-c { background:#b8d2f2; }.workflow-chip.active { color:#174ea6; border-color:#9abbe8; background:#eaf2ff; }
.result-banner { border-color:#bcd3f1; background:linear-gradient(120deg,#eaf3ff,#fff); }.result-banner.bad { border-color:#efc1ba; background:#fff5f3; }
.state-dot { background:#2f6fda; }.state-dot.bad { background:var(--danger); }.approval-card { border-left-color:var(--warning); }.unavailable { background:#f3f6fa; border-color:#d5e2f1; }
.compare-table th { background:#f1f5fa; color:#60748b; }.compare-table td { border-color:#dce6f2; }.compare-table .good-cell { background:#eaf2ff; color:#174ea6; }
[data-testid="stMainBlockContainer"] button[kind="primary"] { background:#2f6fda; color:#fff; border:1px solid #2461c1; }.creator-credit { color:#94a4b7!important; }
[data-testid="stToolbar"], #MainMenu, footer { visibility:hidden; height:0; }
[data-testid="stToolbar"], .stAppToolbar { visibility:visible!important; height:44px!important; }
[data-testid="stMainMenuButton"] { visibility:hidden!important; }
[data-testid="stBaseButton-header"] { visibility:hidden!important; display:none!important; }
[data-testid="stExpandSidebarButton"] { visibility:visible!important; opacity:1!important; display:flex!important; position:fixed!important; left:12px!important; top:12px!important; z-index:1005!important; }
.home-hero { min-height:220px; display:flex; align-items:center; justify-content:space-between; gap:28px; position:relative; overflow:hidden; padding:30px 34px; margin:10px 0 28px; border-radius:22px; }.home-hero:after { content:''; position:absolute; right:0; top:0; width:48%; height:100%; background:linear-gradient(135deg,transparent 15%,rgba(77,143,225,.08) 16%,transparent 17%,transparent 39%,rgba(77,143,225,.12) 40%,transparent 41%),radial-gradient(circle at 68% 44%,rgba(138,190,242,.3),transparent 39%); pointer-events:none; }.home-hero-content,.home-hero-art { position:relative; z-index:1; }.home-hero-content { max-width:560px; }.home-hero p { font-size:.96rem; line-height:1.55; max-width:510px; margin-bottom:0; }.home-hero h1 { font-size:3.25rem!important; line-height:.98; margin:7px 0 10px!important; }.home-hero-art { width:230px; height:165px; flex:0 0 230px; }.hero-orbit { position:absolute; border:1px solid rgba(47,111,218,.3); border-radius:50%; transform:rotate(-26deg); }.hero-orbit-one { width:220px; height:92px; top:38px; left:4px; }.hero-orbit-two { width:160px; height:70px; top:49px; left:34px; border-color:rgba(47,111,218,.2); }.hero-spark { position:absolute; width:13px; height:13px; border-radius:50%; background:#2f6fda; box-shadow:0 0 0 8px rgba(47,111,218,.1),0 0 26px rgba(47,111,218,.35); top:77px; left:105px; }
.project-overview { margin:24px 0 18px; padding:28px 30px; border:1px solid #dce6f2; border-radius:20px; background:linear-gradient(135deg,#f4f8fd 0%,#fff 68%); box-shadow:0 12px 30px rgba(23,62,112,.06); }.project-overview-header { display:flex; align-items:center; justify-content:space-between; gap:22px; }.project-overview h2 { margin:0!important; font-size:1.55rem!important; }.project-overview p { margin:6px 0 0; color:#61748b; }.project-pipeline { display:flex; align-items:center; gap:12px; margin:26px 0 20px; }.project-node { min-width:170px; padding:14px 16px; border:1px solid #cddff2; border-radius:12px; background:#fff; }.project-node-label { color:#71849a; font-size:.68rem; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }.project-node-value { margin-top:4px; color:#193556; font-weight:800; }.project-arrow { color:#2f6fda; font-size:1.35rem; font-weight:800; }.project-meta { display:flex; gap:10px; flex-wrap:wrap; color:#516a86; font-size:.78rem; }.project-meta span { padding:6px 9px; border:1px solid #dce6f2; border-radius:999px; background:#fff; }.completion-card { margin:16px 0; padding:20px 22px; border:1px solid #cddff2; border-radius:16px; background:#fff; }.completion-card h3 { margin:0 0 5px!important; }.completion-card p { margin:0; color:#61748b; }
.brand-mark { font-size:.7rem!important; letter-spacing:.14em; text-align:center; }.brand-tag { display:none; }
[data-testid="stSidebar"] .sidebar-section-label { margin:24px 8px 8px; color:#7a8da4; font-size:.66rem; font-weight:800; letter-spacing:.1em; text-transform:uppercase; }
[data-testid="stSidebar"] button[kind="secondary"], [data-testid="stSidebar"] button[kind="primary"] { width:100%; min-height:40px; justify-content:flex-start; margin:2px 0; padding:8px 11px; border:1px solid transparent; border-radius:8px; color:#284b75; background:transparent; box-shadow:none; font-size:.82rem; font-weight:700; text-align:left; }
[data-testid="stSidebar"] button[kind="secondary"] > div, [data-testid="stSidebar"] button[kind="primary"] > div { justify-content:flex-start!important; gap:10px!important; }
[data-testid="stSidebar"] button[kind="secondary"] p, [data-testid="stSidebar"] button[kind="primary"] p { margin:0!important; text-align:left!important; }
[data-testid="stSidebar"] button[kind="secondary"] [data-testid="stIconMaterial"], [data-testid="stSidebar"] button[kind="primary"] [data-testid="stIconMaterial"] { width:18px!important; min-width:18px!important; flex:0 0 18px!important; text-align:center!important; }
[data-testid="stSidebar"] button[kind="secondary"]:hover { border-color:#c9dbf0; background:#f0f6ff; color:#174ea6; }
[data-testid="stSidebar"] button[kind="primary"] { border-color:#cfe0f4; background:#eaf2ff; color:#174ea6; box-shadow:none; }
[data-testid="stSidebar"] button[kind="primary"] span { color:#2361b6; }
[data-testid="stSidebar"] button[kind="secondary"] span { color:#4c78ad; }
[data-testid="stSidebar"] .incident-status-badge { display:inline-block; margin-top:10px; padding:3px 6px; border-radius:999px; color:#416b9c; background:#eaf2ff; font-size:.58rem; font-weight:800; white-space:nowrap; }
[data-testid="stSidebar"] .incident-status-badge.status-red { color:#8f3834; background:#fae6e3; }
[data-testid="stSidebar"] .incident-status-badge.status-amber { color:#805b16; background:#fff1ca; }
[data-testid="stSidebar"] .sidebar-developer { margin-top:14px; border-top:1px solid #dce6f2; padding-top:10px; }
.creator-credit { font-size:.63rem!important; line-height:1.2!important; margin-top:110px!important; }
.section-lead { margin-top:20px; }.section-lead h2 { font-size:1.15rem!important; }.metric-strip { gap:8px; }.metric { padding:12px 13px; min-height:74px; }.metric-value { font-size:1.3rem; }.card { padding:14px 16px; }
.flow { grid-template-columns:1fr 76px 1fr; gap:12px; }.node { min-height:150px; padding:17px; border-radius:13px; }.node-icon { width:38px; height:38px; border-radius:11px; }.lucide { width:21px; height:21px; }.node-name { font-size:1rem; }.node-stat { font-size:1.25rem; margin-top:14px; }.transfer-arrow { font-size:1.9rem; }
[data-testid="stMainBlockContainer"] button[kind="primary"], [data-testid="stMainBlockContainer"] [data-testid="stBaseButton-primary"] { min-height:46px!important; border-radius:9px!important; font-weight:800!important; letter-spacing:.01em; color:#f8fbff!important; background:linear-gradient(135deg,#071a34 0%,#123f83 58%,#1f66c8 100%)!important; border:1px solid #2f7be1!important; box-shadow:0 8px 18px rgba(16,71,150,.28), inset 0 1px 0 rgba(255,255,255,.16); transition:transform .15s ease, box-shadow .15s ease, background .15s ease; }
[data-testid="stMainBlockContainer"] button[kind="primary"] p, [data-testid="stMainBlockContainer"] [data-testid="stBaseButton-primary"] p { color:#f8fbff!important; font-weight:800!important; }
[data-testid="stMainBlockContainer"] button[kind="primary"]:hover, [data-testid="stMainBlockContainer"] [data-testid="stBaseButton-primary"]:hover { transform:translateY(-1px); box-shadow:0 11px 24px rgba(16,71,150,.38), inset 0 1px 0 rgba(255,255,255,.2); background:linear-gradient(135deg,#0a2346 0%,#174ea6 58%,#2f7be1 100%)!important; }
[data-testid="stMainBlockContainer"] button:not([kind="primary"]) { min-height:38px; border-radius:8px; border:1px solid #b9cce2; color:#174ea6; font-weight:700; background:#fff; }
[data-testid="stMainBlockContainer"] button:not([kind="primary"]):hover { border-color:#2f6fda; background:#eaf2ff; color:#0b1f3a; }
[data-testid="stSidebar"] .sidebar-developer [data-testid="stExpander"] { border:0!important; background:transparent!important; box-shadow:none!important; }
[data-testid="stSidebar"] .sidebar-developer [data-testid="stExpander"] summary { padding:7px 8px!important; color:#526f95!important; font-size:.76rem!important; }
[data-testid="stSidebar"] .sidebar-developer [data-testid="stExpander"] summary > div { justify-content:flex-start!important; gap:10px!important; }
[data-testid="stSidebar"] .sidebar-developer [data-testid="stExpander"] summary:hover { background:#f0f6ff; border-radius:8px; }
.next-step-card { border-color:#b9d1ed; background:linear-gradient(135deg,#f1f7ff,#fff); }.next-step-card strong { color:#0b1f3a; font-weight:800; }.next-step-note { margin:12px 0 4px; padding:10px 14px; border:1px solid #c4d9f5; border-radius:9px; background:#f1f7ff; color:#365b87; }.next-step-note b { color:#123f83; }
.compare-table { font-size:.76rem; }.compare-table th,.compare-table td { padding:9px 10px; }.history-row { padding:12px 14px; }.history-meta { font-size:.72rem; }
@media (max-width: 800px) { [data-testid="stMainBlockContainer"] { padding:18px 14px 36px; }.home-hero { min-height:0; padding:26px 24px; }.home-hero-art { display:none; }.featured-scenarios { grid-template-columns:1fr; }.result-focus { display:block; }.result-focus span { display:block; margin-top:5px; }.compact-summary { grid-template-columns:1fr; }.flow { grid-template-columns:1fr; }.transfer { transform:rotate(90deg); margin:-8px 0; }.metric-strip { grid-template-columns:1fr 1fr; }.history-detail-header { display:block; }.history-detail-header > div:last-child { margin-top:12px; }.history-detail-grid { grid-template-columns:1fr 1fr; } }
</style>
""",
    unsafe_allow_html=True,
)


def fetch(factory: Callable, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    conn = factory()
    try:
        return [dict(row) for row in conn.execute(sql, params)]
    finally:
        conn.close()


def one(factory: Callable, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    rows = fetch(factory, sql, params)
    return rows[0] if rows else None


def parse_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except (TypeError, json.JSONDecodeError):
        return {"raw": value}


def money(halalas: Any) -> str:
    if halalas is None:
        return "—"
    return f"SAR {int(halalas) / 100:,.2f}"


def display_field_value(field: str, value: Any) -> str:
    if value is None:
        return "—"
    return money(value) if field == "amount_halalas" else str(value)


def status_label(value: str | None) -> str:
    if isinstance(value, bool):
        return "Passed" if value else "Not passed"
    return (value or "unknown").replace("_", " ").title()


def history_timestamp(value: Any) -> str:
    """Format persisted timestamps for people without changing their stored value."""
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
        return parsed.strftime("%b %-d, %Y · %-I:%M %p UTC")
    except ValueError:
        return str(value)


def history_badge(label: str, style: str = "neutral") -> str:
    icons = {"verified": "✓", "healthy": "•", "failed": "!", "review": "!"}
    icon_text = icons.get(style, "")
    return f'<span class="history-badge history-badge-{style}"><span class="history-badge-icon">{icon_text}</span>{label}</span>'


def pill(value: str | None, tone: str = "blue") -> str:
    return f'<span class="pill pill-{tone}">{status_label(value)}</span>'


def tone(value: str | None) -> str:
    value = (value or "").lower()
    if value in {"healthy", "verified", "completed", "succeeded", "executed", "safe", "active"}:
        return "green"
    if value in {"corrupted", "failed", "escalated", "unsafe", "quarantined"}:
        return "red"
    if value in {"investigating", "pending", "unknown", "proposed", "review_required"}:
        return "amber"
    return "blue"


def metric(label: str, value: Any, note: str = "", container: Any = st) -> None:
    container.markdown(f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value">{value}</div><div class="metric-note">{note}</div></div>', unsafe_allow_html=True)


def cause_text(cause: str | None) -> str:
    values = {
        "silent_amount_scale_corruption": "A numeric transformation changed destination values.",
        "persistent_transform_defect": "The active transformation is still defective, so retrying could reproduce the corruption.",
        "unsafe_or_ambiguous_destination_state": "Some destination records had conflicts or missing trusted evidence.",
        "insufficient_evidence": "The available evidence was not sufficient to establish a safe recovery.",
        "text_truncation": "A text field was shortened during synchronization.",
        "text_replacement": "A text field was replaced or transformed during synchronization.",
        "text_encoding": "A text field may have been changed by an encoding transformation.",
        "investigation_incomplete": "Investigation incomplete — the model did not submit a final interpretation.",
        "investigation_api_error": "Investigation unavailable because the model request failed.",
        "model_response_invalid": "The model response was not valid for ECHO's investigation contract.",
    }
    return values.get(cause or "", cause.replace("_", " ").capitalize() if cause else "Not recorded")


def classify_investigation_error(message: str) -> tuple[str, str]:
    """Return a safe operator label and explanation without exposing secrets."""
    text = (message or "").lower()
    if "no tool output found" in text or "function call" in text:
        return "OpenAI tool-loop protocol error", "OpenAI returned a function call that ECHO did not answer completely."
    if "401" in text or "authentication" in text or "api key" in text:
        return "Authentication error", "OpenAI rejected the credential or authentication request."
    if "403" in text or "permission" in text or "model_not_found" in text:
        return "Model access error", "The configured account may not have access to the selected model."
    if "429" in text or "quota" in text or "rate limit" in text or "billing" in text:
        return "Quota or billing error", "OpenAI rejected the request because of quota, rate-limit, or billing state."
    if "timeout" in text or "timed out" in text:
        return "Timeout", "The request exceeded ECHO's configured investigation time limit."
    if "json" in text or "parse" in text or "invalid" in text:
        return "Response parsing error", "OpenAI responded, but ECHO could not parse the response contract."
    if "connection" in text or "network" in text or "dns" in text:
        return "Network error", "ECHO could not establish or maintain the OpenAI connection."
    return "OpenAI investigation error", "The request failed before ECHO could complete a structured investigation."


def observed_pattern_text(rows: list[dict[str, Any]], ratios: list[int]) -> str:
    fields = {str(row.get("Field")) for row in rows}
    if "description" in fields:
        type_counts: dict[str, int] = {}
        for row in rows:
            if row.get("Field") != "description":
                continue
            label = str(row.get("Discrepancy type") or "Text value mismatch")
            type_counts[label] = type_counts.get(label, 0) + 1
        detail = ", ".join(f"{count} {label.lower()}" for label, count in type_counts.items())
        return f"Observed text changes: {detail or 'description fields differ'}; numerical multiplier analysis does not apply."
    if ratios:
        return f"Observed numerical pattern: destination values include a {ratios[0]}× scale factor."
    return "Observed pattern: not established from persisted evidence."


def icon(name: str) -> str:
    paths = {
        "database": '<ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v7c0 1.7 3.1 3 7 3s7-1.3 7-3V5"/><path d="M5 9c0 1.7 3.1 3 7 3s7-1.3 7-3"/>',
        "file": '<path d="M5 3h9l5 5v13H5z"/><path d="M14 3v6h6M8 13h8M8 17h6"/>',
        "shield": '<path d="M12 3 19 6v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z"/><path d="m9 12 2 2 4-4"/>',
        "search": '<circle cx="10.5" cy="10.5" r="5.5"/><path d="m15 15 5 5"/>',
    }
    return f'<svg class="lucide" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{paths.get(name, paths["file"])}</svg>'


def incident_data(incident_id: str) -> dict[str, Any]:
    incident = one(echo_conn, "SELECT * FROM incidents WHERE id=?", (incident_id,)) or {}
    run = one(echo_conn, "SELECT * FROM sync_runs WHERE id=?", (incident.get("run_id"),)) or {}
    alert = parse_json(incident.get("alert_json"))
    outcome = parse_json(incident.get("outcome_json"))
    plan = one(echo_conn, "SELECT * FROM recovery_plans WHERE incident_id=? ORDER BY id DESC LIMIT 1", (incident_id,)) or {}
    plan_json = parse_json(plan.get("proposal_json"))
    safety = parse_json(plan.get("safety_json"))
    repairs = fetch(echo_conn, "SELECT * FROM repair_items WHERE plan_id=? ORDER BY id", (plan.get("id"),)) if plan.get("id") else []
    verification = one(echo_conn, "SELECT * FROM verification_reports WHERE incident_id=? ORDER BY id DESC LIMIT 1", (incident_id,)) or {}
    verification_json = parse_json(verification.get("details_json"))
    pipeline = one(echo_conn, "SELECT * FROM pipelines WHERE id=?", (incident.get("pipeline_id"),)) or {}
    events = fetch(echo_conn, "SELECT * FROM investigation_events WHERE incident_id=? ORDER BY ts, id", (incident_id,))
    activities = fetch(echo_conn, "SELECT * FROM activity_events WHERE incident_id=? ORDER BY ts, id", (incident_id,))
    logs = fetch(echo_conn, "SELECT * FROM sync_logs WHERE run_id=? ORDER BY ts", (incident.get("run_id"),))
    usage = fetch(echo_conn, "SELECT * FROM usage_events WHERE incident_id=? ORDER BY id", (incident_id,))
    return {"incident": incident, "run": run, "alert": alert, "outcome": outcome, "plan": plan, "plan_json": plan_json, "safety": safety, "repairs": repairs, "verification": verification, "verification_json": verification_json, "pipeline": pipeline, "events": events, "activities": activities, "logs": logs, "usage": usage}


def incident_has_investigation_error(incident_id: str) -> bool:
    row = one(echo_conn, "SELECT 1 AS found FROM investigation_events WHERE incident_id=? AND kind='investigation_error' LIMIT 1", (incident_id,))
    return bool(row)


def pipeline_presentation(data: dict[str, Any]) -> tuple[str, str]:
    """Explain persisted quarantine without implying it was justified or removed."""
    status = data["pipeline"].get("status") or "not recorded"
    plan_faulty = data["plan_json"].get("pipeline_faulty")
    if status == "quarantined" and plan_faulty is False:
        recorded = next((row.get("summary") for row in data.get("activities", []) if row.get("kind") == "pipeline_quarantined"), None)
        reason = recorded or data["pipeline"].get("resume_blocked_reason") or "No quarantine reason was recorded."
        return (
            "Quarantined · historical mismatch",
            f"Recorded quarantine reason: {reason} The persisted safety plan classified the configured pipeline as not faulty. This state is retained for audit and requires operator review; ECHO has not removed it automatically.",
        )
    if status == "quarantined":
        reason = data["pipeline"].get("resume_blocked_reason") or "Active transformation defect; retry is unsafe."
        return "Quarantined", f"Pipeline quarantine is enforced because the deterministic plan identified a persistent transformation defect: {reason}"
    return status_label(status), "Pipeline status is separate from record repair. ECHO does not infer that a repaired record made the pipeline healthy."


def comparison_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    repairs = data["repairs"]
    if not repairs:
        # A failed investigation can occur before a recovery plan is created.
        # In that narrow case, the destination has not been repaired, so the
        # live mismatch is the recorded failed-run observation. Do not use
        # this fallback after any recovery plan exists.
        if data["plan"] or data["incident"].get("recovery_status") not in {"failed", "escalated"}:
            return []
        allowed = set((data["alert"].get("monitor_findings") or {}).get("affected_record_ids") or [])
        if not allowed:
            return []
        rows = []
        finance, analytics = finance_conn(), analytics_conn()
        try:
            mismatches = field_mismatches(finance, analytics)
        finally:
            finance.close()
            analytics.close()
        for mismatch in mismatches:
            if mismatch.get("record_id") not in allowed:
                continue
            field = mismatch.get("field") or "record"
            source_value = mismatch.get("source_value")
            before = mismatch.get("dest_value")
            rows.append({
                "Transaction": mismatch["record_id"],
                "Field": field,
                "Discrepancy type": "Text value mismatch" if field == "description" else "Amount value mismatch",
                "Original trusted value": display_field_value(field, source_value),
                "Corrupted destination value": display_field_value(field, before),
                "Proposed replacement": "—",
                "Applied replacement": "—",
                "Verified result": "Not verified",
                "Recovery result": "Not changed — investigation failed",
                "_source": source_value,
                "_before": before,
            })
        return rows
    ids = [row["record_id"] for row in repairs]
    placeholders = ",".join("?" for _ in ids)
    sources = {row["record_id"]: row for row in fetch(finance_conn, f"SELECT record_id, amount_halalas, description FROM transactions WHERE record_id IN ({placeholders})", tuple(ids))}
    snapshot_rows = fetch(echo_conn, f"SELECT record_id, amount_halalas, description FROM dest_snapshots WHERE incident_id=? AND record_id IN ({placeholders})", tuple([data["incident"]["id"]] + ids))
    snapshots = {row["record_id"]: row for row in snapshot_rows}
    analytics = {row["record_id"]: row for row in fetch(analytics_conn, f"SELECT record_id, amount_halalas, description FROM fact_transactions WHERE record_id IN ({placeholders})", tuple(ids))}
    rows = []
    for repair in repairs:
        record_id = repair["record_id"]
        field = repair.get("field") or "amount_halalas"
        source = sources.get(record_id, {})
        before = snapshots.get(record_id, {}).get(field, repair.get("current_value"))
        after = analytics.get(record_id, {}).get(field)
        applied = repair.get("safety_status") == "safe" and data["plan"].get("status") == "executed"
        verified = bool(data["verification_json"].get("passed")) and applied and after == source.get(field, repair.get("proposed_value"))
        if repair.get("safety_status") != "safe":
            result = "Not changed — escalated"
        elif verified:
            result = "Repaired and verified"
        elif applied:
            result = "Repaired — verification unavailable"
        else:
            result = "Proposed only"
        source_value = source.get(field, repair.get("proposed_value"))
        ratio = None
        if field == "amount_halalas" and source_value not in (None, 0) and before is not None:
            before_int, source_int = int(before), int(source_value)
            if before_int % source_int == 0:
                ratio = before_int // source_int
        discrepancy_type = f"Observed amount scale mismatch ({ratio}×)" if ratio and ratio > 1 else "Amount value mismatch" if field == "amount_halalas" else "Text value mismatch"
        rows.append({"Transaction": record_id, "Field": field, "Discrepancy type": discrepancy_type, "Original trusted value": display_field_value(field, source_value), "Corrupted destination value": display_field_value(field, before), "Proposed replacement": display_field_value(field, source_value), "Applied replacement": display_field_value(field, after) if applied else "—", "Verified result": "Verified against trusted source" if verified else "Not independently verified", "Recovery result": result, "_source": source_value, "_before": before})
    return rows


def render_timeline(data: dict[str, Any]) -> None:
    events = data["events"]
    usage_models = {row.get("model") for row in data["usage"] if row.get("model")}
    started_models = {
        parse_json(event.get("payload_json")).get("model")
        for event in events
        if event.get("kind") == "investigation_started"
    }
    models = {str(model) for model in usage_models | started_models if model}
    if not events:
        st.info("No investigation timeline has been recorded for this incident.")
        return
    if not any(event.get("kind") == "tool_executed" for event in events):
        st.info("Individual diagnostic tool calls were not recorded for this incident; only the available lifecycle events are shown.")
    if models:
        label = "Live OpenAI investigation" if any(not model.endswith("mock") for model in models) else "Heuristic mock investigation"
        tool_count = sum(1 for event in events if event.get("kind") == "tool_executed")
        estimated_cost = sum(float(row.get("estimated_usd") or 0) for row in data["usage"])
        st.caption(f"Investigation mode recorded: **{label}** · model: **{', '.join(sorted(models))}** · diagnostic tool calls: **{tool_count}/8** · estimated cost: **${estimated_cost:.4f} / $0.10 limit**")
    for event in events:
        payload = parse_json(event.get("payload_json"))
        kind = event.get("kind", "event")
        title = event.get("summary") or kind.replace("_", " ").title()
        if kind == "tool_executed":
            tool_name = payload.get("tool") or title
            title = f"Diagnostic check: {tool_name.replace('_', ' ')}"
        st.markdown(f'<div class="timeline"><div class="timeline-item"><div class="timeline-kind">{status_label(kind)}</div><div class="timeline-summary">{title}</div><div class="timeline-time">{event.get("ts", "")}</div></div></div>', unsafe_allow_html=True)


def render_pipeline_visual(data: dict[str, Any], recovered: bool = False) -> None:
    source_count = (one(finance_conn, "SELECT COUNT(*) AS n FROM transactions") or {}).get("n", 0)
    destination_count = (one(analytics_conn, "SELECT COUNT(*) AS n FROM fact_transactions") or {}).get("n", 0)
    run = data["run"]
    incident = data["incident"]
    integrity = status_label(run.get("integrity_status"))
    destination_class = "recovered" if recovered else "alerted" if integrity.lower() == "corrupted" else ""
    destination_note = "Verified synchronized copy" if recovered else "Synchronized copy · integrity issue"
    destination_status = "Verified" if recovered else integrity
    st.markdown(
        f'''
        <div class="flow">
          <div class="node">
            <div class="node-top"><div class="node-icon">{icon("database")}</div><span class="pill pill-green">Trusted</span></div>
            <div class="node-label">Source system</div><div class="node-name">Finance</div><div class="node-note">Trusted original records</div>
            <div class="node-stat">{int(source_count):,} <small>transactions</small></div>
          </div>
          <div class="transfer"><div class="transfer-arrow">→</div><div class="transfer-label">Sync run<br><b>{run.get("id", "—")}</b></div></div>
          <div class="node {destination_class}">
            <div class="node-top"><div class="node-icon">{icon("file")}</div><span class="pill pill-{"green" if recovered else "red" if integrity.lower() == "corrupted" else "amber"}">{destination_status}</span></div>
            <div class="node-label">Destination system</div><div class="node-name">Analytics</div><div class="node-note">{destination_note}</div>
            <div class="node-stat">{int(destination_count):,} <small>transactions</small></div>
          </div>
        </div>
        ''',
        unsafe_allow_html=True,
    )


def render_sync_preview(data: dict[str, Any], *, destination: bool = False, limit: int = 4) -> None:
    """Show a small real-record preview without turning replay into execution."""
    alert_findings = data["alert"].get("monitor_findings") or {}
    affected = list(alert_findings.get("affected_record_ids") or [])
    source_rows = fetch(finance_conn, "SELECT record_id, amount_halalas, description FROM transactions ORDER BY record_id LIMIT ?", (limit,))
    if affected:
        placeholders = ",".join("?" for _ in affected[:limit])
        source_rows = fetch(finance_conn, f"SELECT record_id, amount_halalas, description FROM transactions WHERE record_id IN ({placeholders}) ORDER BY record_id", tuple(affected[:limit]))
    if not source_rows:
        return
    ids = [row["record_id"] for row in source_rows]
    placeholders = ",".join("?" for _ in ids)
    if destination:
        snapshots = fetch(echo_conn, f"SELECT record_id, amount_halalas, description FROM dest_snapshots WHERE incident_id=? AND record_id IN ({placeholders}) ORDER BY record_id", tuple([data["incident"].get("id")] + ids))
        destination_rows = {row["record_id"]: row for row in snapshots}
        preview_note = "Persisted pre-recovery destination snapshot"
        if not destination_rows and not data["plan"] and data["incident"].get("recovery_status") in {"failed", "escalated"}:
            current = fetch(analytics_conn, f"SELECT record_id, amount_halalas, description FROM fact_transactions WHERE record_id IN ({placeholders}) ORDER BY record_id", tuple(ids))
            destination_rows = {row["record_id"]: row for row in current}
            preview_note = "Destination observed at the failed run; no repair was executed"
    else:
        destination_rows = {}
        preview_note = "Trusted source records"
    table = []
    for source in source_rows:
        dest = destination_rows.get(source["record_id"])
        table.append({
            "Record ID": source["record_id"],
            "Amount": money((dest or source)["amount_halalas"]),
            "Description": (dest or source)["description"],
            "Evidence": "Destination" if destination and dest else "Source",
        })
    st.caption(preview_note)
    st.dataframe(table, use_container_width=True, hide_index=True)


def render_stage(data: dict[str, Any], stage: int) -> None:
    incident, run, alert, outcome = data["incident"], data["run"], data["alert"], data["outcome"]
    findings = alert.get("monitor_findings") or {}
    intent = outcome.get("intent") or {}
    plan = data["plan_json"]
    verification = data["verification_json"]
    count = plan.get("mismatch_count", findings.get("amount_discrepancy_count", 0))
    rows = comparison_rows(data)
    example = rows[0] if rows else None
    if stage == 0:
        st.markdown('<div class="stage-panel"><div class="stage-kicker">Replay · Stage 1 of 4</div><div class="stage-title">Synchronize</div><div class="stage-copy">Finance sends the trusted transaction set to Analytics. The run completed technically; ECHO keeps that separate from whether the data is correct.</div></div>', unsafe_allow_html=True)
        render_pipeline_visual(data)
        a, b, c = st.columns(3)
        a.markdown(f'<div class="check">✓ Execution: <b>{status_label(run.get("execution_status"))}</b></div>', unsafe_allow_html=True)
        b.markdown(f'<div class="check {"bad" if run.get("integrity_status") == "corrupted" else ""}">Integrity: <b>{status_label(run.get("integrity_status"))}</b></div>', unsafe_allow_html=True)
        c.markdown(f'<div class="check">Records processed: <b>{int(run.get("records_processed") or 0):,}</b></div>', unsafe_allow_html=True)
    elif stage == 1:
        st.markdown('<div class="stage-panel"><div class="stage-kicker">Replay · Stage 2 of 4</div><div class="stage-title">Detect</div><div class="stage-copy">The sync reported success, but the integrity monitor compared trusted Finance values with the Analytics copy and found a mismatch.</div></div>', unsafe_allow_html=True)
        render_pipeline_visual(data)
        total_compared = (one(finance_conn, "SELECT COUNT(*) AS n FROM transactions") or {}).get("n", 0)
        matching = max(0, int(total_compared or 0) - int(count or 0))
        d1, d2, d3 = st.columns(3)
        d1.markdown(f'<div class="card"><div class="card-title">Records compared</div><div class="answer">{int(total_compared):,}</div></div>', unsafe_allow_html=True)
        d2.markdown(f'<div class="card"><div class="card-title">Matching records</div><div class="answer">{matching:,}</div></div>', unsafe_allow_html=True)
        d3.markdown(f'<div class="card"><div class="card-title">Discrepancies</div><div class="answer" style="color:var(--danger)">{int(count):,}</div></div>', unsafe_allow_html=True)
        if example:
            st.markdown(f'<div class="example"><div class="example-label">A transaction that tells the story</div><div class="example-value">{example["Transaction"]} · trusted {example["Original trusted value"]} → destination was {example["Corrupted destination value"]}</div><div class="node-note">The destination value was different even though the synchronization execution succeeded.</div></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="card"><div class="card-title">Different field</div><div class="answer"><b>amount_halalas</b> <span class="muted">(displayed above as SAR)</span></div><div class="node-note">Affected transactions: {len(rows)}</div></div>', unsafe_allow_html=True)
        if rows:
            st.markdown(f'<div class="id-list"><b>Affected transaction IDs</b><br>{" · ".join(row["Transaction"] for row in rows)}</div>', unsafe_allow_html=True)
        st.warning(f"Integrity alert: {count} transaction amount discrepancy(ies) detected.")
    elif stage == 2:
        st.markdown('<div class="stage-panel"><div class="stage-kicker">Replay · Stage 3 of 4</div><div class="stage-title">Investigate & recover</div><div class="stage-copy">ECHO reviewed the recorded evidence, identified the likely cause, and created a recovery plan. The model proposes; deterministic safety checks decide what can change.</div></div>', unsafe_allow_html=True)
        summary = investigation_summary(data)
        root = summary["root"]
        strategy = plan.get("decision") or intent.get("strategy") or "not recorded"
        confidence = intent.get("confidence")
        retry_safe = intent.get("pipeline_safe_to_retry")
        confidence_text = f"{float(confidence):.0%}" if confidence is not None else "Not recorded"
        retry_text = "Retry is considered safe." if retry_safe is True else "Retry is unsafe while the faulty pipeline remains active." if retry_safe is False else "Retry safety was not recorded."
        left, right = st.columns([1.15, .85])
        left.markdown(f'<div class="card"><div class="card-title">What ECHO determined</div><div class="answer"><b>{summary.get("title", "Investigation finding")}</b></div><p>{summary.get("summary", root)}</p><p><b>Suspected cause:</b> {root}</p><p>Recovery decision: <b>{status_label(strategy)}</b></p><p>Confidence recorded: <b>{confidence_text}</b></p><p>{retry_text}</p></div>', unsafe_allow_html=True)
        right.markdown(f'<div class="card"><div class="card-title">Safety outcome</div><div class="answer"><b>{plan.get("safe_count", 0)}</b> eligible to restore<br><b>{plan.get("unsafe_count", 0)}</b> kept unchanged</div><p>Pipeline: <b>{status_label(data["pipeline"].get("status"))}</b></p></div>', unsafe_allow_html=True)
        st.markdown("#### Recorded investigation steps")
        render_timeline(data)
    else:
        passed = bool(verification.get("passed"))
        st.markdown(f'<div class="stage-panel"><div class="stage-kicker">Replay · Stage 4 of 4</div><div class="stage-title">Verify</div><div class="stage-copy">An independent verifier checked the actual Analytics database after the recovery action. ECHO does not treat the model’s proposal as proof of success.</div></div>', unsafe_allow_html=True)
        render_pipeline_visual(data, recovered=passed)
        if passed:
            st.success(f"Recovery verified: {verification.get('verified_repairs', 0)} repaired record(s) now match the trusted Finance values.")
        elif verification:
            st.error("Independent verification did not pass. The incident remains unresolved.")
        else:
            st.info("No independent verification report is recorded for this incident.")
        quarantine = data["pipeline"].get("status") == "quarantined"
        q1, q2 = st.columns(2)
        q1.markdown(f'<div class="check {"bad" if quarantine else ""}">{"⚠" if quarantine else "○"} Pipeline quarantine: <b>{"Enforced" if quarantine else "Not recorded"}</b></div>', unsafe_allow_html=True)
        q2.markdown(f'<div class="check">✓ Final outcome: <b>{status_label(incident.get("recovery_status"))}</b></div>', unsafe_allow_html=True)
        if rows:
            st.markdown("#### Before → after evidence")
            st.dataframe(rows, use_container_width=True, hide_index=True)
        if quarantine:
            st.caption("The pipeline remains quarantined. ECHO has not implied that it was restarted or made healthy.")
        if passed:
            st.markdown('<div class="hero"><div class="hero-copy"><b>Conclusion:</b> ECHO restored only the records permitted by its safety checks, then independently confirmed that the repaired values match Finance.</div></div>', unsafe_allow_html=True)
        elif incident.get("recovery_status") == "escalated":
            st.markdown('<div class="hero"><div class="hero-copy"><b>Conclusion:</b> ECHO detected the problem but preserved uncertain records and escalated the unresolved work for human review.</div></div>', unsafe_allow_html=True)


def render_replay_nav(stage: int) -> None:
    labels = ["Synchronize", "Detect", "Investigate", "Verify"]
    pieces = []
    for index, label in enumerate(labels):
        state = "active" if index == stage else "done" if index < stage else ""
        pieces.append(f'<div class="walk-step {state}">{index + 1}<br>{label}</div>')
        if index < len(labels) - 1:
            pieces.append(f'<div class="walk-line {"done" if index < stage else ""}"></div>')
    st.markdown(f'<div class="walk-nav">{"".join(pieces)}</div>', unsafe_allow_html=True)
    left, middle, right = st.columns([1, 1, 1])
    with left:
        if st.button("← Back", disabled=stage == 0, use_container_width=True, key="replay_back"):
            st.session_state["demo_stage"] = stage - 1
            st.rerun()
    with middle:
        st.markdown(f'<div class="nav-note">Replay stage {stage + 1} of 4 · no new backend action</div>', unsafe_allow_html=True)
    with right:
        if stage < 3:
            if st.button("Next →", type="primary", use_container_width=True, key="replay_next"):
                st.session_state["demo_stage"] = stage + 1
                st.rerun()
        elif st.button("Restart Replay", use_container_width=True, key="replay_restart"):
            st.session_state["demo_stage"] = 0
            st.session_state["replay_started"] = False
            st.rerun()


def render_incident(data: dict[str, Any]) -> None:
    incident, run = data["incident"], data["run"]
    current = int(st.session_state.get("demo_stage", 0))
    stage = min(current, 3)
    status = incident.get("recovery_status") or "pending"
    st.markdown('<span class="replay-badge">↻ Replay · persisted incident · navigation does not run anything</span>', unsafe_allow_html=True)
    st.subheader(f'{incident.get("id", "Incident")} · {status_label(status)}')
    st.caption(f'Run {run.get("id", "—")} · {status_label(run.get("execution_status"))} execution · {status_label(run.get("integrity_status"))} integrity · detected {incident.get("detected_at", "—")}', unsafe_allow_html=True)
    render_replay_nav(stage)
    render_stage(data, stage)
    render_replay_nav(stage)

    with st.expander("Advanced Details", expanded=False):
        st.caption("Technical evidence is available here for operators and developers. The walkthrough above is intentionally simplified for demonstration.")
        st.markdown("**Raw incident alert**")
        st.json(data["alert"])
        st.markdown("**Recorded outcome and recovery plan**")
        st.json({"outcome": data["outcome"], "plan": data["plan_json"], "safety": data["safety"]})
        st.markdown("**Investigation events and diagnostic payloads**")
        st.json(data["events"])
        st.markdown("**Synchronization logs**")
        st.json(data["logs"])
        st.markdown("**Source/destination repair evidence**")
        st.dataframe(comparison_rows(data), use_container_width=True, hide_index=True)
        st.markdown("**Internal identifiers**")
        st.json({"incident_id": incident.get("id"), "run_id": run.get("id"), "pipeline_id": incident.get("pipeline_id"), "plan_id": data["plan"].get("id"), "verification_id": data["verification"].get("id")})
        st.markdown("**Synchronization history**")
        render_history(fetch(echo_conn, "SELECT * FROM sync_runs ORDER BY COALESCE(finished_at, started_at) DESC"))


def render_history(runs: list[dict[str, Any]]) -> None:
    st.markdown("## Synchronization history")
    st.caption("Historical context is secondary to the active incident. Execution status and data integrity are separate signals.")
    if not runs:
        st.info("No synchronization history has been recorded yet.")
        return
    for run in runs:
        integrity = run.get("integrity_status") or "unknown"
        marker = "🟢" if integrity == "healthy" else "🔴" if integrity == "corrupted" else "🟡"
        st.markdown(f"{marker} **{run.get('id', '—')}** · {run.get('finished_at') or run.get('started_at') or '—'} · {int(run.get('records_processed') or 0):,} records · execution {status_label(run.get('execution_status'))} · integrity {status_label(integrity)}")
    with st.expander("Detailed synchronization table"):
        st.dataframe(runs, use_container_width=True, hide_index=True)


def run_worker(mode: str) -> Any:
    """Run the selected mode without changing the agent or recovery layers."""
    import echo.agent.openai_client as client

    previous_mode = client.LLM_MODE
    client.LLM_MODE = "mock" if mode == "Mock (offline)" else "openai"
    try:
        return process_one()
    finally:
        client.LLM_MODE = previous_mode


def comparison_table(rows: list[dict[str, Any]], limit: int | None = None, *, phase: str = "recovery") -> None:
    visible = rows if limit is None else rows[:limit]
    if not visible:
        st.info("No persisted comparison rows are available for this incident.")
        return
    body = []
    if phase == "detection":
        for row in visible:
            body.append(f'<tr><td><b>{row["Transaction"]}</b></td><td>{row["Field"]}</td><td>{row["Original trusted value"]}</td><td class="bad-cell">{row["Corrupted destination value"]}</td></tr>')
        header = "<th>Record</th><th>Field</th><th>Trusted source value</th><th>Incorrect value</th>"
    else:
        for row in visible:
            body.append(f'<tr><td><b>{row["Transaction"]}</b></td><td>{row["Field"]}</td><td>{row["Original trusted value"]}</td><td class="bad-cell">{row["Corrupted destination value"]}</td><td>{row["Proposed replacement"]}</td><td class="good-cell">{row["Applied replacement"]}</td><td>{row["Verified result"]}</td></tr>')
        header = "<th>Record</th><th>Field</th><th>Trusted source value</th><th>Incorrect value</th><th>Suggested correction</th><th>Value after repair</th><th>Verification</th>"
    st.markdown(f'<div class="table-wrap"><table class="compare-table"><thead><tr>{header}</tr></thead><tbody>{"".join(body)}</tbody></table></div>', unsafe_allow_html=True)


def render_story(data: dict[str, Any]) -> None:
    """Render one continuous persisted-evidence story for the selected incident."""
    incident, run, alert, outcome = data["incident"], data["run"], data["alert"], data["outcome"]
    findings = alert.get("monitor_findings") or {}
    intent = outcome.get("intent") or {}
    plan = data["plan_json"]
    verification = data["verification_json"]
    rows = comparison_rows(data)
    discrepancy_count = int(plan.get("mismatch_count", findings.get("amount_discrepancy_count", len(rows))) or 0)
    total_compared = int((one(finance_conn, "SELECT COUNT(*) AS n FROM transactions") or {}).get("n", 0) or 0)
    matching_count = max(0, total_compared - discrepancy_count)
    status = incident.get("recovery_status") or "pending"
    passed = bool(verification.get("passed"))
    model_names = {str(row.get("model")) for row in data["usage"] if row.get("model")}
    model_names |= {str(parse_json(event.get("payload_json")).get("model")) for event in data["events"] if event.get("kind") == "investigation_started" and parse_json(event.get("payload_json")).get("model")}
    tool_count = sum(1 for event in data["events"] if event.get("kind") == "tool_executed")
    mode_label = "Live OpenAI" if any(not model.endswith("mock") for model in model_names) else "Heuristic simulation"

    st.markdown('<span class="replay-badge">↻ Recorded replay · no new synchronization or API call</span>', unsafe_allow_html=True)
    st.markdown(f'<div class="story-section" style="--delay:.05s"><div class="story-heading"><span class="story-number">1</span><h2>Synchronization</h2></div><div class="story-intro">A recorded synchronization moves a trusted source dataset into a destination copy. This is a replay of {run.get("id", "the selected run")}, not a new transfer.</div></div>', unsafe_allow_html=True)
    render_pipeline_visual(data)
    sync_cols = st.columns(3)
    sync_cols[0].markdown(f'<div class="check">✓ Execution: <b>{status_label(run.get("execution_status"))}</b></div>', unsafe_allow_html=True)
    sync_cols[1].markdown(f'<div class="check {"bad" if run.get("integrity_status") == "corrupted" else ""}">Integrity: <b>{status_label(run.get("integrity_status"))}</b></div>', unsafe_allow_html=True)
    sync_cols[2].markdown(f'<div class="check">Records: <b>{int(run.get("records_processed") or 0):,}</b></div>', unsafe_allow_html=True)

    st.markdown(f'<div id="comparison" class="story-section" style="--delay:.35s"><div class="story-heading"><span class="story-number">2</span><h2>Integrity check</h2></div><div class="story-intro">The synchronization finished, but ECHO compared the persisted source and destination evidence and found that some values did not match.</div></div>', unsafe_allow_html=True)
    compare_cols = st.columns(3)
    compare_cols[0].markdown(f'<div class="metric"><div class="metric-label">Compared</div><div class="metric-value">{total_compared:,}</div><div class="metric-note">records checked</div></div>', unsafe_allow_html=True)
    compare_cols[1].markdown(f'<div class="metric"><div class="metric-label">Matched</div><div class="metric-value">{matching_count:,}</div><div class="metric-note">actual matching evidence</div></div>', unsafe_allow_html=True)
    compare_cols[2].markdown(f'<div class="metric"><div class="metric-label">Differed</div><div class="metric-value" style="color:var(--danger)">{discrepancy_count:,}</div><div class="metric-note">integrity discrepancies</div></div>', unsafe_allow_html=True)
    if rows:
        first = rows[0]
        st.markdown(f'<div class="example"><div class="example-label">One discrepancy</div><div class="example-value">{first["Transaction"]} · {first["Original trusted value"]} in Source Dataset → {first["Corrupted destination value"]} in Destination Dataset</div><div class="node-note">The destination value is the persisted pre-recovery observation.</div></div>', unsafe_allow_html=True)
        comparison_table(rows, limit=5, phase="detection")
        if len(rows) > 5:
            with st.expander(f"Browse all {len(rows)} affected records"):
                comparison_table(rows, phase="detection")
        st.markdown(f'<div class="id-list"><b>Exact affected record IDs</b><br>{" · ".join(row["Transaction"] for row in rows)}</div>', unsafe_allow_html=True)
    else:
        st.info("No persisted repair rows are available for this incident.")

    st.markdown(f'<div id="investigation" class="story-section" style="--delay:.65s"><div class="story-heading"><span class="story-number">3</span><h2>ECHO intelligence</h2></div><div class="story-intro">ECHO used the recorded investigation path to assess the evidence. The display below contains only persisted events and structured results.</div></div>', unsafe_allow_html=True)
    summary = investigation_summary(data)
    intel_left, intel_right = st.columns([1.05, .95])
    root = summary["root"]
    confidence = intent.get("confidence")
    confidence_text = f"{float(confidence):.0%}" if confidence is not None and not summary["investigation_error"] else ("Unavailable" if summary["investigation_error"] else "Not established")
    strategy = summary["strategy"]
    retry_safe = intent.get("pipeline_safe_to_retry")
    retry_text = "Retry is considered safe." if retry_safe is True else "Retry is unsafe while the faulty pipeline remains active." if retry_safe is False else "Retry safety was not recorded."
    with intel_left:
        evidence_text = " ".join(str(item) for item in summary.get("supporting_evidence") or []) or summary["pattern"]
        if summary["investigation_error"] or not summary["investigation_complete"]:
            st.markdown(f'<div class="card"><div class="card-title">AI investigation</div><div class="answer"><b>Investigation incomplete</b></div><p>{summary["recovery_reason"]}</p><p><b>Recovery is blocked</b> until ECHO receives a complete validated investigation and the deterministic safety checks pass.</p><p>Mode: <b>{mode_label}</b></p></div>', unsafe_allow_html=True)
        else:
            uncertainty = intent.get("uncertainty") or []
            uncertainty_text = " ".join(str(item) for item in uncertainty) if uncertainty else "No additional uncertainty recorded."
            st.markdown(f'<div class="card"><div class="card-title">What went wrong?</div><div class="answer"><b>{summary.get("title", "Investigation finding")}</b></div><p>{summary.get("summary", "The model recorded an interpretation of the persisted evidence.")}</p><p><b>Why does ECHO think this happened?</b><br>{root}<br>{evidence_text}</p><p><b>What uncertainty remains?</b><br>{uncertainty_text}</p><p><b>What should happen next?</b><br>{intent.get("recommended_action", "Not recorded")}</p><p>Mode: <b>{mode_label}</b> · Model: <b>{", ".join(sorted(model_names)) if model_names else "Not recorded"}</b> · Confidence: <b>{confidence_text}</b></p></div>', unsafe_allow_html=True)
    with intel_right:
        st.markdown('<div class="card"><div class="card-title">Recorded evidence path</div>', unsafe_allow_html=True)
        render_timeline(data)
        st.markdown('</div>', unsafe_allow_html=True)
    if not data["events"]:
        st.info("No investigation events are recorded for this incident; ECHO will not invent a diagnostic sequence.")

    st.markdown(f'<div id="recovery" class="story-section" style="--delay:.95s"><div class="story-heading"><span class="story-number">4</span><h2>Recovery & verification</h2></div><div class="story-intro">The recovery plan is separated from execution. Deterministic safety checks decide which records can change, then an independent verifier checks the actual destination state.</div></div>', unsafe_allow_html=True)
    applied_count = sum(1 for repair in data["repairs"] if repair.get("safety_status") == "safe" and data["plan"].get("status") == "executed")
    recovery_cols = st.columns(5)
    recovery_cols[0].markdown(f'<div class="card"><div class="card-title">Proposed</div><div class="answer">{len(data["repairs"])}</div><div class="metric-note">records considered</div></div>', unsafe_allow_html=True)
    recovery_cols[1].markdown(f'<div class="card"><div class="card-title">Approved</div><div class="answer">{plan.get("safe_count", 0)}</div><div class="metric-note">safe by policy</div></div>', unsafe_allow_html=True)
    recovery_cols[2].markdown(f'<div class="card"><div class="card-title">Applied</div><div class="answer">{applied_count}</div><div class="metric-note">actually changed</div></div>', unsafe_allow_html=True)
    recovery_cols[3].markdown(f'<div class="card"><div class="card-title">Verified</div><div class="answer">{verification.get("verified_repairs", 0)}</div><div class="metric-note">independently checked</div></div>', unsafe_allow_html=True)
    recovery_cols[4].markdown(f'<div class="card"><div class="card-title">Blocked</div><div class="answer">{plan.get("unsafe_count", 0)}</div><div class="metric-note">human review</div></div>', unsafe_allow_html=True)
    if rows:
        comparison_table(rows, limit=5, phase="recovery")
    if passed:
        st.markdown(f'<div class="result-banner"><div class="result-title">Recovery verified</div><div class="result-copy">{verification.get("verified_repairs", 0)} repaired record(s) now match the trusted Source Dataset. Independent verification passed. The original corruption finding remains preserved in history.</div></div>', unsafe_allow_html=True)
    elif status == "escalated":
        st.markdown(f'<div class="result-banner bad"><div class="result-title">Recovery escalated safely</div><div class="result-copy">ECHO preserved the uncertain records and did not overwrite them. Human review remains required.</div></div>', unsafe_allow_html=True)
    elif verification:
        st.markdown('<div class="result-banner bad"><div class="result-title">Verification did not pass</div><div class="result-copy">The persisted verifier did not establish a successful recovery. The incident remains unresolved.</div></div>', unsafe_allow_html=True)
    else:
        st.info("No persisted verification result is available yet.")
    if data["pipeline"].get("status") == "quarantined":
        pipeline_title, pipeline_note = pipeline_presentation(data)
        st.warning(f"{pipeline_title}: {pipeline_note}")

    with st.expander("Advanced Details", expanded=False):
        st.caption("Raw logs, JSON, technical IDs, full evidence, notifications, and synchronization history are kept here so the primary story stays clear.")
        st.markdown("**Raw incident alert and recorded outcome**")
        st.json({"alert": data["alert"], "outcome": data["outcome"], "plan": data["plan_json"], "safety": data["safety"]})
        st.markdown("**Investigation events and synchronization logs**")
        st.json({"events": data["events"], "logs": data["logs"]})
        st.markdown("**Full persisted repair evidence**")
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.markdown("**Technical identifiers**")
        st.json({"incident_id": incident.get("id"), "run_id": run.get("id"), "pipeline_id": incident.get("pipeline_id"), "plan_id": data["plan"].get("id"), "verification_id": data["verification"].get("id")})
        render_history(fetch(echo_conn, "SELECT * FROM sync_runs ORDER BY COALESCE(finished_at, started_at) DESC"))


FEATURED_SCENARIO_IDS = ["SCENARIO-01", "SCENARIO-02", "SCENARIO-05"]
FEATURED_SCENARIO_META = {
    "SCENARIO-01": {"title": "Healthy Data", "category": "Healthy baseline", "icon": "shield"},
    "SCENARIO-02": {"title": "Auto Recovery", "category": "Targeted numeric corruption", "icon": "search"},
    "SCENARIO-03": {"title": "Partial Text Corruption", "category": "Text-field integrity", "icon": "file"},
    "SCENARIO-04": {"title": "Complete Data Corruption", "category": "Persistent pipeline defect", "icon": "database"},
    "SCENARIO-05": {"title": "Human Review", "category": "Unsafe conflict", "icon": "shield"},
}


def scenario_catalog(*, featured_only: bool = False) -> list[dict[str, Any]]:
    """Read the active registry without executing scenarios.

    The registry retains all five reproducible cases for history/evaluation;
    the local demo surface intentionally features only the three safe-to-show
    cases selected for the hackathon walkthrough.
    """
    cards = []
    registry = json.loads((PACKAGE_DIR / "scenario_registry.json").read_text())
    for entry in registry.get("active_scenarios", []):
        case_id = entry["case_id"]
        patch = json.loads((PACKAGE_DIR / entry["patch_path"]).read_text())
        alert_path = PACKAGE_DIR / "alerts" / f"{case_id}.json"
        alert = json.loads(alert_path.read_text()) if alert_path.is_file() else {}
        setup = patch.get("scenario_setup") or {}
        category = entry.get("category") or FEATURED_SCENARIO_META.get(case_id, {}).get("category", "Scenario")
        metadata = FEATURED_SCENARIO_META.get(case_id, {})
        display_title = metadata.get("title") if case_id in FEATURED_SCENARIO_IDS else entry.get("title")
        cards.append({"case_id": case_id, "title": display_title or case_id, "icon": metadata.get("icon"), "incident_id": None, "category": category, "data_type": entry.get("data_type", "Supported fields"), "description": entry.get("description") or "Reproducible synchronization scenario", "severity": alert.get("severity") or "unknown", "featured": case_id in FEATURED_SCENARIO_IDS})
    if featured_only:
        cards = [card for card in cards if card["featured"]]
    return sorted(cards, key=lambda card: (0 if card["case_id"] in FEATURED_SCENARIO_IDS else 1, FEATURED_SCENARIO_IDS.index(card["case_id"]) if card["case_id"] in FEATURED_SCENARIO_IDS else card["case_id"]))


def investigation_summary(data: dict[str, Any]) -> dict[str, Any]:
    intent = data["outcome"].get("intent") or {}
    rows = comparison_rows(data)
    source_values = [int(row["_source"]) for row in rows if row.get("Field") == "amount_halalas" and row.get("_source") is not None]
    before_values = [int(row["_before"]) for row in rows if row.get("Field") == "amount_halalas" and row.get("_before") is not None]
    ratios = {before // source for source, before in zip(source_values, before_values) if source and before and before % source == 0 and before // source > 1}
    confidence = intent.get("confidence")
    legacy_incomplete = "max_tool_calls" in (intent.get("uncertainty") or []) and "model_submitted" not in intent
    complete = (
        intent.get("investigation_state", "complete" if intent else "unknown") == "complete"
        and bool(intent.get("model_submitted", not legacy_incomplete))
        and not legacy_incomplete
    )
    confidence_sufficient = isinstance(confidence, (int, float)) and float(confidence) >= MIN_INVESTIGATION_CONFIDENCE
    has_error = bool(intent.get("investigation_error")) or any(event.get("kind") == "investigation_error" for event in data["events"])
    if has_error:
        root = "AI Investigation Unavailable"
        title = root
        summary_text = "The model request failed before ECHO received a complete structured interpretation."
    elif not complete:
        root = "AI Investigation Incomplete"
        title = root
        summary_text = "The model did not submit a complete structured interpretation, so ECHO requires human review."
    else:
        title = str(intent.get("title") or "Investigation finding")
        summary_text = str(intent.get("summary") or intent.get("finding_summary") or "The model recorded an interpretation of the persisted evidence.")
        root = str(intent.get("suspected_root_cause") or cause_text(intent.get("suspected_cause")))
    # The model can recommend review because it is uncertain about the exact
    # mechanism. That is distinct from whether the proposed record repair is
    # safe. The persisted deterministic plan is authoritative for the latter.
    # `plan` is the SQL recovery_plans row; the decision and safety gate are
    # persisted separately as parsed proposal/safety JSON.  Use the same
    # authoritative records that the recovery view and worker use.
    policy_safety = data.get("safety", {})
    policy_plan = data.get("plan_json", {})
    policy_allows_recovery = bool(policy_safety.get("auto_execute")) and policy_plan.get("decision") in {"restore", "quarantine_and_restore"}
    safe_to_recommend = complete and confidence_sufficient and not has_error
    strategy = policy_plan.get("decision") if policy_allows_recovery else "human_review"
    return {
        "intent": intent,
        "rows": rows,
        "root": root,
        "title": title,
        "summary": summary_text,
        "observed_issue": intent.get("observed_issue") or "Persisted source/destination comparison is shown in the Detection step.",
        "supporting_evidence": intent.get("supporting_evidence") or [],
        "safety_concerns": intent.get("safety_concerns") or [],
        "human_review_reason": intent.get("human_review_reason"),
        "strategy": strategy,
        "model_strategy": intent.get("strategy"),
        "ratios": sorted(ratios),
        "pattern": observed_pattern_text(rows, sorted(ratios)),
        "confidence_sufficient": confidence_sufficient,
        "investigation_complete": complete,
        "investigation_error": has_error,
        "investigation_failure_kind": "model_execution_failure" if has_error else "incomplete_report" if not complete else None,
        "recovery_reason": "The model execution failed before a report was received." if has_error else "The investigation did not produce a complete validated report." if not complete else "Deterministic safety policy evaluated the persisted evidence.",
    }


def searchable_rows(rows: list[dict[str, Any]], key: str, *, phase: str = "recovery") -> None:
    query = st.text_input("Search record IDs or fields", key=key, placeholder="e.g. TX-002613 or amount_halalas")
    filtered = [row for row in rows if not query.strip() or query.strip().lower() in " ".join(str(value) for value in row.values()).lower()]
    st.caption(f"Showing {len(filtered)} of {len(rows)} persisted records.")
    if filtered:
        if phase == "detection":
            display_rows = [{
                "Record": row["Transaction"],
                "Field": row["Field"],
                "Trusted source value": row["Original trusted value"],
                "Incorrect value": row["Corrupted destination value"],
                "Discrepancy type": row["Discrepancy type"],
            } for row in filtered]
        else:
            display_rows = [{
                "Record": row["Transaction"],
                "Field": row["Field"],
                "Trusted source value": row["Original trusted value"],
                "Incorrect value": row["Corrupted destination value"],
                "Suggested correction": row["Proposed replacement"],
                "Value after repair": row["Applied replacement"],
                "Verification": row["Verified result"],
            } for row in filtered]
        st.dataframe(display_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No persisted records match that search.")


def investigation_field(label: str, value: Any, clamp_class: str) -> str:
    """Render concise visible AI text while keeping the full value in Technical Evidence."""
    text = str(value or "Not recorded")
    return (
        f'<div class="investigation-field"><div class="investigation-field-label">{html.escape(label)}</div>'
        f'<div class="investigation-clamp {clamp_class}" title="{html.escape(text)}">{html.escape(text)}</div></div>'
    )


def assistant_field(icon: str, label: str, value: Any, clamp_class: str) -> str:
    """Render one compact, escaped assistant response field."""
    text = str(value or "Not recorded")
    return (
        f'<div class="assistant-field"><span class="assistant-field-icon">{html.escape(icon)}</span><div>'
        f'<div class="assistant-field-label">{html.escape(label)}</div>'
        f'<div class="assistant-field-copy investigation-clamp {clamp_class}" title="{html.escape(text)}">{html.escape(text)}</div>'
        f'</div></div>'
    )


def assistant_problem(title: Any, summary: Any) -> str:
    """Render the model title separately from its concise explanation."""
    title_text, summary_text = str(title or "Investigation finding"), str(summary or "Not recorded")
    return (
        f'<div class="assistant-field"><span class="assistant-field-icon">error</span><div>'
        f'<div class="assistant-field-label">Found the problem</div>'
        f'<div class="investigation-clamp investigation-title-clamp" title="{html.escape(title_text)}">{html.escape(title_text)}</div>'
        f'<div class="assistant-field-copy investigation-clamp investigation-summary-clamp" title="{html.escape(summary_text)}">{html.escape(summary_text)}</div>'
        f'</div></div>'
    )


def concise_points(value: Any, limit: int) -> list[str]:
    """Prepare short visible bullets without changing the persisted finding."""
    values = value if isinstance(value, list) else [value]
    points: list[str] = []
    for item in values:
        text = str(item or "").strip()
        for part in re.split(r"(?<=[.!?])\s+|\n+", text):
            part = part.strip(" •-")
            if part:
                words = part.split()
                points.append(" ".join(words[:12]) + ("…" if len(words) > 12 else ""))
                if len(points) >= limit:
                    return points
    return points or ["Not recorded."]


def assistant_bullets(icon_name: str, label: str, value: Any, limit: int) -> str:
    points = concise_points(value, limit)
    items = "".join(f"<li>{html.escape(point)}</li>" for point in points)
    return (
        f'<div class="assistant-field"><span class="assistant-field-icon">{html.escape(icon_name)}</span><div>'
        f'<div class="assistant-field-label">{html.escape(label)}</div><ul class="assistant-list">{items}</ul>'
        f'</div></div>'
    )


def scenario_card_label(card: dict[str, Any]) -> str:
    """Keep selectable scenario cards equal and readable without executing them."""
    return str(card.get("title", card.get("case_id", "Scenario")))


def reset_workflow_selection(*, open_workflow: bool = True) -> None:
    """Return to scenario selection without deleting history or resetting runtime data."""
    for key in ("sync_replay", "echo_reveal", "recovery_reveal", "show_all_discrepancies", "show_all_repairs"):
        st.session_state[key] = False
    st.session_state["workflow_step"] = 0
    st.session_state["workflow_case"] = None
    st.session_state["healthy_run_id"] = None
    st.session_state["workflow_reset"] = True
    st.session_state["workflow_open"] = open_workflow
    st.session_state["workflow_execution_notice"] = None


def render_healthy_workflow(run: dict[str, Any], case_id: str) -> None:
    """Show the real healthy execution even though it intentionally creates no incident."""
    total = int(run.get("records_processed") or 0)
    stage = min(int(st.session_state.get("workflow_step", 0)), 3)
    labels = ["Synchronization", "Detection", "AI Investigation", "Recovery & Verification"]
    st.markdown(f'<div class="replay-badge">Recorded healthy run · {html.escape(case_id)} · no incident or API call was required</div>', unsafe_allow_html=True)
    steps = st.columns(4)
    for index, label in enumerate(labels):
        with steps[index]:
            if st.button(f"{index + 1}  {label}", key=f"healthy_step_{index}", type="primary" if index == stage else "secondary", disabled=index > stage, use_container_width=True):
                st.session_state["workflow_step"] = index
                st.rerun()
    if stage == 0:
        st.markdown('<div class="stage-panel"><div class="stage-kicker">Replay · Stage 1 of 4</div><div class="stage-title">Synchronization completed</div><div class="stage-copy">The trusted source and destination synchronized successfully. This is the actual recorded run, not a new transfer.</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="sync-progress"><div class="sync-progress-head"><span>Synchronization completed</span><span>100%</span></div><div class="sync-progress-note">{total:,} records processed in the persisted run.</div></div>', unsafe_allow_html=True)
        st.progress(1.0)
        st.markdown(f'<div class="check">✓ Execution: <b>{html.escape(status_label(run.get("execution_status")))}</b> · Integrity: <b>{html.escape(status_label(run.get("integrity_status")))}</b></div>', unsafe_allow_html=True)
    elif stage == 1:
        st.markdown('<div class="stage-panel"><div class="stage-kicker">Replay · Stage 2 of 4</div><div class="stage-title">No discrepancies detected</div><div class="stage-copy">ECHO compared the persisted source and destination evidence. Every checked record matched.</div></div>', unsafe_allow_html=True)
        a, b, c = st.columns(3)
        a.markdown(f'<div class="card"><div class="card-title">Records compared</div><div class="answer">{total:,}</div></div>', unsafe_allow_html=True)
        b.markdown(f'<div class="card"><div class="card-title">Matching records</div><div class="answer">{total:,}</div></div>', unsafe_allow_html=True)
        c.markdown('<div class="card"><div class="card-title">Discrepancies</div><div class="answer">0</div></div>', unsafe_allow_html=True)
    elif stage == 2:
        st.markdown('<div class="stage-panel"><div class="stage-kicker">Replay · Stage 3 of 4</div><div class="stage-title">AI investigation not needed</div><div class="stage-copy">Because integrity passed with zero discrepancies, ECHO did not spend investigation tokens or invent a diagnosis.</div></div>', unsafe_allow_html=True)
        st.markdown('<div class="result-banner success"><div class="result-title">Healthy data confirmed</div><div class="result-copy">No issue was found, so no recovery plan was created.</div></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="stage-panel"><div class="stage-kicker">Replay · Stage 4 of 4</div><div class="stage-title">Recovery &amp; Verification</div><div class="stage-copy">There was nothing to repair. The healthy result is complete without a recovery action.</div></div>', unsafe_allow_html=True)
        st.markdown('<div class="completion-card"><h3>Integrity Verified — No Recovery Needed</h3><p>All persisted records matched and ECHO made zero changes.</p></div>', unsafe_allow_html=True)
    if stage < 3:
        if st.button(f"Continue  →  {labels[stage + 1]}", type="primary", use_container_width=True, key="healthy_continue"):
            st.session_state["workflow_step"] = stage + 1
            st.rerun()
    else:
        project_column, history_column = st.columns([1, 1])
        if project_column.button("Back to Project", type="primary", use_container_width=True, key="healthy_back_to_project"):
            reset_workflow_selection(open_workflow=False)
            st.rerun()
        if history_column.button("View History", type="secondary", use_container_width=True, key="healthy_view_history"):
            st.session_state["page"] = "History"
            st.session_state["workflow_open"] = False
            st.rerun()
        if st.button("Restart Replay", key="healthy_restart"):
            st.session_state["workflow_step"] = 0
            st.rerun()
        if st.button("Reset & choose another scenario", key="healthy_reset"):
            reset_workflow_selection()
            st.rerun()


def render_incident_workflow(data: dict[str, Any] | None) -> None:
    """Render one persisted incident stage at a time; navigation never executes work."""
    st.markdown('<div class="eyebrow">Workspace · incident workflow</div>', unsafe_allow_html=True)
    if st.session_state.get("workflow_reset"):
        data = None
    if data:
        incident_key = data["incident"].get("id")
        if st.session_state.get("story_incident") != incident_key:
            st.session_state["story_incident"] = incident_key
            st.session_state["sync_replay"] = False
            st.session_state["echo_reveal"] = False
            st.session_state["recovery_reveal"] = False
            st.session_state["workflow_step"] = 0
            st.session_state["show_all_discrepancies"] = False
            st.session_state["show_all_repairs"] = False
    if "workflow_step" not in st.session_state:
        st.session_state["workflow_step"] = 0

    if st.button("Back to Workspace", key="back_to_workspace"):
        st.session_state["workflow_open"] = False
        st.rerun()
    st.title("Incident workflow")
    st.markdown('<div class="subtitle">A guided view of the recorded synchronization, investigation, and recovery evidence.</div>', unsafe_allow_html=True)
    if st.session_state.get("workflow_execution_notice"):
        st.warning(f"The run completed with a recorded investigation issue: {st.session_state['workflow_execution_notice']}")

    cards = scenario_catalog(featured_only=True)
    case_options = [card["case_id"] for card in cards]
    replay_started = bool(st.session_state.get("sync_replay"))
    if not replay_started and case_options:
        with st.expander("Scenario setup · select or execute a scenario", expanded=True):
            featured_cards = [card for card in cards if card.get("featured")]
            selected_case = (
                st.session_state.get("workflow_case")
                or (data or {}).get("incident", {}).get("case_id")
                or (case_options[0] if case_options else "")
            )
            st.caption("Choose a scenario. Selecting a card does not execute or reset anything.")
            featured_columns = st.columns(3)
            for column, card in zip(featured_columns, featured_cards):
                with column:
                    is_selected = card["case_id"] == selected_case
                    label = scenario_card_label(card)
                    if st.button(label, type="primary" if is_selected else "secondary", key=f'workflow_featured_{card["case_id"]}', use_container_width=True):
                        st.session_state["workflow_case"] = card["case_id"]
                        st.session_state["healthy_run_id"] = None
                        st.session_state["workflow_reset"] = True
                        st.rerun()
                    st.caption(card["description"])
            workflow_case = selected_case
            selected_card = next((card for card in cards if card["case_id"] == workflow_case), None)
            if selected_card:
                st.caption(f'{selected_card["category"]} · {selected_card["description"]}')
            import echo.agent.openai_client as client
            live_available = bool(client.OPENAI_API_KEY)
            workflow_mode = st.selectbox("Investigation mode", ["Mock (offline)"] + (["Live OpenAI"] if live_available else []), key="workflow_mode")
            confirm_run = st.checkbox("Confirm explicit scenario execution and runtime reset", key="workflow_confirm")
            if st.session_state.get("workflow_execution_in_progress"):
                st.info("ECHO is already processing this scenario. Keep this window open while the persisted result is prepared.")
            if st.button("Run Scenario", disabled=not can_start_execution(confirmed=confirm_run, in_progress=bool(st.session_state.get("workflow_execution_in_progress"))), key="workflow_run_scenario"):
                st.session_state["workflow_execution_in_progress"] = True
                st.session_state["workflow_execution_error"] = None
                st.session_state["workflow_execution_notice"] = None
                try:
                    with st.status("ECHO is processing the scenario…", expanded=True) as execution_status:
                        execution_status.write("Synchronizing Data · in progress")
                        setup = load_case(workflow_case)
                        records = int((setup.get("findings") or {}).get("compared_records") or setup.get("transactions") or 0)
                        execution_status.write(f"Synchronizing Data · complete ({records:,} records prepared)")
                        discrepancy_count = int((setup.get("findings") or {}).get("discrepancy_count") or 0)
                        execution_status.write(f"Detecting Discrepancies · complete ({discrepancy_count:,} differences recorded)")
                        if setup.get("incident_id"):
                            execution_status.write("AI Investigating · in progress")
                            result = run_worker(workflow_mode)
                            execution_status.write("AI Investigating · persisted result received")
                            execution_status.write("Recovery & Verification · reading the recorded outcome")
                        else:
                            result = None
                            execution_status.write("AI Investigating · not needed because integrity passed")
                            execution_status.write("Recovery & Verification · not needed")

                        run_id = setup.get("run_id") or (result or {}).get("run_id")
                        persisted_run = one(echo_conn, "SELECT id FROM sync_runs WHERE id=?", (run_id,)) if run_id else None
                        incident_id = result.get("incident_id") if isinstance(result, dict) else None
                        persisted_incident = one(echo_conn, "SELECT id FROM incidents WHERE id=?", (incident_id,)) if incident_id else None
                        incident_id = validate_execution_target(setup, result, persisted_run, persisted_incident)
                        if isinstance(result, dict) and result.get("error"):
                            st.session_state["workflow_execution_notice"] = str(result["error"])
                            execution_status.write("Investigation completed with a recorded error; opening the persisted review state")
                        execution_status.update(label="Processing complete · opening persisted results", state="complete")
                    st.session_state["last_result"] = {"setup": setup, "result": result}
                    st.session_state["selected_incident"] = incident_id
                    st.session_state["healthy_run_id"] = setup.get("run_id") if result is None else None
                    st.session_state["workflow_case"] = workflow_case
                    st.session_state["workflow_open"] = True
                    st.session_state["workflow_reset"] = False
                    st.session_state["story_incident"] = None
                    st.session_state["workflow_step"] = 0
                except Exception as exc:
                    st.session_state["workflow_execution_error"] = str(exc)
                finally:
                    st.session_state["workflow_execution_in_progress"] = False
                if st.session_state.get("workflow_execution_error"):
                    st.error(f"Scenario execution failed: {st.session_state['workflow_execution_error']}")
                    st.caption("No results view was opened. Check the error above, then retry the explicit Run Scenario action if safe.")
                else:
                    st.rerun()

    if not data and st.session_state.get("healthy_run_id"):
        healthy_run = one(echo_conn, "SELECT * FROM sync_runs WHERE id=?", (st.session_state["healthy_run_id"],))
        if healthy_run:
            render_healthy_workflow(healthy_run, st.session_state.get("workflow_case", "SCENARIO-01"))
            return
    if not data:
        st.markdown('<div class="empty-card">Select a persisted incident from the sidebar to open its evidence story.</div>', unsafe_allow_html=True)
        return
    incident, run = data["incident"], data["run"]
    if st.button("Restart replay", key="restart_story"):
        st.session_state["sync_replay"] = False
        st.session_state["echo_reveal"] = False
        st.session_state["recovery_reveal"] = False
        st.session_state["workflow_step"] = 0
        st.session_state["show_all_discrepancies"] = False
        st.session_state["show_all_repairs"] = False
        st.rerun()

    max_step = 0
    if st.session_state.get("sync_replay"):
        max_step = 1
    if st.session_state.get("echo_reveal"):
        max_step = 2
    if st.session_state.get("recovery_reveal"):
        max_step = 3
    current_step = min(int(st.session_state.get("workflow_step", 0)), max_step)
    st.session_state["workflow_step"] = current_step
    stage_labels = ["Synchronization", "Detection", "AI Investigation", "Recovery & Verification"]
    step_columns = st.columns(4)
    for index, label in enumerate(stage_labels):
        with step_columns[index]:
            if st.button(f"{index + 1}  {label}", key=f"workflow_step_{index}", type="primary" if index == current_step else "secondary", disabled=index > max_step, use_container_width=True):
                st.session_state["workflow_step"] = index
                st.rerun()

    if current_step > 0:
        st.markdown(f'<div class="replay-badge">Recorded replay · {incident.get("case_id", incident.get("id"))} · no new sync or API call</div>', unsafe_allow_html=True)

    if current_step == 0:
        st.markdown('<div class="step-heading"><span>01</span><div><h2>Synchronization</h2><p>Replay the recorded source-to-destination transfer.</p></div></div>', unsafe_allow_html=True)
        records_processed = int(run.get("records_processed") or 0)
        execution_succeeded = str(run.get("execution_status") or "").lower() in {"succeeded", "success", "completed"}
        progress_value = 1.0 if replay_started and execution_succeeded else 0.0
        progress_label = "Synchronization completed" if progress_value else "Ready to replay recorded synchronization"
        progress_note = f"{records_processed:,} records processed in the persisted run." if progress_value else "This replay will not start a new transfer or call OpenAI."
        st.markdown(f'<div class="sync-progress"><div class="sync-progress-head"><span>{progress_label}</span><span>{int(progress_value * 100)}%</span></div><div class="sync-progress-note">{progress_note}</div></div>', unsafe_allow_html=True)
        st.progress(progress_value)
        if not replay_started:
            st.markdown('<div class="next-step-card"><strong>Next: start the recorded replay</strong><p>This is presentation-only evidence. It will not run a new synchronization or call OpenAI.</p></div>', unsafe_allow_html=True)
            if st.button("Replay Sync  →", type="primary", use_container_width=True, key="sync_story"):
                st.session_state["sync_replay"] = True
                st.session_state["workflow_reset"] = False
                st.rerun()
            return
        render_pipeline_visual(data, recovered=False)
        render_sync_preview(data, destination=True)
        execution = status_label(run.get("execution_status"))
        integrity = status_label(run.get("integrity_status"))
        a, b, c = st.columns(3)
        a.markdown(f'<div class="check"><b>Execution</b><br>{execution}</div>', unsafe_allow_html=True)
        b.markdown(f'<div class="check {"bad" if run.get("integrity_status") == "corrupted" else ""}"><b>Integrity</b><br>{integrity}</div>', unsafe_allow_html=True)
        c.markdown(f'<div class="check"><b>Records processed</b><br>{int(run.get("records_processed") or 0):,}</div>', unsafe_allow_html=True)
        if st.button("Continue  →  Detection", type="primary", use_container_width=True, key="continue_detection"):
            st.session_state["echo_reveal"] = True
            st.session_state["workflow_step"] = 1
            st.rerun()
        return

    summary = investigation_summary(data)
    rows = summary["rows"]
    plan = data["plan_json"]
    verification = data["verification_json"]
    findings = data["alert"].get("monitor_findings") or {}
    discrepancies = int(plan.get("mismatch_count", findings.get("amount_discrepancy_count", len(rows))) or 0)
    total = int((one(finance_conn, "SELECT COUNT(*) AS n FROM transactions") or {}).get("n", 0) or 0)

    if current_step == 1:
        st.markdown('<div class="step-heading"><span>02</span><div><h2>Detection</h2><p>Compare persisted source evidence with the destination snapshot.</p></div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="result-focus"><strong>{discrepancies:,} discrepancies detected</strong><span>{max(0, total - discrepancies):,} of {total:,} records matched.</span></div>', unsafe_allow_html=True)
        if rows:
            comparison_table(rows, limit=3, phase="detection")
            if st.button("View All Discrepancies", key="view_all_discrepancies"):
                st.session_state["show_all_discrepancies"] = not st.session_state.get("show_all_discrepancies", False)
            if st.session_state.get("show_all_discrepancies"):
                with st.expander("All persisted discrepancies", expanded=True):
                    searchable_rows(rows, "discrepancy_search", phase="detection")
        else:
            st.markdown('<div class="empty-card">No affected records were recorded for this incident.</div>', unsafe_allow_html=True)
        previous, continue_column = st.columns([1, 2])
        if previous.button("← Previous", key="previous_detection"):
            st.session_state["workflow_step"] = 0
            st.rerun()
        if continue_column.button("Continue  →  AI Investigation", type="primary", use_container_width=True, key="continue_investigation"):
            st.session_state["workflow_step"] = 2
            st.rerun()
        return

    intent = summary["intent"]
    confidence = intent.get("confidence")
    model_names = {str(row.get("model")) for row in data["usage"] if row.get("model")}
    model_names |= {str(parse_json(event.get("payload_json")).get("model")) for event in data["events"] if event.get("kind") == "investigation_started" and parse_json(event.get("payload_json")).get("model")}
    mode = "Live OpenAI" if any(not model.endswith("mock") for model in model_names) else "Mock investigation — no live LLM"

    if current_step == 2:
        st.markdown('<div class="step-heading"><span>03</span><div><h2>AI Investigation</h2><p>Review the recorded finding and the evidence behind the recommendation.</p></div></div>', unsafe_allow_html=True)
        finding_title = "Investigation incomplete" if summary["investigation_error"] or not summary["investigation_complete"] else summary.get("title", "Investigation finding")
        finding_summary = summary["recovery_reason"] if summary["investigation_error"] or not summary["investigation_complete"] else summary.get("summary", "The model recorded an interpretation of the persisted evidence.")
        evidence_count = sum(1 for event in data["events"] if event.get("kind") == "tool_executed")
        confidence_label = f"{float(confidence):.0%}" if confidence is not None and not summary["investigation_error"] else ("Not established" if confidence is None else "Unavailable")
        confidence_badge = f'<span class="confidence-badge">Confidence · {confidence_label}</span>'
        model_recommendation = intent.get("recommended_action") if summary["investigation_complete"] and not summary["investigation_error"] else "No AI recommendation was completed."
        policy_allows_recovery = bool(data.get("safety", {}).get("auto_execute")) and plan.get("decision") in {"restore", "quarantine_and_restore"}
        review_reason = summary.get("human_review_reason") if not policy_allows_recovery else None
        if summary["investigation_error"] or not summary["investigation_complete"]:
            safety_decision = "Blocked — investigation incomplete"
            safety_reason = summary["recovery_reason"]
            decision_class = "blocked"
            review_reason = review_reason or summary["recovery_reason"]
        elif summary["strategy"] == "human_review" or plan.get("unsafe_count"):
            safety_decision = "Human Review Required"
            safety_reason = review_reason or "Deterministic safety checks did not authorize automatic recovery."
            review_reason = safety_reason
            decision_class = "review"
        else:
            safety_decision = "Automatic recovery allowed by safety checks"
            safety_reason = "ECHO's deterministic policy approved eligible changes; independent verification must still pass."
            decision_class = ""
        st.markdown(
            f'<div class="investigation-card assistant-card"><div class="assistant-header"><span class="assistant-icon">psychology</span><div><div class="assistant-name">ECHO AI</div><div class="assistant-mode">{html.escape(mode)}</div></div>{confidence_badge}</div><div class="assistant-rule"></div>'
            f'{assistant_bullets("error", "Problem", [finding_title, finding_summary], 2)}'
            f'{assistant_bullets("search_check", "Likely cause", [summary["root"], *(summary.get("supporting_evidence") or [])] if summary["investigation_complete"] and not summary["investigation_error"] else "No complete AI interpretation was received.", 2)}'
            f'{assistant_bullets("build", "Recommended fix", model_recommendation, 2)}'
            f'<div class="investigation-decision {decision_class}"><b>ECHO safety decision:</b> {html.escape(safety_decision)}<br>{html.escape(safety_reason)}</div></div>',
            unsafe_allow_html=True,
        )
        with st.expander(f"Technical Evidence · {len(rows)} discrepancy rows · {evidence_count} diagnostic events", expanded=False):
            st.markdown("**Full LLM-generated finding**")
            for label, key in (("Title", "title"), ("Summary", "summary"), ("Observed issue", "observed_issue"), ("Suspected root cause", "suspected_root_cause"), ("Supporting evidence", "supporting_evidence"), ("Recommended action", "recommended_action"), ("Safety concerns", "safety_concerns"), ("Human review reason", "human_review_reason")):
                value = intent.get(key)
                if isinstance(value, list):
                    value = " ".join(str(item) for item in value)
                st.markdown(f"**{label}:** {value or 'Not recorded'}")
            st.markdown(f'<p><b>Observed issue from persisted alert:</b> {data["alert"].get("message", "Integrity alert recorded")}</p><p><b>Recorded model recommendation:</b> {status_label(summary["model_strategy"]) if summary["model_strategy"] else "Not submitted"}</p>', unsafe_allow_html=True)
            render_timeline(data)
        previous, continue_column = st.columns([1, 2])
        if previous.button("← Previous", key="previous_investigation"):
            st.session_state["workflow_step"] = 1
            st.rerun()
        if continue_column.button("Continue  →  Recovery", type="primary", use_container_width=True, key="continue_recovery"):
            st.session_state["recovery_reveal"] = True
            st.session_state["workflow_step"] = 3
            st.rerun()
        return

    st.markdown('<div class="step-heading"><span>04</span><div><h2>Recovery &amp; Verification</h2><p>See what was restored, independently verified, and quarantined.</p></div></div>', unsafe_allow_html=True)
    repairs = data["repairs"]
    applied = sum(1 for repair in repairs if repair.get("safety_status") == "safe" and data["plan"].get("status") == "executed")
    verified = int(verification.get("verified_repairs") or 0)
    st.markdown(f'<div class="result-focus"><strong>{verified:,} records independently verified</strong><span>{len(repairs):,} proposed · {applied:,} applied · {plan.get("unsafe_count", 0):,} blocked.</span></div>', unsafe_allow_html=True)
    healthy = discrepancies == 0 and str(run.get("integrity_status") or "").lower() == "healthy"
    safety_allows = bool(data.get("safety", {}).get("auto_execute")) and plan.get("decision") in {"restore", "quarantine_and_restore"}
    review_required = not safety_allows or bool(plan.get("unsafe_count")) or bool(incident.get("review_required"))
    review_reason = summary.get("human_review_reason") or "Deterministic safety checks did not authorize an automatic change."
    if summary["investigation_error"] or not summary["investigation_complete"]:
        st.warning(f"Recovery blocked: {summary['recovery_reason']}")
    elif review_required and applied == 0 and not healthy:
        awaiting = max(int(plan.get("unsafe_count", 0) or 0), len(rows))
        st.markdown(f'<div class="result-banner bad"><div class="result-title">Automatic Recovery Blocked — Human Approval Required</div><div class="result-copy">{html.escape(str(review_reason))}</div><div class="result-copy"><b>0</b> records repaired · <b>{awaiting}</b> awaiting review.</div></div>', unsafe_allow_html=True)
        if st.button("Open Human Review", type="secondary", key="open_human_review_recovery"):
            st.session_state["page"] = "Human Review"
            st.session_state["workflow_open"] = False
            st.rerun()
        if rows:
            first = rows[0]
            st.markdown(f'<div class="recovery-compare"><div class="recovery-value"><div class="label">Trusted source</div><div class="value">{html.escape(str(first["Original trusted value"]))}</div></div><div class="recovery-arrow">→</div><div class="recovery-value incorrect"><div class="label">Current destination · Not Modified</div><div class="value">{html.escape(str(first["Corrupted destination value"]))}</div></div></div>', unsafe_allow_html=True)
    pipeline_title, pipeline_note = pipeline_presentation(data)
    st.markdown(f'<div class="card quarantine-card"><div class="card-title">Pipeline status</div><div class="answer">{html.escape(pipeline_title)}</div><div class="node-note">{html.escape(pipeline_note)}</div></div>', unsafe_allow_html=True)
    if healthy:
        st.markdown('<div class="result-banner success"><div class="result-title">Healthy — No Recovery Needed</div><div class="result-copy">All persisted source and destination records matched. ECHO made no changes.</div></div>', unsafe_allow_html=True)
    elif verification.get("passed") and applied > 0:
        first = rows[0] if rows else None
        if first:
            st.markdown(f'<div class="recovery-compare"><div class="recovery-value incorrect"><div class="label">Incorrect value</div><div class="value">{html.escape(str(first["Corrupted destination value"]))}</div></div><div class="recovery-arrow">→</div><div class="recovery-value verified"><div class="label">Verified after repair</div><div class="value">{html.escape(str(first["Verified result"]))}</div></div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="result-banner success"><div class="result-title">Recovery Successful — Verification Passed</div><div class="result-copy">{verified} record(s) were restored and independently verified against the trusted Source Dataset.</div></div>', unsafe_allow_html=True)
    elif review_required and applied == 0:
        pass
    elif verification and not verification.get("passed"):
        st.markdown('<div class="result-banner bad"><div class="result-title">Recovery Failed</div><div class="result-copy">Independent verification did not establish a successful recovery.</div></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="result-banner bad"><div class="result-title">Recovery unresolved</div><div class="result-copy">No verified recovery outcome is recorded for this incident.</div></div>', unsafe_allow_html=True)
    with st.expander("Evidence · repairs and verification", expanded=False):
        if rows:
            comparison_table(rows, limit=3, phase="recovery")
            if st.button("View All Repairs", key="view_all_repairs"):
                st.session_state["show_all_repairs"] = not st.session_state.get("show_all_repairs", False)
            if st.session_state.get("show_all_repairs"):
                searchable_rows(rows, "repair_search", phase="recovery")
        st.json({"plan": data["plan_json"], "safety": data["safety"], "verification": data["verification_json"]})
    previous, project_column, history_column = st.columns([1, 1, 1])
    if previous.button("← Previous", key="previous_recovery"):
        st.session_state["workflow_step"] = 2
        st.rerun()
    if project_column.button("Back to Project", type="primary", use_container_width=True, key="back_to_project"):
        reset_workflow_selection(open_workflow=False)
        st.rerun()
    if history_column.button("View History", type="secondary", use_container_width=True, key="view_in_history"):
        st.session_state["page"] = "History"
        st.session_state["workflow_open"] = False
        st.rerun()
    if st.button("Reset & choose another scenario", key="reset_workflow_after_recovery"):
        reset_workflow_selection()
        st.rerun()


def render_workspace_home(incidents: list[dict[str, Any]], runs: list[dict[str, Any]]) -> None:
    source_count = int((one(finance_conn, "SELECT COUNT(*) AS n FROM transactions") or {}).get("n", 0) or 0)
    destination_count = int((one(analytics_conn, "SELECT COUNT(*) AS n FROM fact_transactions") or {}).get("n", 0) or 0)
    latest_run = runs[0] if runs else None
    if latest_run:
        latest_integrity = status_label(latest_run.get("integrity_status"))
        latest_note = f'Latest recorded run · {history_timestamp(latest_run.get("finished_at") or latest_run.get("started_at"))}'
    else:
        latest_integrity = "Not yet synchronized"
        latest_note = "No synchronization run has been recorded yet."
    st.markdown('<div class="eyebrow">Workspace · projects</div>', unsafe_allow_html=True)
    st.title("Projects")
    st.markdown('<div class="subtitle">A focused view of the data pipelines ECHO can investigate and recover.</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="project-overview"><div class="project-overview-header"><div><div class="eyebrow">Active project</div><h2>Finance Analytics</h2><p>Trusted Finance records synchronized to the Analytics destination.</p></div><div>{history_badge(latest_integrity, "healthy" if latest_integrity == "Healthy" else "neutral")}</div></div>'
        f'<div class="project-pipeline"><div class="project-node"><div class="project-node-label">Source</div><div class="project-node-value">Finance</div></div><div class="project-arrow">→</div><div class="project-node"><div class="project-node-label">Destination</div><div class="project-node-value">Analytics</div></div></div>'
        f'<div class="project-meta"><span>{source_count:,} source records</span><span>{destination_count:,} destination records</span><span>{html.escape(latest_note)}</span></div></div>',
        unsafe_allow_html=True,
    )
    open_column = st.columns([1, 1, 1])[1]
    if open_column.button("Open Project  →", type="primary", use_container_width=True, key="open_finance_project"):
        reset_workflow_selection()
        st.rerun()
    st.markdown('<div class="launch-note">Open Project leads to the three scenario cards and the guided four-step workflow. It does not make a synchronization or API call.</div>', unsafe_allow_html=True)


def render_history_page(runs: list[dict[str, Any]], incidents: list[dict[str, Any]]) -> None:
    st.markdown('<div class="eyebrow">History · recorded activity</div>', unsafe_allow_html=True)
    st.title("Activity registry")
    st.markdown('<div class="subtitle">A clear record of what synchronized, what ECHO found, and what happened next.</div>', unsafe_allow_html=True)

    incident_by_run = {row.get("run_id"): row for row in incidents}
    synthetic_run_ids: set[str] = set()
    history_csv = PACKAGE_DIR / "history" / "sync_runs.csv"
    if history_csv.is_file():
        with history_csv.open(newline="") as handle:
            synthetic_run_ids = {str(row.get("run_id")) for row in csv.DictReader(handle) if row.get("run_id")}

    query = st.text_input("Search history", placeholder="Search by run, incident, title, or status", label_visibility="collapsed")
    f1, f2, f3, f4 = st.columns([1.1, 1.1, 1.1, 1.35])
    execution_filter = f1.selectbox("Execution", ["All", "Succeeded", "Failed"])
    integrity_filter = f2.selectbox("Integrity", ["All", "Healthy", "Corrupted", "Failed"])
    outcome_filter = f3.selectbox("Outcome", ["All", "Healthy", "Recovered", "Failed", "Human Review"])
    review_filter = f4.selectbox("Human review", ["All", "Required", "Not required"])
    include_archived = st.checkbox("Show archived/reset runs", value=False, key="history_include_archived")
    st.caption("Archived runs stay preserved and are hidden from the default Actual ECHO Runs view.")

    all_rows: list[dict[str, Any]] = []
    details_by_run: dict[str, tuple[dict[str, Any], dict[str, Any] | None]] = {}
    for run in runs:
        run_id = str(run.get("id", "—"))
        incident = incident_by_run.get(run.get("id"))
        summary = incident_data(incident["id"]) if incident else None
        title = "No incident recorded" if not incident else (summary["alert"].get("message") or "Integrity incident detected")
        failure_reason = "—"
        root = "No incident recorded for this run."
        strategy = "—"
        mode = "Not recorded"
        model = "Not recorded"
        if summary:
            models = {str(row.get("model")) for row in summary["usage"] if row.get("model")}
            mode = "Live OpenAI" if any(not item.endswith("mock") for item in models) else "Mock investigation"
            model = ", ".join(sorted(models)) or "Not recorded"
            failure_logs = [log.get("message") for log in summary["logs"] if log.get("level") in {"ERROR", "WARN"}]
            failure_reason = failure_logs[0] if failure_logs else "Integrity discrepancy recorded"
            root = cause_text((summary["outcome"].get("intent") or {}).get("suspected_cause"))
            strategy = status_label(summary["plan_json"].get("decision"))
        execution = status_label(run.get("execution_status"))
        integrity = str(run.get("integrity_status") or "unknown").lower()
        recovery_status = str(incident.get("recovery_status") if incident else "not_applicable").lower()
        human_required = bool(incident and (incident.get("review_required") or recovery_status == "escalated" or incident_has_investigation_error(incident["id"])))
        if human_required:
            outcome = "Human Review"
            outcome_badge = history_badge("Human Review Required", "review")
        elif not incident:
            outcome = "Healthy"
            outcome_badge = history_badge("Not Applicable", "neutral")
        elif recovery_status == "verified":
            outcome = "Recovered"
            outcome_badge = history_badge("Recovered · Verified", "verified")
        elif recovery_status in {"failed", "rejected"}:
            outcome = "Failed"
            outcome_badge = history_badge("Failed", "failed")
        else:
            outcome = "Failed"
            outcome_badge = history_badge(status_label(recovery_status), "failed")
        integrity_label = "Healthy" if integrity == "healthy" else "Failed" if integrity == "failed" else "Corrupted" if integrity == "corrupted" else status_label(integrity)
        integrity_badge = history_badge(integrity_label, "healthy" if integrity == "healthy" else "failed" if integrity in {"failed", "corrupted"} else "neutral")
        searchable = " ".join(str(value) for value in (run, incident, title, failure_reason, root, strategy, mode)).lower()
        if execution_filter != "All" and execution != execution_filter:
            continue
        if integrity_filter != "All" and integrity_label != integrity_filter:
            continue
        if outcome_filter != "All" and outcome != outcome_filter:
            continue
        if review_filter == "Required" and not human_required:
            continue
        if review_filter == "Not required" and human_required:
            continue
        if query.strip().lower() not in searchable:
            continue
        all_rows.append({
            "run_id": run_id,
            "incident_id": incident.get("id") if incident else None,
            "date": history_timestamp(run.get("finished_at") or run.get("started_at")),
            "title": title,
            "integrity": integrity_label,
            "integrity_badge": integrity_badge,
            "outcome": outcome,
            "outcome_badge": outcome_badge,
            "human_required": human_required,
            # A scenario can materialize an incident using a baseline run ID;
            # the persisted incident linkage is the source of truth for that run's provenance.
            "run_type": "Synthetic Historical Data" if run_id in synthetic_run_ids and not incident else "Actual ECHO Run",
            "execution": execution,
            "failure_reason": failure_reason,
            "root": root,
            "strategy": strategy,
            "mode": mode,
            "model": model,
        })
        details_by_run[run_id] = (run, summary)

    # Deliberate scenario resets append full prior runtime evidence to this
    # archive. Keep those executions visible and distinct from bundled history.
    archive_path = execution_archive_path()
    if archive_path.is_file():
        for line in archive_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            if not include_archived:
                continue
            archived = json.loads(line)
            archived_incidents = {row.get("run_id"): row for row in archived.get("incidents", [])}
            for archived_run in archived.get("runs", []):
                original_id = str(archived_run.get("id", "—"))
                run_id = f'{original_id} · archived {archived.get("archived_at", "")[:19]}'
                archived_incident = archived_incidents.get(original_id)
                archived_alert = parse_json(archived_incident.get("alert_json")) if archived_incident else {}
                recovery_status = str(archived_incident.get("recovery_status") if archived_incident else "not_applicable").lower()
                human_required = bool(archived_incident and (archived_incident.get("review_required") or recovery_status == "escalated"))
                outcome = "Human Review" if human_required else "Healthy" if not archived_incident else "Recovered" if recovery_status == "verified" else "Failed"
                title = archived_incident.get("case_id") if archived_incident else "No incident recorded"
                execution = status_label(archived_run.get("execution_status"))
                integrity = "Healthy" if archived_run.get("integrity_status") == "healthy" else "Corrupted" if archived_run.get("integrity_status") == "corrupted" else status_label(archived_run.get("integrity_status"))
                if execution_filter != "All" and execution != execution_filter:
                    continue
                if integrity_filter != "All" and integrity != integrity_filter:
                    continue
                if outcome_filter != "All" and outcome != outcome_filter:
                    continue
                if review_filter == "Required" and not human_required:
                    continue
                if review_filter == "Not required" and human_required:
                    continue
                if query.strip().lower() not in f"{archived_run} {archived_incident} {title} {outcome} {integrity}".lower():
                    continue
                all_rows.append({
                    "run_id": run_id,
                    "incident_id": archived_incident.get("id") if archived_incident else None,
                    "date": history_timestamp(archived_run.get("finished_at") or archived_run.get("started_at")),
                    "title": title,
                    "integrity": integrity,
                    "integrity_badge": history_badge("Healthy", "healthy") if archived_run.get("integrity_status") == "healthy" else history_badge("Corrupted", "failed"),
                    "outcome": outcome,
                    "outcome_badge": history_badge("Human Review Required", "review") if outcome == "Human Review" else history_badge("Recovered · Verified", "verified") if outcome == "Recovered" else history_badge("Not Applicable", "neutral") if outcome == "Healthy" else history_badge("Failed", "failed"),
                    "human_required": human_required,
                    "run_type": "Archived Actual ECHO Run",
                    "execution": execution,
                    "failure_reason": archived_alert.get("message", "—"),
                    "root": "Archived evidence; reopen the original runtime for full investigation detail.",
                    "strategy": "Archived evidence",
                    "mode": "Recorded in archive",
                    "model": "Recorded in archive",
                })
                details_by_run[run_id] = ({"archived": True, "run": archived_run, "archive": archived}, None)

    actual_rows = [row for row in all_rows if row["run_type"] in {"Actual ECHO Run", "Archived Actual ECHO Run"}]
    synthetic_rows = [row for row in all_rows if row["run_type"] == "Synthetic Historical Data"]
    metric_scope = all_rows
    healthy_count = sum(row["integrity"] == "Healthy" for row in metric_scope)
    recovered_count = sum(row["outcome"] == "Recovered" for row in metric_scope)
    review_count = sum(row["outcome"] == "Human Review" for row in metric_scope)
    st.markdown('<div class="history-summary">', unsafe_allow_html=True)
    summary_cols = st.columns(4)
    metric("Total runs", len(metric_scope), "matching current filters", summary_cols[0])
    metric("Healthy", healthy_count, "integrity passed", summary_cols[1])
    metric("Recovered", recovered_count, "verified outcomes", summary_cols[2])
    metric("Needs review", review_count, "human intervention", summary_cols[3])
    st.markdown('</div>', unsafe_allow_html=True)

    def render_registry(rows: list[dict[str, Any]], key_prefix: str) -> None:
        if not rows:
            st.markdown('<div class="empty-card">No persisted runs match the current filters in this registry.</div>', unsafe_allow_html=True)
            return
        def render_table(table_rows: list[dict[str, Any]]) -> None:
            body = []
            for row in table_rows:
                identifier = f'{row["run_id"]}<span class="history-incident">{row["incident_id"] or "No incident"}</span>'
                human = history_badge("Required", "review") if row["human_required"] else history_badge("No", "neutral")
                body.append(f'<tr><td class="history-date">{row["date"]}</td><td class="history-id">{identifier}</td><td class="history-title">{row["title"]}</td><td>{row["integrity_badge"]}</td><td>{row["outcome_badge"]}</td><td>{human}</td><td><span class="history-view">View details&nbsp; →</span></td></tr>')
            st.markdown(f'<div class="history-table-wrap"><table class="history-table"><thead><tr><th>Date &amp; Time</th><th>Run / Incident ID</th><th>Incident Title</th><th>Integrity Status</th><th>Recovery Outcome</th><th>Human Review Required</th><th>View Details</th></tr></thead><tbody>{"".join(body)}</tbody></table></div>', unsafe_allow_html=True)

        if key_prefix == "actual_history":
            st.markdown("### Latest run")
            render_table(rows[:1])
            if len(rows) > 1:
                with st.expander(f"Previous Runs · {len(rows) - 1}", expanded=False):
                    render_table(rows[1:])
        else:
            with st.expander(f"Previous Runs · {len(rows)}", expanded=False):
                render_table(rows)
        selected = st.selectbox("View details", [row["run_id"] for row in rows], key=f"{key_prefix}_details", label_visibility="collapsed")
        run, summary = details_by_run[selected]
        selected_row = next(row for row in rows if row["run_id"] == selected)
        with st.expander(f'{selected} · {selected_row["title"]}', expanded=True):
            st.markdown(f'<div class="history-detail-header"><div><span class="eyebrow">{selected_row["run_type"]}</span><h3>{selected_row["title"]}</h3><p>{selected_row["date"]} · {selected_row["run_id"]} · {selected_row["incident_id"] or "No incident"}</p></div><div>{selected_row["integrity_badge"]} {selected_row["outcome_badge"]}</div></div>', unsafe_allow_html=True)
            if summary:
                repairs = comparison_rows(summary)
                verification = summary["verification_json"]
                detail_cols = st.columns(4)
                detail_cols[0].markdown(f'**Execution**<br>{selected_row["execution"]}', unsafe_allow_html=True)
                detail_cols[1].markdown(f'**Affected records**<br>{len(repairs):,}', unsafe_allow_html=True)
                detail_cols[2].markdown(f'**Investigation**<br>{selected_row["mode"]}', unsafe_allow_html=True)
                detail_cols[3].markdown(f'**Verification**<br>{status_label(verification.get("passed")) if verification else "Not recorded"}', unsafe_allow_html=True)
                st.markdown(f'<div class="history-detail-grid"><div><b>Failure reason</b><br>{selected_row["failure_reason"]}</div><div><b>Suspected root cause</b><br>{selected_row["root"]}</div><div><b>Recovery strategy</b><br>{selected_row["strategy"]}</div><div><b>Model</b><br>{selected_row["model"]}</div></div>', unsafe_allow_html=True)
                with st.expander("Technical evidence", expanded=False):
                    render_timeline(summary)
                    st.markdown("**Persisted repair evidence**")
                    comparison_table(repairs, limit=5)
                    st.json({"run": run, "incident": summary["incident"], "plan": summary["plan_json"], "safety": summary["safety"], "verification": summary["verification_json"]})
                if st.button(f'Open {summary["incident"].get("id")} in Workspace', key=f"open_history_{key_prefix}_{summary['incident'].get('id')}"):
                    st.session_state["selected_incident"] = summary["incident"].get("id")
                    st.session_state["page"] = "Workspace"
                    st.session_state["workflow_open"] = True
                    st.rerun()
            else:
                if run.get("archived"):
                    st.info("Archived actual ECHO execution. Its full persisted evidence is retained below; reopening the original runtime is not required to preserve this record.")
                else:
                    st.info("This is synthetic historical data from the bundled baseline. No incident investigation or recovery evidence is recorded for this healthy run.")
                with st.expander("Raw synchronization record", expanded=False):
                    st.json(run.get("archive") if run.get("archived") else run)

    actual_tab, synthetic_tab = st.tabs([f"Actual ECHO Runs · {len(actual_rows)}", f"Synthetic Historical Data · {len(synthetic_rows)}"])
    with actual_tab:
        render_registry(actual_rows, "actual_history")
    with synthetic_tab:
        render_registry(synthetic_rows, "synthetic_history")
    with st.expander("All synchronization records · Advanced Details", expanded=False):
        st.dataframe(runs, use_container_width=True, hide_index=True)


def render_scenarios_page(incidents: list[dict[str, Any]]) -> None:
    st.markdown('<div class="eyebrow">Demo scenarios · deliberate execution</div>', unsafe_allow_html=True)
    st.title("Demo scenarios")
    st.markdown('<div class="subtitle">Select a bundled scenario first. Only the explicit Run Scenario action invokes the existing backend workflow; browsing cards never resets data or calls OpenAI.</div>', unsafe_allow_html=True)
    cards = scenario_catalog(featured_only=True)
    options = [card["case_id"] for card in cards]
    selected_case = st.session_state.get("scenario_case", options[0] if options else "")
    st.caption("Choose a scenario. Selecting a card only selects it; it does not execute or reset anything.")
    scenario_columns = st.columns(3)
    for column, item in zip(scenario_columns, cards):
        with column:
            is_selected = item["case_id"] == selected_case
            label = scenario_card_label(item)
            if st.button(label, type="primary" if is_selected else "secondary", key=f'scenario_featured_{item["case_id"]}', use_container_width=True):
                st.session_state["scenario_case"] = item["case_id"]
                st.session_state["healthy_run_id"] = None
                st.rerun()
            st.caption(item["description"])
    st.session_state["scenario_case"] = selected_case
    card = next((item for item in cards if item["case_id"] == selected_case), None)
    if card:
        st.markdown(f'<div class="hero"><div class="eyebrow">{card["category"]}</div><div class="hero-title">{card["case_id"]}</div><div class="hero-copy">{card["description"]}</div><p>Severity: <b>{status_label(card["severity"])}</b> · incident: <b>{card["incident_id"] or "created on execution"}</b></p></div>', unsafe_allow_html=True)
    st.caption("Mock (offline) is the default. Live OpenAI is shown only when the configured project key is available, and is never called without this deliberate action.")
    import echo.agent.openai_client as client
    live_available = bool(client.OPENAI_API_KEY)
    mode = st.selectbox("Investigation mode", ["Mock (offline)"] + (["Live OpenAI"] if live_available else []), key="scenario_mode")
    st.warning("Running a scenario resets the demo runtime databases. Existing runtime incidents will be replaced by the selected recorded scenario.")
    confirm = st.checkbox("I understand this is an explicit demo reset and execution.", key="scenario_confirm")
    if st.button("Run Scenario", type="primary", disabled=not confirm, use_container_width=True):
        with st.spinner("Running the existing backend workflow…"):
            setup = load_case(selected_case)
            result = run_worker(mode)
        st.session_state["last_result"] = {"setup": setup, "result": result}
        st.session_state["selected_incident"] = result.get("incident_id") if isinstance(result, dict) else None
        st.session_state["page"] = "Workspace"
        st.rerun()


def render_approvals_page(incidents: list[dict[str, Any]]) -> None:
    st.markdown('<div class="eyebrow">Human approvals · controlled review</div>', unsafe_allow_html=True)
    st.title("Human approvals")
    st.markdown('<div class="subtitle">This queue is read-only because the current project has no secure approval endpoint, permission model, or audit-backed approval action. ECHO will not present fake Approve or Reject controls.</div>', unsafe_allow_html=True)
    pending = [row for row in incidents if row.get("review_required") or row.get("recovery_status") == "escalated" or incident_has_investigation_error(row["id"])]
    reviewed = [row for row in incidents if row.get("review_required") and row.get("recovery_status") not in {"pending", "escalated"}]
    pending_tab, reviewed_tab = st.tabs([f"Pending ({len(pending)})", f"Reviewed ({len(reviewed)})"])
    with pending_tab:
        if not pending:
            st.markdown('<div class="empty-card">No persisted incidents currently require human review.</div>', unsafe_allow_html=True)
        for incident in pending:
            data = incident_data(incident["id"])
            plan = data["plan_json"]
            investigation = investigation_summary(data)
            reason = investigation["human_review_reason"] or investigation["recovery_reason"]
            if investigation["investigation_error"]:
                reason = "Model execution failed; no AI conclusion was accepted."
            elif not investigation["investigation_complete"]:
                reason = "The investigation report was incomplete; no AI conclusion was accepted."
            elif plan.get("unsafe_count"):
                reason = reason or "Deterministic safety checks found a destination conflict or unavailable trusted evidence."
            st.markdown(f'<div class="approval-card"><div class="title">{incident.get("id")} · {status_label(incident.get("case_id"))}</div><div class="copy">{investigation["title"]}<br>{reason}<br>Affected records: <b>{len(data["repairs"])}</b> · proposed decision: <b>{status_label(plan.get("decision"))}</b><br>Automatic recovery remains blocked. Approval actions are unavailable.</div></div>', unsafe_allow_html=True)
            with st.expander(f"Evidence · {incident.get('id')}"):
                st.markdown(f"**Incident:** {incident.get('id')} · **Detected:** {incident.get('detected_at', '—')}")
                comparison_table(comparison_rows(data), limit=5)
                render_timeline(data)
    with reviewed_tab:
        if not reviewed:
            st.markdown('<div class="empty-card">No reviewed human-intervention cases are recorded.</div>', unsafe_allow_html=True)
        for incident in reviewed:
            st.markdown(f'<div class="history-row"><strong>{incident.get("id")}</strong> · {status_label(incident.get("recovery_status"))}<div class="history-meta">{incident.get("detected_at", "—")}</div></div>', unsafe_allow_html=True)
    with st.expander("Historical review evidence · Advanced Details"):
        st.dataframe(pending + reviewed, use_container_width=True, hide_index=True)


def render_evaluation_page() -> None:
    cards = scenario_catalog(featured_only=True)
    runs_now = fetch(echo_conn, "SELECT * FROM sync_runs ORDER BY COALESCE(finished_at, started_at) DESC")
    incidents_now = fetch(echo_conn, "SELECT * FROM incidents ORDER BY detected_at DESC")
    incident_by_case = {row.get("case_id"): row for row in incidents_now if row.get("case_id")}
    run_by_case = {str(row.get("id")): row for row in runs_now if str(row.get("id", "")).startswith("RUN-SCENARIO-")}
    archived_by_case: dict[str, tuple[dict[str, Any], dict[str, Any] | None]] = {}
    archive_path = execution_archive_path()
    if archive_path.is_file():
        for line in archive_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            archived = json.loads(line)
            archived_incidents = {row.get("run_id"): row for row in archived.get("incidents", [])}
            for archived_run in archived.get("runs", []):
                archived_id = str(archived_run.get("id", ""))
                case_id = archived_id.replace("RUN-", "", 1) if archived_id.startswith("RUN-SCENARIO-") else None
                if case_id:
                    archived_by_case[case_id] = (archived_run, archived_incidents.get(archived_id))
    total = len(cards)
    rows = []
    for card in cards:
        case_id = card["case_id"]
        run = run_by_case.get(f"RUN-{case_id}")
        incident = incident_by_case.get(case_id)
        archived = None
        if not run:
            archived = archived_by_case.get(case_id)
            if archived:
                run, incident = archived
        if not run:
            execution, integrity, recovery, verification, final = "Not tested", "Not measured", "Not measured", "Not measured", "Not tested"
        elif archived:
            execution = status_label(run.get("execution_status"))
            integrity = status_label(run.get("integrity_status"))
            recovery = status_label(incident.get("recovery_status")) if incident else "No recovery needed"
            verification = "Persisted in archive"
            final = "Recorded execution"
        elif not incident:
            execution, integrity, recovery, verification, final = status_label(run.get("execution_status")), status_label(run.get("integrity_status")), "No recovery needed", "Not applicable", "Passed" if run.get("integrity_status") == "healthy" else "Failed"
        else:
            data = incident_data(incident["id"])
            verification_json = data["verification_json"]
            execution, integrity = status_label(run.get("execution_status")), status_label(run.get("integrity_status"))
            recovery = status_label(incident.get("recovery_status"))
            verification = status_label(verification_json.get("passed")) if verification_json else "Not recorded"
            final = "Passed" if verification_json.get("passed") or recovery == "Escalated" else "Failed"
        rows.append({"Scenario": case_id, "Title": card["title"], "Execution": execution, "Integrity": integrity, "Recovery": recovery, "Verification": verification, "Final result": final})
    executed = sum(row["Execution"] != "Not tested" for row in rows)
    passed = sum(row["Final result"] == "Passed" for row in rows)
    failed = sum(row["Final result"] == "Failed" for row in rows)
    not_tested = total - executed
    st.markdown('<div class="eyebrow">Evaluation · measured reliability</div>', unsafe_allow_html=True)
    st.title("Evaluation")
    st.markdown('<div class="subtitle">Five active end-to-end cases. Results below are derived from persisted runtime executions; unexecuted cases remain Not tested.</div>', unsafe_allow_html=True)
    st.markdown('<div class="coverage"><span class="coverage-a"></span><span class="coverage-b"></span><span class="coverage-c"></span></div><div class="coverage-legend"><span><b>01</b> healthy</span><span><b>02–03</b> recoverable corruption</span><span><b>04–05</b> quarantine or human review</span></div>', unsafe_allow_html=True)
    cols = st.columns(5)
    metric("Available", total, "active scenarios", cols[0])
    metric("Executed", executed, "persisted runs", cols[1])
    metric("Passed", passed, "verified or healthy", cols[2])
    metric("Failed", failed, "verification failures", cols[3])
    metric("Not tested", not_tested, "remaining cases", cols[4])
    st.markdown('<div class="unavailable"><b>Evaluation is observational.</b><br>Use the explicit scenario execution control to run one case. This page never runs scenarios or calls OpenAI.</div>', unsafe_allow_html=True)
    st.markdown("### Per-case results")
    query = st.text_input("Search cases", placeholder="SCENARIO-02")
    visible_rows = [row for row in rows if not query.strip() or query.strip().lower() in f'{row["Scenario"]} {row["Title"]}'.lower()]
    if visible_rows:
        st.dataframe(visible_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No cases match this search.")
    st.markdown("### Aggregate reliability metrics")
    st.markdown('<div class="metric-strip"><div class="unavailable">Root-cause accuracy<br><b>Not measured</b></div><div class="unavailable">Affected-record precision / recall<br><b>Not measured</b></div><div class="unavailable">Recovery correctness<br><b>Not measured</b></div><div class="unavailable">API cost / token usage<br><b>Not measured</b></div></div>', unsafe_allow_html=True)
    st.markdown("### Data Types Tested")
    types = [
        ("Numerical values", "Covered by scenarios 01, 02, and 04; status follows persisted executions.", "Scenario coverage"),
        ("Text fields", "Covered by scenario 03; status follows persisted executions.", "Scenario coverage"),
        ("Conflicting updates", "Covered by scenario 05; status follows persisted escalations.", "Scenario coverage"),
    ]
    for label, detail, state in types:
        st.markdown(f'<div class="card" style="margin:8px 0"><div class="card-title">{label} · {state}</div><div class="node-note">{detail}</div></div>', unsafe_allow_html=True)
    with st.expander("Evaluation traces · Advanced Details"):
        st.info("No separate batch evaluation report is persisted. Per-case status above is read directly from the runtime execution records.")


runs = fetch(echo_conn, "SELECT * FROM sync_runs ORDER BY COALESCE(finished_at, started_at) DESC")
incidents = fetch(echo_conn, "SELECT * FROM incidents ORDER BY detected_at DESC")
incident_ids = [row["id"] for row in incidents]
if "selected_incident" not in st.session_state or st.session_state.get("selected_incident") not in incident_ids:
    st.session_state["selected_incident"] = incident_ids[0] if incident_ids else None
if "page" not in st.session_state:
    st.session_state["page"] = "Workspace"
if "workflow_open" not in st.session_state:
    st.session_state["workflow_open"] = False

with st.sidebar:
    st.markdown('<div class="brand-mark">ECHO</div><div class="brand-tag">Every error leaves a trace.</div>', unsafe_allow_html=True)
    pages = ["Workspace", "History", "Human Review"]
    page_icons = {
        "Workspace": ":material/home:",
        "History": ":material/history:",
        "Human Review": ":material/gpp_maybe:",
    }
    if st.session_state.get("page") not in pages + ["Evaluation"]:
        st.session_state["page"] = "Workspace"

    st.markdown('<div class="sidebar-section-label">Main menu</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-nav">', unsafe_allow_html=True)
    for page_name in pages:
        if st.button(
            page_name,
            key=f"sidebar_page_{page_name.lower().replace(' ', '_')}",
            icon=page_icons[page_name],
            type="primary" if page_name == st.session_state["page"] else "secondary",
            width="stretch",
        ):
            if page_name != st.session_state["page"]:
                st.session_state["page"] = page_name
                if page_name != "Workspace":
                    st.session_state["workflow_open"] = False
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="sidebar-developer">', unsafe_allow_html=True)
    advanced_open = bool(st.session_state.get("advanced_sidebar_open"))
    with st.expander("Advanced", expanded=advanced_open):
        if st.button("Evaluation", key="sidebar_advanced_evaluation", icon=":material/analytics:", width="stretch"):
            st.session_state["page"] = "Evaluation"
            st.session_state["workflow_open"] = False
            st.session_state["advanced_sidebar_open"] = False
            st.rerun()
        st.markdown("**Developer Settings**")
        st.caption("Developer settings · connection diagnostics are sanitized. API keys and request credentials are never displayed.")
        st.markdown(f"**Investigation mode:** `{LLM_MODE}`  \n**Model:** `{OPENAI_MODEL}`  \n**Project key:** `{'configured' if bool(OPENAI_API_KEY) else 'not configured'}`")
        st.caption(f"Limits: {MAX_TOOL_CALLS} tool calls · {MAX_SECONDS:g}s · ${MAX_ESTIMATED_USD:.2f} estimated cost · confidence threshold {MIN_INVESTIGATION_CONFIDENCE:.0%}")
        selected_row = next((row for row in incidents if row["id"] == st.session_state.get("selected_incident")), None)
        if selected_row:
            error_events = fetch(echo_conn, "SELECT * FROM investigation_events WHERE incident_id=? AND kind='investigation_error' ORDER BY id DESC", (selected_row["id"],))
            response_events = fetch(echo_conn, "SELECT * FROM investigation_events WHERE incident_id=? AND kind='model_response' ORDER BY id DESC", (selected_row["id"],))
            if error_events:
                error_payload = parse_json(error_events[0].get("payload_json"))
                raw_error = str(error_payload.get("error") or "")
                if OPENAI_API_KEY:
                    raw_error = raw_error.replace(OPENAI_API_KEY, "[redacted]")
                error_kind, explanation = classify_investigation_error(raw_error)
                st.error(f"{error_kind}: {explanation}")
                with st.expander("Sanitized diagnostic details", expanded=False):
                    st.json({
                        "incident_id": selected_row["id"],
                        "error_type": error_payload.get("error_type", "Not recorded"),
                        "http_status": error_payload.get("http_status") or (400 if "400" in raw_error else 401 if "401" in raw_error else 429 if "429" in raw_error else None),
                        "message": raw_error,
                        "model": error_payload.get("model", OPENAI_MODEL),
                        "tool_calls_before_failure": error_payload.get("tool_calls"),
                        "response_received_before_failure": bool(response_events),
                        "response_count": len(response_events),
                        "response_statuses": [parse_json(event.get("payload_json")).get("response_status") for event in response_events],
                        "response_tokens": [
                            {
                                "input_tokens": parse_json(event.get("payload_json")).get("input_tokens"),
                                "output_tokens": parse_json(event.get("payload_json")).get("output_tokens"),
                            }
                            for event in response_events
                        ],
                    })
            else:
                st.success("No persisted OpenAI investigation error for the selected incident.")
            st.caption("Raw JSON, logs, IDs, and full history are available in the incident Advanced Details section.")
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown("<div class='creator-credit'>Made by Nada Al-Mutairi</div>", unsafe_allow_html=True)

needs_workflow_evidence = st.session_state.get("page") == "Workspace" and st.session_state.get("workflow_open")
selected = incident_data(st.session_state["selected_incident"]) if needs_workflow_evidence and st.session_state.get("selected_incident") else None
st.markdown('<div class="page-shell">', unsafe_allow_html=True)
if st.session_state["page"] == "Workspace":
    if st.session_state.get("workflow_open"):
        render_incident_workflow(selected)
    else:
        render_workspace_home(incidents, runs)
elif st.session_state["page"] == "History":
    render_history_page(runs, incidents)
elif st.session_state["page"] == "Human Review":
    render_approvals_page(incidents)
else:
    render_evaluation_page()
st.markdown('</div>', unsafe_allow_html=True)

if "last_result" in st.session_state:
    with st.expander("Latest operator action · Advanced Details", expanded=False):
        st.json(st.session_state["last_result"])
