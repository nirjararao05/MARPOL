import streamlit as st
import os
import time
import random
import math
import uuid
import base64
import hashlib
import json
import ipaddress
import secrets
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from html import escape as html_escape

import pandas as pd
import plotly.express as px
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import PyMongoError, DuplicateKeyError
from pymongo.uri_parser import parse_uri
from streamlit.errors import StreamlitSecretNotFoundError

# ============================================================
# MARPOL-SAFE | Shipboard Environmental Operations
# ============================================================

APP_DIR = Path(__file__).resolve().parent


def setting(name, default):
    if name in os.environ:
        return os.environ[name]
    try:
        return str(st.secrets.get(name, default))
    except StreamlitSecretNotFoundError:
        return default


APP_ENV = setting("APP_ENV", "demo").strip().lower()
MONGO_URI = setting("MONGODB_URI", "mongodb://localhost:27017")
MONGO_DATABASE = setting("MONGODB_DATABASE", "marpol_safe")
MONGO_TLS_CONFIGURED = setting("MONGODB_TLS", "false").strip().lower() in {"1", "true", "yes"}
EVIDENCE_DIR = Path(setting("EVIDENCE_DIR", str(APP_DIR / "evidence_store"))).resolve()
BOOTSTRAP_ADMIN_PASSWORD = setting("BOOTSTRAP_ADMIN_PASSWORD", "").strip()
ENABLE_DEMO_ACCOUNTS = setting("ENABLE_DEMO_ACCOUNTS", "true").strip().lower() in {"1", "true", "yes"}


def is_loopback_address(address):
    if str(address).strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(address).is_loopback
    except (TypeError, ValueError):
        return False


def mongo_uri_requires_tls(uri):
    if uri.lower().startswith("mongodb+srv://"):
        return True
    hosts = parse_uri(uri)["nodelist"]
    return not hosts or any(not is_loopback_address(host) for host, _ in hosts)


STREAMLIT_BIND_ADDRESS = st.get_option("server.address") or ""
DEMO_ACCOUNTS_ENABLED = (
    APP_ENV != "production"
    and ENABLE_DEMO_ACCOUNTS
    and is_loopback_address(STREAMLIT_BIND_ADDRESS)
)
MONGO_TLS = MONGO_TLS_CONFIGURED or mongo_uri_requires_tls(MONGO_URI)

MAX_EVIDENCE_BYTES = 20 * 1024 * 1024  # 20 MB per file
PBKDF2_ITERATIONS = 200_000
DUMMY_PASSWORD_SALT = bytes(32)
DUMMY_PASSWORD_VERIFIER = bytes(32)
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 60

ALLOWED_EVIDENCE_TYPES = {
    ".pdf": ("application/pdf", b"%PDF-"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
}

FALLBACK_SHIP_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 240" fill="none">
  <defs>
    <linearGradient id="hull" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#e5b567" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="#2dd4bf" stop-opacity="0.45"/>
    </linearGradient>
    <linearGradient id="wave" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#2dd4bf" stop-opacity="0.04"/>
      <stop offset="50%" stop-color="#2dd4bf" stop-opacity="0.34"/>
      <stop offset="100%" stop-color="#2dd4bf" stop-opacity="0.04"/>
    </linearGradient>
  </defs>
  <rect x="424" y="64" width="76" height="54" rx="6" stroke="#e5b567" stroke-opacity="0.5" stroke-width="2" fill="#e5b567" fill-opacity="0.08"/>
  <rect x="442" y="42" width="42" height="22" rx="4" stroke="#2dd4bf" stroke-opacity="0.6" stroke-width="2" fill="#2dd4bf" fill-opacity="0.16"/>
  <rect x="457" y="24" width="12" height="18" rx="2" fill="#2dd4bf" fill-opacity="0.55"/>
  <rect x="168" y="88" width="60" height="30" rx="5" stroke="#8b9eb0" stroke-opacity="0.45" stroke-width="1.8" fill="#162028"/>
  <rect x="236" y="80" width="66" height="38" rx="5" stroke="#2dd4bf" stroke-opacity="0.45" stroke-width="1.8" fill="#1a2731"/>
  <rect x="310" y="88" width="58" height="30" rx="5" stroke="#8b9eb0" stroke-opacity="0.45" stroke-width="1.8" fill="#162028"/>
  <rect x="376" y="96" width="40" height="22" rx="4" stroke="#e5b567" stroke-opacity="0.42" stroke-width="1.8" fill="#151f27"/>
  <path d="M68 118 L566 118 L534 168 L118 168 Z" fill="url(#hull)" stroke="#2dd4bf" stroke-opacity="0.55" stroke-width="2"/>
  <line x1="104" y1="142" x2="546" y2="142" stroke="#f1f5f9" stroke-opacity="0.25" stroke-width="1.5" stroke-dasharray="6 6"/>
  <path d="M20 184 Q96 170 172 184 T324 184 T476 184 T620 184" stroke="url(#wave)" stroke-width="3" fill="none"/>
  <path d="M52 204 Q128 192 204 204 T356 204 T508 204 T604 204" stroke="url(#wave)" stroke-width="2" fill="none"/>
</svg>
""".strip()


def asset_data_uri(filename):
    """Return a local SVG asset as a data URI, falling back to an embedded vector."""
    assets_root = (APP_DIR / "assets").resolve()
    asset = (assets_root / filename).resolve()
    try:
        asset.relative_to(assets_root)
        inside_assets = True
    except ValueError:
        inside_assets = False
    if inside_assets and asset.is_file():
        raw = asset.read_bytes()
    else:
        raw = FALLBACK_SHIP_SVG.encode("utf-8")
    return "data:image/svg+xml;base64," + base64.b64encode(raw).decode("ascii")


st.set_page_config(
    page_title="MARPOL-SAFE | Shipboard Operations",
    page_icon="⚓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------
# Theme 1: Obsidian Bridge & Seafoam (Dark Mode)
# -----------------------------
st.markdown("""
<style>
:root {
  --bg:#070b0e;
  --surface:#0f161c;
  --surface-2:#162028;
  --surface-3:#1e2b36;
  --ink:#f1f5f9;
  --ink-2:#c7d3de;
  --muted:#8b9eb0;
  --faint:#8294a5;
  --line:rgba(148,179,199,.14);
  --line-2:rgba(45,212,191,.28);
  --teal-500:#14b8a6;
  --teal-400:#2dd4bf;
  --teal-300:#5eead4;
  --brass-400:#e5b567;
  --radius:16px;
  --radius-lg:22px;
  --shadow-sm:0 4px 18px rgba(0,0,0,.48),inset 0 1px 0 rgba(255,255,255,.04);
  --shadow-md:0 14px 32px rgba(0,0,0,.65),inset 0 1px 0 rgba(255,255,255,.06);
  --font:"Inter","Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,"Helvetica Neue",Roboto,Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,"Cascadia Mono",Consolas,Menlo,monospace;
  --good:#34d399;
  --warn:#fbbf24;
  --bad:#f87171;
  --info:#2dd4bf;
}
.t-teal{--tone:#2dd4bf;--tone-bg:rgba(45,212,191,.13);--tone-line:rgba(45,212,191,.28)}
.t-good{--tone:#34d399;--tone-bg:rgba(52,211,153,.13);--tone-line:rgba(52,211,153,.28)}
.t-warn{--tone:#fbbf24;--tone-bg:rgba(251,191,36,.13);--tone-line:rgba(251,191,36,.28)}
.t-bad{--tone:#f87171;--tone-bg:rgba(248,113,113,.13);--tone-line:rgba(248,113,113,.28)}
.t-info{--tone:#38bdf8;--tone-bg:rgba(56,189,248,.13);--tone-line:rgba(56,189,248,.28)}
.t-muted{--tone:#94a3b8;--tone-bg:rgba(148,163,184,.12);--tone-line:rgba(148,163,184,.24)}

/* Base */
html,body{background:var(--bg);color:var(--ink)}
.stApp,.stApp button,.stApp input,.stApp textarea,.stApp select,.stApp p,.stApp li,.stApp label,.stApp div,.stApp a,.stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp td,.stApp th,.stApp span:not([data-testid*="Icon"]):not([class*="material"]){font-family:var(--font)}
.stApp{
  background:
    radial-gradient(880px 420px at 14% -6%,rgba(45,212,191,.13),transparent 60%),
    radial-gradient(760px 380px at 90% 2%,rgba(229,181,103,.08),transparent 58%),
    var(--bg);
  color:var(--ink);
  -webkit-font-smoothing:antialiased;
}
.block-container,[data-testid="stMainBlockContainer"]{max-width:1380px;padding:3.1rem 2.25rem 3rem}
[data-testid="stHeader"]{background:rgba(7,11,14,.8);backdrop-filter:blur(12px)}
#MainMenu{visibility:hidden}
[data-testid="stDecoration"],[data-testid="stAppDeployButton"]{display:none!important}
.stApp h1,.stApp h2,.stApp h3,.stApp h4{color:var(--ink)!important;font-weight:700!important;letter-spacing:-.022em}
.stApp h1{font-size:1.85rem!important;line-height:1.15}
.stApp h2{font-size:1.35rem!important}
.stApp h3{font-size:1.05rem!important}
.stApp p,.stApp li{color:var(--ink-2);font-size:.93rem}
.stApp label,[data-testid="stWidgetLabel"],[data-testid="stWidgetLabel"] *{color:var(--ink-2)!important;font-size:.83rem!important;font-weight:620}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] *{color:var(--muted)!important;font-size:.78rem!important}
hr{border-color:var(--line)!important}
:focus-visible{outline:2px solid var(--teal-400)!important;outline-offset:2px}
::selection{background:rgba(45,212,191,.28);color:#fff}

/* Sidebar */
section[data-testid="stSidebar"]{
  background:linear-gradient(180deg,#080d11 0%,#0c141a 58%,#101b22 100%)!important;
  border-right:1px solid var(--line);
}
section[data-testid="stSidebar"] *{color:var(--ink-2)}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] *{color:var(--muted)!important}
section[data-testid="stSidebar"] hr{border-color:var(--line)!important;margin:.85rem 0}
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"],section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] *{color:var(--muted)!important;font-size:.66rem!important;font-weight:750;letter-spacing:.13em;text-transform:uppercase}
section[data-testid="stSidebar"] [role="radiogroup"]{gap:.25rem}
section[data-testid="stSidebar"] [data-testid="stRadioOption"],section[data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"]{
  width:100%;margin:0;padding:.6rem .82rem;border:1px solid transparent;border-radius:12px;
  transition:background .16s ease,border-color .16s ease,transform .16s ease;cursor:pointer;
}
section[data-testid="stSidebar"] [data-testid="stRadioOption"]>div>div:first-child,section[data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"]>div:first-child{display:none!important}
section[data-testid="stSidebar"] [data-testid="stRadioOption"] p,section[data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"] p{
  font-family:var(--font)!important;font-size:.9rem!important;font-weight:580;color:var(--ink-2)!important;
}
section[data-testid="stSidebar"] [data-testid="stRadioOption"]:hover,section[data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"]:hover{
  background:rgba(45,212,191,.07);border-color:var(--line);transform:translateX(2px);
}
section[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"],section[data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked),section[data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"][aria-checked="true"]{
  background:linear-gradient(90deg,rgba(45,212,191,.18),rgba(45,212,191,.04));
  border-color:rgba(45,212,191,.28);
  box-shadow:inset 3px 0 0 var(--teal-400);
}
section[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] p,section[data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) p{
  color:#ffffff!important;font-weight:700;
}
section[data-testid="stSidebar"] .stButton>button,section[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]{
  color:var(--ink)!important;background:var(--surface-2)!important;border:1px solid var(--line)!important;
}
section[data-testid="stSidebar"] .stButton>button:hover{background:var(--surface-3)!important;border-color:var(--line-2)!important}
section[data-testid="stSidebar"] .stButton>button p{color:var(--ink)!important}

.ms-brand{display:flex;align-items:center;gap:.75rem;margin:.2rem 0 .1rem}
.ms-brand-mark{
  flex:none;width:40px;height:40px;border-radius:12px;display:grid;place-items:center;
  font-weight:850;font-size:.86rem;letter-spacing:-.03em;
  background:linear-gradient(135deg,#134e4a,#0f766e);
  border:1px solid rgba(45,212,191,.4);
  box-shadow:0 8px 20px rgba(0,0,0,.45);
}
section[data-testid="stSidebar"] .ms-brand-mark{color:#f0fdfa!important}
.ms-brand-name{font-size:1.1rem;font-weight:780;letter-spacing:-.03em;line-height:1.1}
.ms-brand-kicker{font-size:.6rem;font-weight:750;letter-spacing:.15em;text-transform:uppercase;margin-top:.16rem}
section[data-testid="stSidebar"] .ms-brand-name{color:#fff!important}
section[data-testid="stSidebar"] .ms-brand-kicker{color:var(--teal-400)!important}

.ms-side-label{font-size:.66rem;font-weight:750;letter-spacing:.13em;text-transform:uppercase;margin:0 0 .5rem}
section[data-testid="stSidebar"] .ms-side-label{color:var(--muted)!important}
.ms-sidecard{padding:.8rem .9rem;border-radius:14px;background:rgba(255,255,255,.03);border:1px solid var(--line)}
.ms-sidecard-title{font-weight:720;font-size:.9rem;line-height:1.25}
.ms-sidecard-meta{font-size:.76rem;margin-top:.3rem;line-height:1.55}
section[data-testid="stSidebar"] .ms-sidecard-title{color:#fff!important}
section[data-testid="stSidebar"] .ms-sidecard-meta{color:var(--muted)!important}
.ms-user{display:flex;gap:.7rem;align-items:center}
.ms-avatar{
  flex:none;width:38px;height:38px;border-radius:50%;display:grid;place-items:center;
  font-weight:750;font-size:.8rem;background:rgba(229,181,103,.14);border:1px solid rgba(229,181,103,.38);
}
section[data-testid="stSidebar"] .ms-avatar{color:var(--brass-400)!important}
.ms-rolepill{
  display:inline-block;margin-top:.22rem;padding:.12rem .52rem;border-radius:99px;
  font-size:.66rem;font-weight:720;letter-spacing:.04em;
  background:rgba(45,212,191,.13);border:1px solid rgba(45,212,191,.28);
}
section[data-testid="stSidebar"] .ms-rolepill{color:var(--teal-400)!important}

/* Buttons & Inputs */
.stButton>button,.stDownloadButton>button,.stFormSubmitButton>button,.stLinkButton>a,[data-testid^="stBaseButton"],[data-testid^="stBaseLinkButton"]{
  min-height:2.6rem;border-radius:99px;font-size:.86rem!important;font-weight:650!important;
  transition:transform .15s ease,box-shadow .15s ease,background .15s ease,border-color .15s ease;
}
.stButton>button[kind="primary"],.stFormSubmitButton>button,button[data-testid="stBaseButton-primary"],button[data-testid="stBaseButton-primaryFormSubmit"]{
  background:linear-gradient(135deg,#14b8a6,#0f766e)!important;
  border:1px solid rgba(94,234,212,.4)!important;
  color:#041212!important;
  box-shadow:0 8px 22px -8px rgba(20,184,166,.55);
}
.stButton>button[kind="primary"] p,.stFormSubmitButton>button p,button[data-testid="stBaseButton-primary"] p,button[data-testid="stBaseButton-primaryFormSubmit"] p{
  color:#041212!important;font-weight:720!important;
}
.stButton>button[kind="primary"]:hover,.stFormSubmitButton>button:hover,button[data-testid="stBaseButton-primary"]:hover,button[data-testid="stBaseButton-primaryFormSubmit"]:hover{
  background:linear-gradient(135deg,#2dd4bf,#0d9488)!important;
}
.stButton>button[kind="secondary"],.stDownloadButton>button[kind="secondary"],.stLinkButton>a,button[data-testid="stBaseButton-secondary"],a[data-testid^="stBaseLinkButton"]{
  color:var(--ink)!important;background:var(--surface-2)!important;border:1px solid var(--line)!important;
}
.stButton>button:hover,.stDownloadButton>button:hover,.stLinkButton>a:hover{
  transform:translateY(-1px);box-shadow:0 10px 22px -10px rgba(0,0,0,.75);border-color:var(--line-2)!important;
}
.stButton>button:disabled,.stFormSubmitButton>button:disabled{opacity:.48}

[data-baseweb="input"],[data-baseweb="textarea"],[data-baseweb="select"]>div{
  border-radius:12px!important;background:var(--surface-2)!important;border-color:var(--line)!important;color:var(--ink)!important;
}
[data-baseweb="input"]:focus-within,[data-baseweb="textarea"]:focus-within,[data-baseweb="select"]>div:focus-within{
  border-color:var(--teal-400)!important;box-shadow:0 0 0 3px rgba(45,212,191,.16)!important;
}
[data-baseweb="input"] input,[data-baseweb="textarea"] textarea,[data-baseweb="select"] input,[data-baseweb="select"] div,[data-baseweb="select"] span{
  color:var(--ink)!important;
}
.stApp input:not([type="radio"]):not([type="checkbox"]):not([type="file"]):not([type="hidden"]),
.stApp textarea{
  color:var(--ink)!important;background-color:var(--surface-2)!important;
  -webkit-text-fill-color:var(--ink);caret-color:var(--teal-300);
}
.stApp input::placeholder,.stApp textarea::placeholder{
  color:var(--muted)!important;opacity:1!important;-webkit-text-fill-color:var(--muted);
}
[data-testid="stSelectbox"] input[role="combobox"]{caret-color:transparent!important;outline:none!important}
[data-testid="InputInstructions"]{display:none!important}
[data-testid="stFileUploaderDropzone"]{
  border:1.5px dashed rgba(45,212,191,.36);border-radius:16px;background:var(--surface-2);
}
[data-testid="stFileUploaderDropzone"]:hover{background:var(--surface-3)}
[data-testid="stVerticalBlockBorderWrapper"]{
  border-color:var(--line)!important;border-radius:var(--radius)!important;background:var(--surface);box-shadow:var(--shadow-sm);
}
[data-testid="stForm"]{
  border:1px solid var(--line);border-radius:var(--radius);padding:1.25rem 1.4rem;background:var(--surface);box-shadow:var(--shadow-sm);
}
[data-testid="stDataFrame"],[data-testid="stTable"]{
  border:1px solid var(--line);border-radius:16px;overflow:hidden;background:var(--surface);box-shadow:var(--shadow-sm);
}
[data-testid="stMetric"]{
  padding:1rem 1.1rem;background:var(--surface-2);border:1px solid var(--line);border-radius:var(--radius);
}
[data-testid="stMetricLabel"],[data-testid="stMetricLabel"] *{color:var(--muted)!important;font-size:.78rem!important;font-weight:620!important}
[data-testid="stMetricValue"]{color:var(--ink)!important;font-size:1.75rem!important;font-weight:730!important;letter-spacing:-.04em;font-variant-numeric:tabular-nums}
[data-testid="stExpander"]{border:1px solid var(--line)!important;border-radius:16px!important;background:var(--surface);box-shadow:var(--shadow-sm)}
[data-testid="stExpander"] summary{font-weight:650;color:var(--ink)}
button[data-baseweb="tab"]{color:var(--muted)!important;font-weight:650}
button[data-baseweb="tab"][aria-selected="true"]{color:var(--teal-400)!important}

/* Page header & sections */
.ms-pagehead{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:.8rem 2rem;margin:.1rem 0 1.3rem;padding-bottom:1.1rem;border-bottom:1px solid var(--line)}
.ms-kicker{color:var(--teal-400)!important;font-size:.7rem;font-weight:760;letter-spacing:.15em;text-transform:uppercase}
.ms-title{color:var(--ink)!important;font-size:clamp(1.6rem,2.3vw,2.05rem);font-weight:740;letter-spacing:-.034em;line-height:1.12;margin:.35rem 0 .1rem}
.ms-chips{display:flex;flex-wrap:wrap;gap:.45rem}
.ms-chip{display:inline-flex;align-items:center;gap:.4rem;padding:.34rem .75rem;border-radius:99px;font-size:.74rem;font-weight:650;color:var(--ink-2)!important;background:var(--surface-2);border:1px solid var(--line)}
.ms-section{display:flex;flex-wrap:wrap;align-items:baseline;gap:.2rem .8rem;margin:1.65rem 0 .75rem}
.ms-section-title{color:var(--ink)!important;font-size:1.1rem;font-weight:710;letter-spacing:-.022em}
.ms-cardhead{margin:.05rem 0 .6rem}
.ms-cardtitle{color:var(--ink)!important;font-size:1.02rem;font-weight:700;letter-spacing:-.018em}

/* Top bar */
.ms-topbar{
  display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:.55rem 1.4rem;
  margin:.1rem 0 1.25rem;padding:.68rem 1rem;
  background:rgba(15,22,28,.9);backdrop-filter:blur(10px);
  border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow-sm);
  font-size:.78rem;color:var(--muted);
}
.ms-topbar-group{display:flex;flex-wrap:wrap;align-items:center;gap:.45rem 1.05rem}
.ms-topbar b{color:var(--ink)}
.ms-dot-sep{width:3px;height:3px;border-radius:50%;background:var(--faint);display:inline-block}
.ms-topbar-item{display:inline-flex;align-items:center;gap:.4rem;white-space:nowrap;font-variant-numeric:tabular-nums}
.ms-topbar-item svg{width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}

/* Pills & KPIs */
.ms-pill{display:inline-flex;align-items:center;gap:.4rem;padding:.24rem .68rem;border-radius:99px;font-size:.72rem;font-weight:700;letter-spacing:.01em;color:var(--tone)!important;background:var(--tone-bg);border:1px solid var(--tone-line);white-space:nowrap}
.ms-pill:before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.ms-pill.plain:before{display:none}

.ms-kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.9rem;margin:.3rem 0 .75rem}
.ms-kpis.cols-4{grid-template-columns:repeat(4,minmax(0,1fr))}
.ms-kpi{
  display:flex;gap:.85rem;align-items:flex-start;padding:1.05rem 1.15rem;
  background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
  box-shadow:var(--shadow-sm);transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease;
}
.ms-kpi:hover{transform:translateY(-2px);box-shadow:var(--shadow-md);border-color:var(--line-2)}
.ms-kpi-icon{flex:none;width:44px;height:44px;border-radius:12px;display:grid;place-items:center;color:var(--tone);background:var(--tone-bg);border:1px solid var(--tone-line)}
.ms-kpi-icon svg{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}
.ms-kpi-body{min-width:0}
.ms-kpi-label{color:var(--muted)!important;font-size:.76rem;font-weight:660}
.ms-kpi-value{color:var(--ink)!important;font-size:1.85rem!important;font-weight:730!important;letter-spacing:-.045em;line-height:1.12;margin:.12rem 0;font-variant-numeric:tabular-nums}
.ms-kpi-note{color:var(--faint)!important;font-size:.74rem}

/* Details, Callouts, Forms, Library */
.ms-detailhead{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-start;gap:.5rem 1rem;margin-bottom:.9rem;padding-bottom:.85rem;border-bottom:1px solid var(--line)}
.ms-id{font-family:var(--mono)!important;color:var(--ink)!important;font-size:1.12rem;font-weight:700}
.ms-subtle{color:var(--muted)!important;font-size:.82rem;margin-top:.2rem}
.ms-kv{display:grid;grid-template-columns:repeat(auto-fill,minmax(185px,1fr));gap:.95rem 1.5rem}
.ms-kv-l{color:var(--muted)!important;font-size:.68rem;font-weight:740;letter-spacing:.09em;text-transform:uppercase}
.ms-kv-v{color:var(--ink)!important;font-size:.93rem;font-weight:560;margin-top:.18rem;word-break:break-word;font-variant-numeric:tabular-nums}
.ms-note{margin-top:1rem;padding:.8rem .95rem;border-radius:12px;background:var(--surface-2);border:1px solid var(--line)}
.ms-note .ms-kv-v{font-weight:450;line-height:1.55}
.ms-callout{display:flex;gap:.7rem;align-items:flex-start;margin:.35rem 0 .9rem;padding:.8rem 1rem;border-radius:12px;color:var(--ink-2)!important;background:var(--tone-bg);border:1px solid var(--tone-line);border-left:4px solid var(--tone);font-size:.88rem;line-height:1.6}
.ms-callout b{color:var(--ink)}
.ms-callout-body{min-width:0}
.ms-callout-title{color:var(--tone)!important;font-weight:720;font-size:.8rem;letter-spacing:.02em;margin-bottom:.15rem}
.ms-empty{text-align:center;padding:2rem 1rem;border:1.5px dashed var(--line-2);border-radius:var(--radius);background:var(--surface)}
.ms-empty-title{color:var(--ink)!important;font-weight:700}
.ms-steps{display:flex;flex-wrap:wrap;gap:.5rem;margin:0 0 1rem}
.ms-step{display:inline-flex;align-items:center;gap:.5rem;padding:.35rem .82rem .35rem .4rem;border-radius:99px;background:var(--surface-2);border:1px solid var(--line);font-size:.78rem;font-weight:650;color:var(--ink-2)!important}
.ms-step-n{display:grid;place-items:center;width:22px;height:22px;border-radius:50%;background:linear-gradient(135deg,#14b8a6,#0f766e);color:#041212!important;font-size:.7rem;font-weight:800}
.ms-formsec{display:flex;align-items:center;gap:.6rem;margin:.9rem 0 .6rem}
.ms-formsec-n{display:grid;place-items:center;width:24px;height:24px;border-radius:8px;background:rgba(45,212,191,.14);border:1px solid rgba(45,212,191,.28);color:var(--teal-400)!important;font-size:.76rem;font-weight:780}
.ms-formsec-t{color:var(--ink)!important;font-weight:700;font-size:.98rem}
.ms-count{display:inline-flex;align-items:baseline;gap:.4rem;padding:.4rem .8rem;border-radius:11px;background:var(--surface-2);border:1px solid var(--line);color:var(--ink)!important;font-size:1.05rem;font-weight:740;font-variant-numeric:tabular-nums}
.ms-count span{color:var(--muted)!important;font-size:.76rem;font-weight:600}
.ms-toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem;margin:.4rem 0 .8rem}
.ms-latest{display:inline-flex;gap:.5rem;align-items:center;margin-top:.6rem;padding:.4rem .75rem;border-radius:11px;background:var(--surface-2);border:1px solid var(--line);font-size:.82rem;color:var(--muted)!important}
.ms-latest code{font-family:var(--mono);color:var(--teal-400);background:rgba(45,212,191,.12);padding:.1rem .4rem;border-radius:6px}

.ms-libtop{display:flex;flex-wrap:wrap;gap:.4rem;margin-bottom:.55rem}
.ms-libtitle{color:var(--ink)!important;font-weight:710;font-size:1.04rem;letter-spacing:-.018em;line-height:1.3;margin:.1rem 0 .35rem}
.ms-libsum{color:var(--ink-2)!important;font-size:.86rem;line-height:1.6}
.ms-libchips{display:flex;flex-wrap:wrap;gap:.35rem;margin:.7rem 0 .55rem}
.ms-srcchip{padding:.22rem .58rem;border-radius:99px;background:var(--surface-2);border:1px solid var(--line);color:var(--muted)!important;font-size:.7rem;font-weight:620}

.ms-sysgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:.9rem}
.ms-sys{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:1rem 1.15rem;box-shadow:var(--shadow-sm)}
.ms-sys-l{color:var(--muted)!important;font-size:.68rem;font-weight:740;letter-spacing:.09em;text-transform:uppercase}
.ms-sys-v{color:var(--ink)!important;font-size:.95rem;font-weight:620;margin-top:.3rem;line-height:1.5;word-break:break-word}

/* Hero Banner */
.dashboard-hero{
  position:relative;display:flex;min-height:210px;align-items:center;overflow:hidden;
  container-type:inline-size;
  margin:.1rem 0 1.35rem;padding:1.85rem 2.1rem;
  border:1px solid rgba(45,212,191,.24);border-radius:var(--radius-lg);
  background:
    radial-gradient(560px 260px at 84% 12%,rgba(45,212,191,.22),transparent 70%),
    linear-gradient(120deg,#0b1319 0%,#10222c 55%,#14303b 100%);
  box-shadow:0 24px 48px -24px rgba(0,0,0,.85);
}
.dashboard-hero:before{
  content:"";position:absolute;inset:-28% 5% auto auto;width:380px;height:380px;
  border:1px solid rgba(45,212,191,.13);border-radius:50%;
  box-shadow:0 0 0 42px rgba(45,212,191,.03),0 0 0 84px rgba(45,212,191,.02);
}
.hero-copy{position:relative;z-index:2;max-width:58%}
.hero-kicker{color:var(--teal-400)!important;font-size:.68rem;font-weight:760;letter-spacing:.16em;text-transform:uppercase}
.hero-title{margin:.5rem 0 .45rem;color:#ffffff!important;font-size:clamp(1.75rem,2.9vw,2.4rem);font-weight:740;letter-spacing:-.04em;line-height:1.08}
.hero-title-accent{color:var(--teal-300)!important}
.hero-tags{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.55rem;margin-top:1rem;max-width:760px}
.hero-tag{
  display:grid;align-content:center;gap:.22rem;min-width:0;padding:.58rem .78rem;
  border:1px solid rgba(229,181,103,.28);border-left:3px solid var(--brass-400);border-radius:13px;
  background:rgba(7,11,14,.58);
}
.hero-tag-label{color:var(--teal-400)!important;font-size:.59rem;font-weight:760;letter-spacing:.12em;text-transform:uppercase}
.hero-tag-value{color:var(--brass-400)!important;font-size:.72rem;font-weight:680;line-height:1.45;overflow-wrap:anywhere}
.hero-art{position:absolute;right:1.5%;bottom:-4%;width:43%;max-width:510px;opacity:.92}
.hero-art img{display:block;width:100%;height:auto}
@container (max-width:700px){
  .hero-copy{max-width:100%}
  .hero-tags{grid-template-columns:1fr}
  .hero-art{display:none}
}

/* Login */
.stApp:has(.login-visual) .block-container,.stApp:has(.login-visual) [data-testid="stMainBlockContainer"]{max-width:1120px;padding-top:3.1rem}
.stApp:has(.login-visual) [data-testid="stHorizontalBlock"]{
  min-height:660px;align-items:stretch;gap:0!important;overflow:hidden;
  border:1px solid var(--line);border-radius:26px;background:var(--surface);
  box-shadow:0 40px 80px -36px rgba(0,0,0,.85);
}
.stApp:has(.login-visual) [data-testid="stColumn"]:has(.login-visual){padding:0!important;overflow:hidden;background:#0c141a}
.stApp:has(.login-visual) [data-testid="stColumn"]:has([data-testid="stForm"]){
  display:flex;flex-direction:column;justify-content:center;min-height:660px;padding:2.5rem 2.7rem!important;background:var(--surface);
}
.stApp:has(.login-visual) [data-testid="stForm"]{border:none;box-shadow:none;padding:0;background:transparent}
.login-visual{
  position:relative;min-height:660px;height:100%;overflow:hidden;
  background:radial-gradient(500px 300px at 85% 0%,rgba(45,212,191,.22),transparent 70%),linear-gradient(135deg,#070b0e,#112630);
}
.login-ship-art{position:absolute;right:-6%;bottom:3%;width:94%;opacity:.88}
.stApp .login-copy{position:absolute;z-index:2;top:10%;left:9%;right:8%}
.login-tag{display:inline-block;padding:.4rem .75rem;border:1px solid rgba(229,181,103,.32);border-radius:99px;color:var(--brass-400)!important;background:rgba(255,255,255,.03);font-size:.62rem;font-weight:760;letter-spacing:.12em}
.stApp .login-copy h1{color:#ffffff!important;font-size:clamp(2.4rem,4.4vw,3.5rem)!important;font-weight:740!important;letter-spacing:-.055em;margin:.9rem 0 .45rem;line-height:1}
.stApp .login-copy h1 span{color:var(--teal-400)!important}
.login-points{display:grid;gap:.55rem;margin:1.1rem 0 1.2rem;padding:0}
.login-points div{display:flex;align-items:center;gap:.6rem;color:var(--ink-2)!important;font-size:.88rem}
.login-points i{flex:none;width:22px;height:22px;border-radius:50%;display:grid;place-items:center;font-style:normal;font-size:.72rem;font-weight:800;color:#041212!important;background:linear-gradient(135deg,#2dd4bf,#14b8a6)}
.login-brand{display:flex;align-items:center;gap:.6rem;color:var(--ink);font-size:1.1rem;font-weight:780;letter-spacing:-.035em}
.login-brand-mark{display:grid;width:32px;height:32px;place-items:center;border-radius:10px;background:rgba(45,212,191,.14);border:1px solid rgba(45,212,191,.32);color:var(--teal-400);font-size:.72rem;font-weight:840}
.login-brand small{color:var(--brass-400);font-size:.66rem;font-weight:700;letter-spacing:.1em;padding:.1rem .45rem;border:1px solid rgba(229,181,103,.28);border-radius:99px}
.login-card-title{color:var(--ink)!important;font-size:1.85rem;font-weight:740;letter-spacing:-.04em;margin:1.1rem 0 .2rem;line-height:1.15}
.login-muted{color:var(--muted)!important;margin:0 0 1.2rem;font-size:.92rem}
.login-accounts{margin-top:1rem;border:1px solid var(--line);border-radius:14px;overflow:hidden;background:var(--surface-2)}
.login-accounts-head{padding:.55rem .85rem;color:var(--muted)!important;font-size:.66rem;font-weight:750;letter-spacing:.11em;text-transform:uppercase;background:var(--surface-3);border-bottom:1px solid var(--line)}
.login-acc{display:grid;grid-template-columns:1fr 1fr 1.2fr;gap:.5rem;padding:.45rem .85rem;font-size:.78rem;border-bottom:1px solid var(--line);color:var(--ink-2)!important}
.login-acc:last-child{border-bottom:none}
.login-acc code{font-family:var(--mono);font-size:.76rem;color:var(--teal-400);background:transparent}
.login-acc span{color:var(--muted)!important}
.login-security{display:flex;gap:.4rem;flex-wrap:wrap;margin-top:.9rem}
.security-chip{padding:.3rem .62rem;border-radius:99px;background:var(--surface-2)!important;border:1px solid var(--line);color:var(--muted)!important;font-size:.62rem;font-weight:730;letter-spacing:.04em}

.ms-footer{display:flex;flex-wrap:wrap;justify-content:center;gap:.3rem 1rem;margin-top:1.2rem;padding:.9rem 0 .4rem;color:var(--muted)!important;font-size:.76rem;text-align:center;border-top:1px solid var(--line)}
.ms-footer b{color:var(--ink)}

@keyframes ms-rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.ms-pagehead,.ms-kpi,.ms-topbar,.dashboard-hero,.ms-sys{animation:ms-rise .45s cubic-bezier(.2,.7,.2,1) both}
@media (max-width:960px){
  .ms-kpis,.ms-kpis.cols-4{grid-template-columns:repeat(2,minmax(0,1fr))}
  .hero-copy{max-width:100%}
  .hero-tags{grid-template-columns:1fr}
}
@media (max-width:640px){
  .ms-kpis,.ms-kpis.cols-4{grid-template-columns:1fr}
  .stApp:has(.login-visual) [data-testid="stHorizontalBlock"]{display:block;min-height:0}
  .login-visual{min-height:260px}
  .login-ship-art{display:none}
  .stApp .login-copy{position:relative;top:auto;left:auto;right:auto;padding:1.6rem}
  .stApp:has(.login-visual) [data-testid="stColumn"]:has([data-testid="stForm"]){min-height:0;padding:1.6rem!important}
}
</style>
""", unsafe_allow_html=True)


# -----------------------------
# Presentation Helpers
# -----------------------------
class Raw(str):
    """Marks a string as trusted, already-escaped HTML."""


def esc(value):
    return html_escape("" if value is None else str(value))


def ui(markup):
    st.markdown(" ".join(str(markup).split()).replace("> <", "><"), unsafe_allow_html=True)


def nz(value, default="—"):
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text if text and text.lower() not in {"nan", "none"} else default


_ICON_PATHS = {
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
    "check": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "alert": '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    "clip": '<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
    "sync": '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "pulse": '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    "pin": '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
}


def icon_svg(name):
    return f'<svg viewBox="0 0 24 24" aria-hidden="true">{_ICON_PATHS.get(name, _ICON_PATHS["file"])}</svg>'


STATUS_TONE = {"Approved": "good", "Pending": "warn"}
SEVERITY_TONE = {"Error": "bad", "Warning": "warn", "Information": "info"}


def pill(text, tone=None, plain=False):
    tone = tone or STATUS_TONE.get(str(text), "muted")
    return Raw(f'<span class="ms-pill t-{tone}{" plain" if plain else ""}">{esc(text)}</span>')


def status_label(status):
    return {"Approved": "🟢 Approved", "Pending": "🟡 Pending"}.get(str(status), str(status))


def severity_label(severity):
    return {"Error": "🔴 Error", "Warning": "🟠 Warning", "Information": "🔵 Information"}.get(str(severity), str(severity))


def page_header(kicker, title, desc="", chips=()):
    chip_html = "".join(f'<span class="ms-chip">{esc(c)}</span>' for c in chips)
    ui(f'<div class="ms-pagehead"><div><div class="ms-kicker">{esc(kicker)}</div>'
       f'<div class="ms-title" role="heading" aria-level="1">{esc(title)}</div>'
       f'</div><div class="ms-chips">{chip_html}</div></div>')


def section_title(title, sub=""):
    ui(f'<div class="ms-section"><span class="ms-section-title">{esc(title)}</span></div>')


def card_title(title, sub=""):
    ui(f'<div class="ms-cardhead"><div class="ms-cardtitle">{esc(title)}</div></div>')


def kpi_grid(items):
    cells = "".join(
        f'<div class="ms-kpi t-{tone}"><div class="ms-kpi-icon">{icon_svg(icon)}</div><div class="ms-kpi-body">'
        f'<div class="ms-kpi-label">{esc(label)}</div><div class="ms-kpi-value">{esc(value)}</div>'
        f'<div class="ms-kpi-note">{esc(note)}</div></div></div>'
        for label, value, note, tone, icon in items)
    cols = 4 if len(items) == 4 else 3
    ui(f'<div class="ms-kpis cols-{cols}">{cells}</div>')


def kv_html(pairs):
    cells = "".join(
        f'<div class="ms-kv-item"><div class="ms-kv-l">{esc(label)}</div>'
        f'<div class="ms-kv-v">{value if isinstance(value, Raw) else esc(value)}</div></div>'
        for label, value in pairs)
    return f'<div class="ms-kv">{cells}</div>'


def callout(tone, body, title=""):
    title_html = f'<div class="ms-callout-title">{esc(title)}</div>' if title else ""
    ui(f'<div class="ms-callout t-{tone}"><div class="ms-callout-body">{title_html}{body}</div></div>')


def empty_state(title, text=""):
    ui(f'<div class="ms-empty"><div class="ms-empty-title">{esc(title)}</div></div>')


def form_section(number, title, sub=""):
    ui(f'<div class="ms-formsec"><span class="ms-formsec-n">{esc(number)}</span><div><div class="ms-formsec-t">{esc(title)}</div></div></div>')


def flash(kind, message):
    st.session_state.setdefault("_flash", []).append((kind, message))


def render_flash():
    for kind, message in st.session_state.pop("_flash", []):
        {"success": st.success, "warning": st.warning, "error": st.error}.get(kind, st.info)(message)


# -----------------------------
# Domain Constants
# -----------------------------
ANNEXES = {
    "Annex I - Oil": "Oil",
    "Annex II - NLS": "NLS",
    "Annex III - Packaged": "Packaged",
    "Annex IV - Sewage": "Sewage",
    "Annex V - Garbage": "Garbage",
    "Annex VI - Air": "Air",
}

OPERATIONS = {
    "Annex I - Oil": ["Sludge Discharge", "Bilge/Oily Water Discharge", "Oil Transfer"],
    "Annex II - NLS": ["Cargo Tank Cleaning", "NLS Discharge", "Tank Residue Operation"],
    "Annex III - Packaged": ["Disposal to Port", "Package Transfer", "Cargo Inspection"],
    "Annex IV - Sewage": ["Sewage Discharge", "Sewage Treatment"],
    "Annex V - Garbage": ["Incineration", "Food Waste Disposal", "Garbage Discharge"],
    "Annex VI - Air": ["Fuel Changeover", "Bunker Operation", "Emission Record"],
}

LOCATIONS = ["Arabian Sea", "Mangalore Anchorage", "Mangalore Port", "Singapore", "Bay of Bengal"]

DEMO_USERS = {
    "admin":   {"user_id": "USR-ADMIN",   "password": "admin123",  "name": "System Administrator", "role": "Admin"},
    "chief":   {"user_id": "USR-CHIEF",   "password": "marpol123", "name": "Chief Engineer",       "role": "Chief Engineer"},
    "officer": {"user_id": "USR-OFFICER", "password": "marpol123", "name": "Third Officer",        "role": "Officer"},
    "cadet":   {"user_id": "USR-CADET",   "password": "marpol123", "name": "Deck Cadet",           "role": "Cadet"},
}

ROLE_PAGES = {
    "Admin": ["Dashboard", "Record an Operation", "MARPOL Records", "Compliance Alerts",
              "Approval Queue", "Reports & Analytics", "Audit Trail", "MARPOL Library",
              "Database Explorer", "System Settings"],
    "Chief Engineer": ["Dashboard", "Record an Operation", "MARPOL Records", "Compliance Alerts",
                        "Approval Queue", "Reports & Analytics", "Audit Trail", "MARPOL Library"],
    "Officer": ["Dashboard", "Record an Operation", "MARPOL Records", "Compliance Alerts",
                "Reports & Analytics", "MARPOL Library"],
    "Cadet": ["Dashboard", "Record an Operation", "MARPOL Records", "MARPOL Library"],
}
ROLE_SUMMARY = {
    "Admin": "Full system access • users, settings, records, approvals and audit",
    "Chief Engineer": "Supervises records • resolves alerts • reviews and approves operations",
    "Officer": "Creates and reviews operational records • monitors alerts and reports",
    "Cadet": "Creates/submits operational entries • views own records and reference library",
}
VESSEL = {
    "name": "MV OCEAN PIONEER", "imo": "9876543", "flag": "India",
    "type": "Oil Tanker", "gt": "45,678 GT", "voyage": "V-2026-001",
    "route": "Mangalore → Singapore", "base_lat": 12.5933, "base_lon": 74.8718,
}


# -----------------------------
# Security, Auth & RBAC
# -----------------------------
def utc_now_str():
    return datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")


def require_role(role, allowed_roles):
    if role not in allowed_roles:
        raise PermissionError(f"Role '{role}' is not authorized for this action.")


def hash_password(password, salt_hex=None):
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(32)
    verifier = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return salt.hex(), verifier.hex()


def verify_password(password, salt_hex, verifier_hex):
    try:
        if not salt_hex or not verifier_hex:
            return False
        salt = bytes.fromhex(salt_hex)
        for iterations in (PBKDF2_ITERATIONS, 120_000):
            candidate = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, iterations
            ).hex()
            if secrets.compare_digest(candidate, verifier_hex):
                return True
        return False
    except (TypeError, ValueError):
        return False


def is_seeded_demo_account(database, profile, account):
    if account.get("is_demo_account") is True:
        return True
    if account.get("is_demo_account") is False:
        return False
    is_demo_account = verify_password(
        profile["password"],
        account.get("password_salt"),
        account.get("password_verifier"),
    )
    if is_demo_account:
        database.users.update_one(
            {"_id": account["_id"]},
            {"$set": {"is_demo_account": True}},
        )
    return is_demo_account


def seed_users(database):
    """Seed demo accounts when enabled on loopback, or bootstrap admin in production."""
    if not DEMO_ACCOUNTS_ENABLED:
        for username, profile in DEMO_USERS.items():
            existing = database.users.find_one({"username": username})
            if existing and is_seeded_demo_account(database, profile, existing):
                database.users.update_one(
                    {"_id": existing["_id"], "enabled": {"$ne": False}},
                    {"$set": {"enabled": False, "demo_disabled_by_policy": True}},
                )

    if APP_ENV == "production":
        if database.users.count_documents({"role": "Admin", "enabled": True}) == 0 and BOOTSTRAP_ADMIN_PASSWORD:
            if len(BOOTSTRAP_ADMIN_PASSWORD) >= 8:
                salt_hex, verifier_hex = hash_password(BOOTSTRAP_ADMIN_PASSWORD)
                database.users.update_one(
                    {"username": "admin"},
                    {"$set": {
                        "id": next_id(database, "users"),
                        "username": "admin",
                        "user_id": "USR-ADMIN",
                        "name": "System Administrator",
                        "role": "Admin",
                        "password_salt": salt_hex,
                        "password_verifier": verifier_hex,
                        "is_demo_account": False,
                        "demo_disabled_by_policy": False,
                        "enabled": True,
                    }},
                    upsert=True,
                )
        return

    if not DEMO_ACCOUNTS_ENABLED:
        return

    for username, profile in DEMO_USERS.items():
        existing = database.users.find_one({"username": username})
        if existing and existing.get("password_salt") and existing.get("password_verifier"):
            if (
                is_seeded_demo_account(database, profile, existing)
                and existing.get("demo_disabled_by_policy")
            ):
                database.users.update_one(
                    {"_id": existing["_id"], "demo_disabled_by_policy": True},
                    {"$set": {"enabled": True, "demo_disabled_by_policy": False}},
                )
            continue
        salt_hex, verifier_hex = hash_password(profile["password"])
        database.users.update_one(
            {"username": username},
            {"$set": {
                "id": existing.get("id") if existing else next_id(database, "users"),
                "username": username,
                "user_id": profile["user_id"],
                "name": profile["name"],
                "role": profile["role"],
                "password_salt": salt_hex,
                "password_verifier": verifier_hex,
                "is_demo_account": True,
                "demo_disabled_by_policy": False,
                "enabled": True,
            }},
            upsert=True,
        )


def authenticate_user(username, password):
    account = db().users.find_one({"username": username.strip().lower(), "enabled": True})
    if not account:
        verify_password(
            password,
            DUMMY_PASSWORD_SALT.hex(),
            DUMMY_PASSWORD_VERIFIER.hex(),
        )
        return None
    if not verify_password(password, account.get("password_salt"), account.get("password_verifier")):
        return None
    return {
        "user_id": account["user_id"],
        "username": account["username"],
        "name": account["name"],
        "role": account["role"],
    }


def login_attempt_key(username):
    normalized_username = username.strip().lower()
    return hashlib.sha256(normalized_username.encode("utf-8")).hexdigest()


def login_lockout_remaining(database, username):
    normalized_username = username.strip().lower()
    if not normalized_username:
        return 0
    account = database.users.find_one({"username": normalized_username}, {"_id": 1})
    if not account:
        return 0
    attempt = database.login_attempts.find_one(
        {"_id": login_attempt_key(normalized_username)},
        {"locked_until": 1},
    )
    if not attempt or not attempt.get("locked_until"):
        return 0
    locked_until = attempt["locked_until"]
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    return max(0, math.ceil((locked_until - datetime.now(timezone.utc)).total_seconds()))


def record_login_failure(database, username):
    normalized_username = username.strip().lower()
    account = database.users.find_one({"username": normalized_username}, {"_id": 1})
    if not account:
        return 0, 0

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=LOGIN_LOCKOUT_SECONDS)
    lockout_until = now + timedelta(seconds=LOGIN_LOCKOUT_SECONDS)
    recent_window = {
        "$gt": [
            {"$ifNull": ["$window_started_at", datetime(1970, 1, 1, tzinfo=timezone.utc)]},
            window_start,
        ]
    }
    attempt = database.login_attempts.find_one_and_update(
        {"_id": login_attempt_key(normalized_username)},
        [
            {"$set": {
                "attempts": {
                    "$cond": [
                        recent_window,
                        {"$add": [{"$ifNull": ["$attempts", 0]}, 1]},
                        1,
                    ]
                },
                "window_started_at": {"$cond": [recent_window, "$window_started_at", now]},
                "expires_at": now + timedelta(seconds=LOGIN_LOCKOUT_SECONDS * 2),
            }},
            {"$set": {
                "locked_until": {
                    "$cond": [
                        {"$gte": ["$attempts", MAX_LOGIN_ATTEMPTS]},
                        lockout_until,
                        "$$REMOVE",
                    ]
                }
            }},
        ],
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    attempts = int(attempt["attempts"])
    return attempts, LOGIN_LOCKOUT_SECONDS if attempts >= MAX_LOGIN_ATTEMPTS else 0


def clear_login_failures(database, username):
    normalized_username = username.strip().lower()
    if normalized_username:
        database.login_attempts.delete_one({"_id": login_attempt_key(normalized_username)})


def refresh_authenticated_identity(username):
    account = db().users.find_one({"username": username.strip().lower(), "enabled": True})
    if not account:
        return None
    return {
        "user_id": account["user_id"],
        "username": account["username"],
        "name": account["name"],
        "role": account["role"],
    }


def create_crew_account(username, full_name, role, password, actor_user, actor_role):
    require_role(actor_role, {"Admin"})
    clean_user = username.strip().lower()
    if not clean_user or not clean_user.replace("_", "").replace(".", "").isalnum():
        raise ValueError("Username must be alphanumeric (underscores/dots allowed).")
    if not full_name.strip():
        raise ValueError("Full name is required.")
    if role not in ROLE_PAGES:
        raise ValueError("Invalid role selected.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")

    database = db()
    salt_hex, verifier_hex = hash_password(password)
    seq = next_id(database, "users")
    user_id = f"USR-{seq:04d}"
    try:
        database.users.insert_one({
            "id": seq,
            "username": clean_user,
            "user_id": user_id,
            "name": full_name.strip(),
            "role": role,
            "password_salt": salt_hex,
            "password_verifier": verifier_hex,
            "is_demo_account": False,
            "demo_disabled_by_policy": False,
            "enabled": True,
        })
    except DuplicateKeyError:
        raise ValueError(f"Username '{clean_user}' already exists.")
    write_audit_row(database, "Created User Account", "", f"Created '{clean_user}' ({role})", actor_user, actor_role)
    return user_id


def update_user_credentials(target_username, new_password, enabled, actor_user, actor_role):
    require_role(actor_role, {"Admin"})
    database = db()
    if target_username == st.session_state.username and not enabled:
        raise ValueError("You cannot disable your own active Admin account.")
    updates = {"enabled": bool(enabled), "demo_disabled_by_policy": False}
    if new_password:
        if len(new_password) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        salt_hex, verifier_hex = hash_password(new_password)
        updates["password_salt"] = salt_hex
        updates["password_verifier"] = verifier_hex
        updates["is_demo_account"] = False
    result = database.users.update_one({"username": target_username}, {"$set": updates})
    if result.matched_count == 1:
        write_audit_row(database, "Updated User Account", "", f"Updated '{target_username}' (enabled={enabled})", actor_user, actor_role)
        return True
    return False


# -----------------------------
# Evidence Validation & Safe Storage
# -----------------------------
def validate_evidence_file(uploaded_file):
    raw_name = uploaded_file.name.replace("\\", "/").split("/")[-1]
    original_name = raw_name.strip()[:180] or "evidence"
    ext = Path(original_name).suffix.lower()

    if ext not in ALLOWED_EVIDENCE_TYPES:
        raise ValueError(f"Unsupported file type '{ext}' for {original_name}. Allowed: PDF, JPG, PNG.")

    data = uploaded_file.getvalue()
    if len(data) == 0:
        raise ValueError(f"File '{original_name}' is empty.")
    if len(data) > MAX_EVIDENCE_BYTES:
        raise ValueError(f"File '{original_name}' exceeds the 20 MB limit.")

    expected_mime, magic_prefix = ALLOWED_EVIDENCE_TYPES[ext]
    declared_mime = (uploaded_file.type or "").strip().lower()
    if declared_mime and declared_mime not in {expected_mime, "application/octet-stream"}:
        raise ValueError(f"MIME type mismatch for '{original_name}' ({declared_mime}).")

    if not data.startswith(magic_prefix):
        raise ValueError(f"File signature check failed for '{original_name}'. Content does not match {ext.upper()}.")

    stored_name = f"{uuid.uuid4().hex}{ext}"
    return original_name, stored_name, expected_mime, data


def safe_evidence_path(stored_name):
    clean_name = Path(str(stored_name)).name
    if not clean_name or clean_name != str(stored_name):
        return None
    candidate = (EVIDENCE_DIR / clean_name).resolve()
    if candidate.parent != EVIDENCE_DIR:
        return None
    return candidate


# -----------------------------
# Database & Schema Integrity
# -----------------------------
DEFAULT_COLUMNS = {
    "records": ["id", "record_id", "annex", "operation", "record_date", "location", "position",
                "quantity", "unit", "equipment", "remarks", "evidence", "status",
                "created_by", "created_by_id", "submitted_on", "reviewed_by", "approved_on", "synced", "created_at"],
    "alerts": ["id", "alert_id", "alert_type", "message", "related_record", "alert_date", "severity", "resolved"],
    "audit": ["id", "event_time", "user_name", "role", "action", "record_id", "details"],
    "attachments": ["id", "record_id", "original_name", "stored_name", "mime_type", "size_bytes", "sha256", "uploaded_at"],
    "library_items": ["id", "slug", "annex", "content_type", "reference", "title", "summary",
                      "source_name", "source_url", "source_version", "source_checked", "created_by"],
    "users": ["id", "username", "user_id", "name", "role", "enabled"],
}
DATABASE_EXPLORER_COLLECTIONS = (
    "records",
    "alerts",
    "audit",
    "attachments",
    "vessel_profile",
    "library_items",
    "users",
    "counters",
)
SENSITIVE_DATABASE_KEYS = {
    "password",
    "passwordhash",
    "passwordsalt",
    "passwordverifier",
    "hashedpassword",
    "token",
    "accesstoken",
    "refreshtoken",
    "secret",
    "clientsecret",
    "apikey",
    "credential",
    "credentials",
    "privatekey",
}


def is_sensitive_database_key(key):
    normalized_key = str(key).replace("_", "").replace("-", "").replace(" ", "").lower()
    return normalized_key in SENSITIVE_DATABASE_KEYS


def sanitize_database_value(value):
    if isinstance(value, dict):
        return {
            key: sanitize_database_value(item)
            for key, item in value.items()
            if not is_sensitive_database_key(key)
        }
    if isinstance(value, list):
        return [sanitize_database_value(item) for item in value]
    return value


def database_document_rows(database, collection_name, limit=100):
    cursor = database[collection_name].find({})
    if collection_name != "counters":
        cursor = cursor.sort("id", -1)
    documents = [sanitize_database_value(document) for document in cursor.limit(limit)]
    rows = [
        {
            key: value
            if value is None or isinstance(value, (str, int, float, bool))
            else json.dumps(value, default=str)
            for key, value in document.items()
        }
        for document in documents
    ]
    return documents, pd.DataFrame(rows)


@st.cache_resource
def mongo_client():
    kwargs = {
        "serverSelectionTimeoutMS": 5000,
        "connectTimeoutMS": 5000,
        "socketTimeoutMS": 10000,
        "retryWrites": True,
        "w": "majority",
    }
    if MONGO_TLS or MONGO_URI.startswith("mongodb+srv://"):
        kwargs["tls"] = True
    return MongoClient(MONGO_URI, **kwargs)


def db():
    return mongo_client()[MONGO_DATABASE]


def next_id(database, collection_name):
    counter = database.counters.find_one_and_update(
        {"_id": collection_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return counter["seq"]


def collection_df(collection_name, query=None, sort=None, projection=None):
    projection = projection or {"_id": 0}
    cursor = db()[collection_name].find(query or {}, projection)
    if sort:
        cursor = cursor.sort(sort)
    documents = list(cursor)
    for document in documents:
        document.pop("_id", None)
    if not documents:
        return pd.DataFrame(columns=DEFAULT_COLUMNS.get(collection_name, []))
    return pd.DataFrame(documents)


def ensure_collection(database, name, validator=None):
    if name not in database.list_collection_names():
        options = {"validator": validator, "validationLevel": "moderate", "validationAction": "error"} if validator else {}
        database.create_collection(name, **options)
    elif validator:
        database.command("collMod", name, validator=validator,
                         validationLevel="moderate", validationAction="error")


def ensure_database_integrity(database):
    schemas = {
        "users": {"$jsonSchema": {
            "bsonType": "object",
            "required": ["username", "user_id", "name", "role", "enabled"],
            "properties": {
                "username": {"bsonType": "string", "minLength": 1},
                "user_id": {"bsonType": "string", "pattern": "^USR-"},
                "role": {"enum": ["Admin", "Chief Engineer", "Officer", "Cadet"]},
                "enabled": {"bsonType": "bool"},
            },
        }},
        "records": {"$jsonSchema": {
            "bsonType": "object",
            "required": ["record_id", "annex", "operation", "status", "created_by"],
            "properties": {
                "record_id": {"bsonType": "string", "minLength": 1},
                "status": {"enum": ["Approved", "Pending"]},
                "quantity": {"bsonType": ["double", "int", "long", "decimal"]},
            },
        }},
        "alerts": {"$jsonSchema": {
            "bsonType": "object",
            "required": ["alert_id", "severity", "resolved"],
            "properties": {
                "alert_id": {"bsonType": "string", "minLength": 1},
                "severity": {"enum": ["Error", "Warning", "Information"]},
                "resolved": {"bsonType": ["int", "long", "bool"]},
            },
        }},
        "audit": {"$jsonSchema": {
            "bsonType": "object",
            "required": ["action", "user_name", "role"],
            "properties": {
                "action": {"bsonType": "string", "minLength": 1},
            },
        }},
        "attachments": {"$jsonSchema": {
            "bsonType": "object",
            "required": ["record_id", "original_name", "stored_name"],
            "properties": {
                "record_id": {"bsonType": "string", "minLength": 1},
                "stored_name": {"bsonType": "string", "minLength": 1},
            },
        }},
    }
    for name, validator in schemas.items():
        ensure_collection(database, name, validator)
    ensure_collection(database, "login_attempts")

    database.users.create_index("username", unique=True)
    database.users.create_index("user_id", unique=True)
    database.login_attempts.create_index("expires_at", expireAfterSeconds=0)
    database.records.create_index("record_id", unique=True)
    database.records.create_index([("status", 1), ("record_date", -1)])
    database.records.create_index([("annex", 1), ("record_date", -1)])
    database.records.create_index([("created_by_id", 1), ("record_date", -1)])
    database.alerts.create_index("alert_id", unique=True)
    database.alerts.create_index([("resolved", 1), ("severity", 1)])
    database.attachments.create_index("stored_name", unique=True)
    database.attachments.create_index("record_id")
    database.audit.create_index("record_id")
    database.audit.create_index([("id", -1)])
    database.library_items.create_index("slug", unique=True)
    database.library_items.create_index([("annex", 1), ("content_type", 1)])


def init_db():
    database = db()
    ensure_database_integrity(database)
    seed_users(database)

    database.library_items.delete_many({"slug": "imo-marpoll-supplements"})
    database.vessel_profile.update_one(
        {"id": 1},
        {"$setOnInsert": {
            "id": 1, "name": VESSEL["name"], "imo": VESSEL["imo"],
            "flag": VESSEL["flag"], "type": VESSEL["type"], "gt": VESSEL["gt"],
            "voyage": VESSEL["voyage"], "route": VESSEL["route"],
        }},
        upsert=True,
    )

    for collection_name in ("records", "alerts", "audit", "attachments", "library_items", "users", "vessel_profile"):
        latest = database[collection_name].find_one({"id": {"$exists": True}}, sort=[("id", -1)])
        if latest:
            database.counters.update_one({"_id": collection_name}, {"$max": {"seq": latest.get("id", 0) or 0}}, upsert=True)

    record_ids = set(database.records.distinct("record_id"))
    orphan_query = {"record_id": {"$nin": list(record_ids)}} if record_ids else {"record_id": {"$exists": True}}
    orphan_attachments = list(database.attachments.find(orphan_query, {"stored_name": 1}))
    if orphan_attachments:
        for attachment in orphan_attachments:
            target = safe_evidence_path(attachment.get("stored_name", ""))
            if target:
                target.unlink(missing_ok=True)
        database.attachments.delete_many({"_id": {"$in": [attachment["_id"] for attachment in orphan_attachments]}})
        write_audit_row(database, "Integrity Repair", "", f"Removed {len(orphan_attachments)} orphan attachment record(s)", "System", "Admin")

    if APP_ENV != "production":
        seed_data()
    seed_library_items()


def seed_data():
    database = db()
    if database.records.count_documents({}) > 0:
        return

    samples = [
        ("ORB-I-000087", "Annex I - Oil", "Sludge Discharge", date(2026, 8, 9), "Arabian Sea", "12°35.6' N, 74°52.3' E", 25.0, "m³", "OWS-01", "Discharged through OWS as per regulation", "Uploaded", "Approved", "Second Engineer", "09 Aug 2026 10:20", "Chief Engineer", "09 Aug 2026 11:05", 1),
        ("SRB-IV-0032", "Annex IV - Sewage", "Sewage Discharge", date(2026, 8, 9), "Arabian Sea", "12°20.1' N, 74°40.2' E", 18.0, "m³", "Sewage Plant", "Treatment completed before discharge", "Uploaded", "Approved", "Second Engineer", "09 Aug 2026 10:15", "Chief Engineer", "09 Aug 2026 10:45", 1),
        ("GRB-V-0082", "Annex V - Garbage", "Food Waste Disposal", date(2026, 8, 8), "Mangalore Anchorage", "12°10.0' N, 74°30.0' E", 12.0, "kg", "Incinerator", "Food waste processed", "Uploaded", "Approved", "Second Engineer", "08 Aug 2026 18:42", "Chief Engineer", "08 Aug 2026 19:05", 1),
        ("ORB-I-0056", "Annex II - NLS", "Cargo Tank Cleaning", date(2026, 8, 8), "Mangalore Anchorage", "12°10.0' N, 74°30.0' E", 30.0, "m³", "Cargo Pump", "Tank cleaning record submitted", "Uploaded", "Pending", "Second Engineer", "08 Aug 2026 09:05", "", "", 1),
        ("PRB-III-0021", "Annex III - Packaged", "Disposal to Port", date(2026, 8, 7), "Mangalore Port", "Mangalore Port", 8.0, "kg", "Cargo Handling", "Transferred to approved reception facility", "Uploaded", "Approved", "Third Officer", "07 Aug 2026 16:30", "Chief Engineer", "07 Aug 2026 17:10", 1),
        ("AIR-VI-0044", "Annex VI - Air", "Fuel Changeover", date(2026, 8, 6), "Arabian Sea", "12°01.2' N, 74°20.0' E", 4.0, "m³", "Main Engine", "Fuel changeover completed", "Uploaded", "Approved", "Second Engineer", "06 Aug 2026 13:10", "Chief Engineer", "06 Aug 2026 14:00", 1),
        ("ORB-I-0091", "Annex I - Oil", "Bilge/Oily Water Discharge", date(2026, 8, 5), "Arabian Sea", "11°50.2' N, 74°10.0' E", 20.0, "m³", "OWS-01", "OWS operation recorded", "Pending", "Pending", "Second Engineer", "05 Aug 2026 12:00", "", "", 1),
        ("GRB-V-0089", "Annex V - Garbage", "Incineration", date(2026, 8, 4), "Singapore", "01°15.2' N, 103°49.0' E", 15.0, "kg", "Incinerator", "Incineration completed", "Uploaded", "Approved", "Third Officer", "04 Aug 2026 17:20", "Chief Engineer", "04 Aug 2026 18:00", 1),
    ]
    record_fields = ["record_id", "annex", "operation", "record_date", "location", "position", "quantity", "unit", "equipment", "remarks", "evidence", "status", "created_by", "submitted_on", "reviewed_by", "approved_on", "synced"]
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    records = []
    for sample in samples:
        document = dict(zip(record_fields, sample))
        document["record_date"] = document["record_date"].isoformat()
        document["created_at"] = timestamp
        document["id"] = next_id(database, "records")
        creator = database.users.find_one({"name": document["created_by"]})
        document["created_by_id"] = creator["user_id"] if creator else ""
        records.append(document)
    if records:
        database.records.insert_many(records)

    alert_fields = ["alert_id", "alert_type", "message", "related_record", "alert_date", "severity"]
    alerts = [
        ("ALT-0003", "Error", "Oil discharge recorded inside prohibited area", "ORB-I-0080", "09 Aug 2026 14:28", "Error"),
        ("ALT-0002", "Warning", "Missing evidence for record", "SRB-IV-0028", "09 Aug 2026 10:15", "Warning"),
        ("ALT-0001", "Warning", "Garbage record not submitted for last 24 hours", "GRB-V-0079", "08 Aug 2026 19:05", "Warning"),
    ]
    database.alerts.insert_many([{**dict(zip(alert_fields, row)), "id": next_id(database, "alerts"), "resolved": 0} for row in alerts])

    audit_fields = ["event_time", "user_name", "role", "action", "record_id", "details"]
    audit_rows = [
        ("09 Aug 2026 11:05 UTC", "Chief Engineer", "Chief Engineer", "Approved", "ORB-I-000087", "Record approved after validation"),
        ("09 Aug 2026 10:20 UTC", "Second Engineer", "Second Engineer", "Submitted", "ORB-I-000087", "Record submitted for approval"),
        ("08 Aug 2026 18:42 UTC", "Third Officer", "Third Officer", "Created", "GRB-V-0082", "Garbage operation recorded"),
        ("08 Aug 2026 09:05 UTC", "Second Engineer", "Second Engineer", "Submitted", "ORB-I-0056", "Awaiting review"),
    ]
    database.audit.insert_many([{**dict(zip(audit_fields, row)), "id": next_id(database, "audit")} for row in audit_rows])


MARPOL_LIBRARY_SEED = [
    ("imo-annex-i", "Annex I - Oil", "Regulations", "MARPOL Annex I",
     "Prevention of pollution by oil",
     "Covers prevention of pollution by oil from operational measures and accidental releases, with additional controls developed over time for ship design and discharge.",
     "International Maritime Organization", "https://www.imo.org/en/about/conventions/pages/international-convention-for-the-prevention-of-pollution-from-ships-%28marpol%29.aspx", "MARPOL overview", "09 Oct 2026"),
    ("imo-annex-ii", "Annex II - NLS", "Regulations", "MARPOL Annex II",
     "Control of pollution by noxious liquid substances in bulk",
     "Sets controls for noxious liquid substances carried in bulk, including substance categorization, discharge controls, and reception-facility requirements.",
     "International Maritime Organization", "https://www.imo.org/en/about/conventions/pages/international-convention-for-the-prevention-of-pollution-from-ships-%28marpol%29.aspx", "MARPOL overview", "09 Oct 2026"),
    ("imo-annex-iii", "Annex III - Packaged", "Regulations", "MARPOL Annex III",
     "Prevention of pollution by harmful substances in packaged form",
     "Addresses packing, marking and labelling, documentation, stowage, quantity limits, exceptions, and notifications for harmful substances carried in packaged form.",
     "International Maritime Organization", "https://www.imo.org/en/about/conventions/pages/international-convention-for-the-prevention-of-pollution-from-ships-%28marpol%29.aspx", "MARPOL overview", "09 Oct 2026"),
    ("imo-annex-iv", "Annex IV - Sewage", "Regulations", "MARPOL Annex IV",
     "Prevention of pollution by sewage from ships",
     "Sets requirements intended to control pollution of the sea by sewage from ships, including relevant shipboard systems and discharge controls.",
     "International Maritime Organization", "https://www.imo.org/en/about/conventions/pages/international-convention-for-the-prevention-of-pollution-from-ships-%28marpol%29.aspx", "MARPOL overview", "09 Oct 2026"),
    ("imo-annex-v", "Annex V - Garbage", "Regulations", "MARPOL Annex V",
     "Prevention of pollution by garbage from ships",
     "Covers garbage from ships, restricts discharge at sea, and prohibits the discharge of plastics into the sea.",
     "International Maritime Organization", "https://www.imo.org/en/about/conventions/pages/international-convention-for-the-prevention-of-pollution-from-ships-%28marpol%29.aspx", "MARPOL overview", "09 Oct 2026"),
    ("imo-annex-vi", "Annex VI - Air", "Regulations", "MARPOL Annex VI",
     "Prevention of air pollution from ships",
     "Covers ship air pollution controls, including ozone-depleting substances, nitrogen oxides, sulphur oxides, emission control areas, and energy-efficiency and greenhouse-gas measures.",
     "International Maritime Organization", "https://www.imo.org/en/about/conventions/pages/international-convention-for-the-prevention-of-pollution-from-ships-%28marpol%29.aspx", "MARPOL overview", "09 Oct 2026"),
    ("imo-consolidated-edition", "General", "Official source", "MARPOL Consolidated Edition 2022",
     "Official consolidated publication",
     "IMO lists the MARPOL Consolidated Edition 2022 in its publications catalogue. Check the publication page for the current edition and applicable supplements.",
     "International Maritime Organization", "https://www.imo.org/en/publications/pages/currentpublications.aspx", "2022 edition; see current catalogue", "09 Oct 2026"),
    ("imo-marpol-supplements", "General", "Official source", "MARPOL amendments and supplements",
     "Current amendments and supplements",
     "IMO's English publications page lists supplements to MARPOL consolidated publications. Confirm the latest supplement and effective date against the official source before relying on a provision.",
     "International Maritime Organization", "https://www.imo.org/en/publications/pages/english.aspx", "Page reviewed 09 Oct 2026", "09 Oct 2026"),
    ("imo-annex-vi-publication", "Annex VI - Air", "Official source", "MARPOL Annex VI / NTC 2008",
     "Official Annex VI publication listing",
     "IMO's current publications catalogue lists the MARPOL Annex VI and NTC 2008 publication. Follow the catalogue for the current publication and supplements.",
     "International Maritime Organization", "https://www.imo.org/en/publications/pages/currentpublications.aspx", "2023 edition listed", "09 Oct 2026"),
]


def seed_library_items():
    database = db()
    for item in MARPOL_LIBRARY_SEED:
        slug, annex, content_type, reference, title, summary, source_name, source_url, source_version, source_checked = item
        if not database.library_items.find_one({"slug": slug}):
            database.library_items.insert_one({
                "id": next_id(database, "library_items"), "slug": slug, "annex": annex,
                "content_type": content_type, "reference": reference, "title": title,
                "summary": summary, "source_name": source_name, "source_url": source_url,
                "source_version": source_version, "source_checked": source_checked,
                "created_by": "IMO index",
            })


def load_vessel_profile():
    row = db().vessel_profile.find_one({"id": 1}, {"_id": 0, "name": 1, "imo": 1, "flag": 1, "type": 1, "gt": 1, "voyage": 1, "route": 1})
    return row or {}


def save_vessel_profile(profile, user, role):
    require_role(role, {"Admin"})
    database = db()
    database.vessel_profile.update_one(
        {"id": 1},
        {"$set": {key: profile[key] for key in ("name", "imo", "flag", "type", "gt", "voyage", "route")}},
    )
    write_audit_row(database, "Updated Vessel Profile", "", f"Vessel profile updated for IMO {profile['imo']}", user, role)


def write_audit_row(database, action, record_id, details, user, role):
    database.audit.insert_one({
        "id": next_id(database, "audit"),
        "event_time": utc_now_str(),
        "user_name": user, "role": role, "action": action,
        "record_id": record_id, "details": details,
    })


def add_audit(action, record_id="", details="", user="Chief Engineer", role="Chief Engineer"):
    write_audit_row(db(), action, record_id, details, user, role)


def save_operation_record(record, uploaded_files, user, role):
    require_role(role, {"Admin", "Chief Engineer", "Officer", "Cadet"})
    validated_files = [validate_evidence_file(f) for f in (uploaded_files or [])]

    stored_files = []
    try:
        if validated_files:
            EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
            for original_name, stored_name, mime, data in validated_files:
                target = safe_evidence_path(stored_name)
                if target is None:
                    raise ValueError("Invalid evidence storage target path.")
                target.write_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
                stored_files.append((original_name, stored_name, mime, len(data), digest))

        database = db()
        fields = ["record_id", "annex", "operation", "record_date", "location", "position", "quantity", "unit", "equipment", "remarks", "evidence", "status", "created_by", "submitted_on", "synced", "created_at"]
        document = dict(zip(fields, record))
        creator = database.users.find_one({"name": document["created_by"]})
        document["created_by_id"] = creator["user_id"] if creator else ""
        document["reviewed_by"] = ""
        document["approved_on"] = ""
        document["id"] = next_id(database, "records")
        database.records.insert_one(document)
        if stored_files:
            database.attachments.insert_many([
                {"id": next_id(database, "attachments"), "record_id": record[0],
                 "original_name": name, "stored_name": stored_name, "mime_type": mime,
                 "size_bytes": size_bytes, "sha256": digest,
                 "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                for name, stored_name, mime, size_bytes, digest in stored_files
            ])
        write_audit_row(database, "Submitted", record[0], f"{record[1]} / {record[2]}", user, role)
    except Exception:
        for _, stored_name, _, _, _ in stored_files:
            target = safe_evidence_path(stored_name)
            if target:
                target.unlink(missing_ok=True)
        raise


def review_record(record_id, action, user, role):
    require_role(role, {"Admin", "Chief Engineer"})
    database = db()
    if action == "Approved":
        now = utc_now_str()
        result = database.records.update_one(
            {"record_id": record_id, "status": "Pending"},
            {"$set": {"status": "Approved", "reviewed_by": user, "approved_on": now}},
        )
        details = "Record approved after review"
    elif action == "Returned":
        result = database.records.update_one(
            {"record_id": record_id, "status": "Pending"}, {"$set": {"evidence": "Pending"}}
        )
        details = "Returned for supporting evidence"
    else:
        raise ValueError("Unsupported review action")
    if result.matched_count != 1:
        return False
    write_audit_row(database, action, record_id, details, user, role)
    return True


def resolve_alert(alert_id, record_id, alert_type, user, role):
    require_role(role, {"Admin", "Chief Engineer"})
    database = db()
    result = database.alerts.update_one(
        {"alert_id": alert_id, "resolved": 0}, {"$set": {"resolved": 1}}
    )
    if result.modified_count != 1:
        return False
    write_audit_row(database, "Resolved Alert", record_id, f"Resolved {alert_id}: {alert_type}", user, role)
    return True


def process_demo_queue(user, role):
    require_role(role, {"Admin"})
    database = db()
    result = database.records.update_many({"synced": 0}, {"$set": {"synced": 1}})
    write_audit_row(database, "Demo Queue Update", "", f"Marked {result.modified_count} local record(s) processed; no server transfer occurred", user, role)
    return result.modified_count


def live_vessel_position():
    t = int(time.time() // 30)
    lat = VESSEL["base_lat"] + 0.00008 * math.sin(t / 7)
    lon = VESSEL["base_lon"] + 0.00012 * math.cos(t / 9)
    return lat, lon


def dms(lat, lon):
    def one(v, pos, neg):
        a = abs(v)
        deg = int(a)
        minutes = (a - deg) * 60
        return f"{deg:02d}°{minutes:05.2f}' {pos if v >= 0 else neg}"
    return one(lat, 'N', 'S'), one(lon, 'E', 'W')


def login_screen():
    left, right = st.columns([1.1, .9], gap="small")
    with left:
        ship_art = asset_data_uri("ship_hero.svg")
        ui(f'<div class="login-visual"><img class="login-ship-art" src="{ship_art}" alt=""/><div class="login-copy">'
           '<div class="login-tag">SHIPBOARD ENVIRONMENTAL OPERATIONS</div>'
           '<h1>MARPOL<span>-SAFE</span></h1>'
           '<div class="login-points">'
           '<div><i>✓</i>Record operations across MARPOL Annex I – VI</div>'
           '<div><i>✓</i>Attach validated evidence and route for approval</div>'
           '<div><i>✓</i>Keep a complete, UTC-stamped audit history</div></div>'
           '<div class="login-tag">ANNEX I — VI &nbsp; • &nbsp; VESSEL PROFILE &nbsp; • &nbsp; AUDIT HISTORY</div></div></div>')
    with right:
        env_badge = "PROD" if APP_ENV == "production" else "DEMO"
        ui(f'<div class="login-brand"><span class="login-brand-mark">MS</span> MARPOL-SAFE <small>{env_badge}</small></div>')
        ui('<div class="login-card-title">Welcome aboard</div><p class="login-muted">Sign in to the shipboard compliance console.</p>')

        database = db()
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter username")
            password = st.text_input("Password", type="password", placeholder="Enter password")
            submitted = st.form_submit_button("SIGN IN  →", type="primary", width="stretch")

        remaining = login_lockout_remaining(database, username)
        is_locked = remaining > 0

        if submitted:
            identity = authenticate_user(username, password)
            if identity and not is_locked:
                clear_login_failures(database, identity["username"])
                st.session_state.authenticated = True
                st.session_state.user_id = identity["user_id"]
                st.session_state.username = identity["username"]
                st.session_state.user = identity["name"]
                st.session_state.role = identity["role"]
                add_audit("Login", "", f"Successful login from {identity['role']}", identity["name"], identity["role"])
                st.rerun()
            else:
                if not is_locked:
                    record_login_failure(database, username)
                st.error("Invalid username or password, or sign-in temporarily paused. Try again shortly.")

        if DEMO_ACCOUNTS_ENABLED:
            account_rows = "".join(
                f'<div class="login-acc"><code>{esc(name)}</code><code>{esc(info["password"])}</code><span>{esc(info["role"])}</span></div>'
                for name, info in DEMO_USERS.items())
            ui(f'<div class="login-accounts"><div class="login-accounts-head">Local demo accounts · username / password</div>{account_rows}</div>')
        ui('<div class="login-security"><span class="security-chip">🔐 ROLE WORKSPACES</span><span class="security-chip">🗄️ MONGODB BACKEND</span><span class="security-chip">⚓ PBKDF2-SHA256</span></div>')


# -----------------------------
# Helpers
# -----------------------------
def approval_rate(df):
    if df.empty:
        return 0
    return round((df["status"] == "Approved").sum() / len(df) * 100)


def style_figure(fig, height=320):
    fig.update_layout(
        template="plotly_dark",
        height=height,
        margin=dict(l=8, r=12, t=14, b=14),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI Variable Text, Segoe UI, system-ui, sans-serif", size=12, color="#8b9eb0"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            title_text="",
            font=dict(size=12, color="#cbd5e1"),
        ),
        hoverlabel=dict(bgcolor="#162028", font_color="#f1f5f9", bordercolor="rgba(45,212,191,.35)"),
        bargap=0.32,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor="rgba(148,179,199,.16)", ticks="outside", tickcolor="rgba(148,179,199,.16)", tickfont=dict(color="#8b9eb0"), title_font=dict(size=11))
    fig.update_yaxes(showgrid=True, gridcolor="rgba(148,179,199,.08)", zeroline=False, linecolor="rgba(0,0,0,0)", tickfont=dict(color="#8b9eb0"), title_font=dict(size=11))
    return fig


def records_for_user(user_id, user_name, role):
    if role == "Cadet":
        return collection_df(
            "records",
            {"$or": [{"created_by_id": user_id}, {"created_by": user_name}]},
            [("record_date", -1)],
        )
    return collection_df("records", sort=[("record_date", -1), ("id", -1)])


def format_record_datetime(value):
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value or "")
    if len(str(value).strip()) > 10:
        return parsed.strftime("%d %b %Y · %H:%M")
    return parsed.strftime("%d %b %Y")


def generate_id(annex):
    prefix = {"Annex I - Oil": "ORB-I", "Annex II - NLS": "CRB-II", "Annex III - Packaged": "PRB-III",
              "Annex IV - Sewage": "SRB-IV", "Annex V - Garbage": "GRB-V", "Annex VI - Air": "AIR-VI"}[annex]
    n = random.randint(1000, 9999)
    return f"{prefix}-{n:04d}"


# -----------------------------
# Session State & DB Init
# -----------------------------
for key, default in [
    ("offline", False),
    ("authenticated", False),
    ("user", ""),
    ("role", ""),
    ("user_id", ""),
    ("username", ""),
]:
    if key not in st.session_state:
        st.session_state[key] = default

try:
    init_db()
    VESSEL.update(load_vessel_profile())
except PyMongoError as error:
    st.error("MongoDB connection failed. Start MongoDB or set MONGODB_URI to a reachable MongoDB connection string.")
    st.code(str(error))
    st.stop()

if st.session_state.authenticated and st.session_state.username:
    current_identity = refresh_authenticated_identity(st.session_state.username)
    if current_identity:
        st.session_state.user_id = current_identity["user_id"]
        st.session_state.user = current_identity["name"]
        st.session_state.role = current_identity["role"]
    else:
        st.session_state.authenticated = False
        st.session_state.user_id = ""
        st.session_state.username = ""
        st.session_state.user = ""
        st.session_state.role = ""


def refresh_rule_alerts():
    records = collection_df("records")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rules = []
    for _, row in records.iterrows():
        rid = str(row.get("record_id", ""))
        if not rid:
            continue
        evidence = str(row.get("evidence", "Pending"))
        position = str(row.get("position", "") or "").strip()
        try:
            qty = float(row.get("quantity", 0) or 0)
        except (TypeError, ValueError):
            qty = 0
        if evidence not in ("Uploaded", "Not Applicable"):
            rules.append((f"RULE-{rid}-EVIDENCE", "Missing evidence", f"Supporting evidence is {evidence.lower()} for {rid}.", rid, "Warning", "Attach the supporting document or confirm why evidence is not applicable."))
        if not position or position.lower() in {"nan", "none", "n/a"}:
            rules.append((f"RULE-{rid}-POSITION", "Missing position", f"Position is missing for operation {rid}.", rid, "Error", "Confirm the operation position against the approved onboard navigation source."))
        if qty <= 0:
            rules.append((f"RULE-{rid}-QUANTITY", "Quantity validation", f"Quantity is zero, negative or unavailable for {rid}.", rid, "Error", "Verify the quantity and unit before approval."))
        if str(row.get("status", "")) == "Pending":
            submitted = str(row.get("submitted_on", "") or "")
            age_hours = None
            for fmt in ("%d %b %Y %H:%M", "%d %b %Y %H:%M UTC", "%Y-%m-%d %H:%M:%S"):
                try:
                    age_hours = (now - datetime.strptime(submitted, fmt)).total_seconds() / 3600
                    break
                except ValueError:
                    pass
            if age_hours is not None and age_hours >= 24:
                rules.append((f"RULE-{rid}-PENDING", "Approval overdue", f"Record {rid} has been pending for at least 24 hours.", rid, "Warning", "Review the record, request missing information, or document the reason for delay."))
        op = str(row.get("operation", "")).lower()
        location = str(row.get("location", "")).lower()
        if "discharge" in op and any(term in location for term in ("port", "anchorage")):
            rules.append((f"RULE-{rid}-LOCATION", "Discharge location review", f"Review the location and applicable restrictions for {rid} before approval.", rid, "Warning", "Verify the operation against the vessel's approved procedures, voyage context and applicable requirements."))

    database = db()
    for aid, atype, message, rid, severity, action in rules:
        if database.alerts.find_one({"alert_id": aid}, {"_id": 1}) is None:
            database.alerts.insert_one({
                "id": next_id(database, "alerts"), "alert_id": aid,
                "alert_type": atype, "message": message + "\nRecommended action: " + action,
                "related_record": rid, "alert_date": utc_now_str(),
                "severity": severity, "resolved": 0,
            })


refresh_rule_alerts()

if not st.session_state.authenticated:
    login_screen()
    st.stop()


# -----------------------------
# Sidebar
# -----------------------------
def initials(name):
    parts = [p for p in str(name).split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


with st.sidebar:
    ui('<div class="ms-brand"><div class="ms-brand-mark">MS</div><div><div class="ms-brand-name">MARPOL-SAFE</div><div class="ms-brand-kicker">Shipboard operations</div></div></div>')
    st.divider()

    pages = ROLE_PAGES.get(st.session_state.role, ["Dashboard"])
    page = st.radio("YOUR WORKSPACE", pages, label_visibility="visible")

    st.divider()
    ui(f'<div class="ms-side-label">Vessel context</div>'
       f'<div class="ms-sidecard"><div class="ms-sidecard-title">{esc(VESSEL["name"])}</div>'
       f'<div class="ms-sidecard-meta">IMO {esc(VESSEL["imo"])} · {esc(VESSEL["flag"])}<br>'
       f'{esc(VESSEL["type"])} · {esc(VESSEL["gt"])}<br>Voyage {esc(VESSEL["voyage"])}</div></div>')

    st.divider()
    ui(f'<div class="ms-side-label">Signed in</div>'
       f'<div class="ms-sidecard"><div class="ms-user"><div class="ms-avatar">{esc(initials(st.session_state.user))}</div>'
       f'<div><div class="ms-sidecard-title">{esc(st.session_state.user)}</div>'
       f'<span class="ms-rolepill">{esc(st.session_state.role)}</span></div></div>'
       f'<div class="ms-sidecard-meta">{esc(ROLE_SUMMARY.get(st.session_state.role, ""))}<br>{len(pages)} workspaces available</div></div>')
    if st.button("Sign out", width="stretch"):
        add_audit("Logout", "", "User signed out", st.session_state.user, st.session_state.role)
        st.session_state.authenticated = False
        st.session_state.user = ""
        st.session_state.role = ""
        st.session_state.user_id = ""
        st.session_state.username = ""
        st.rerun()

    st.divider()
    mode = "Offline queue demo" if st.session_state.offline else f"{APP_ENV.capitalize()} mode"
    st.caption(f"Mode · {mode}")
    if st.button("Toggle offline queue", width="stretch"):
        st.session_state.offline = not st.session_state.offline
        st.rerun()


if page not in ROLE_PAGES.get(st.session_state.role, []):
    st.error("Access denied: your role is not permitted to open this module.")
    st.stop()


# -----------------------------
# Header Bar
# -----------------------------
lat, lon = live_vessel_position()
lat_s, lon_s = dms(lat, lon)
now_live = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
connection_tone = "warn" if st.session_state.offline else "good"
connection_text = "OFFLINE QUEUE" if st.session_state.offline else f"MONGODB · {APP_ENV.upper()}"
ui(f'<div class="ms-topbar"><div class="ms-topbar-group">'
   f'<span class="ms-pill t-{connection_tone}">{connection_text}</span>'
   f'<span class="ms-topbar-item"><b>{esc(VESSEL["name"])}</b></span><span class="ms-dot-sep"></span>'
   f'<span class="ms-topbar-item">IMO {esc(VESSEL["imo"])}</span><span class="ms-dot-sep"></span>'
   f'<span class="ms-topbar-item">Voyage {esc(VESSEL["voyage"])}</span><span class="ms-dot-sep"></span>'
   f'<span class="ms-topbar-item">{esc(VESSEL["route"])}</span></div>'
   f'<div class="ms-topbar-group">'
   f'<span class="ms-topbar-item" title="Simulated coordinates">{icon_svg("pin")}{esc(lat_s)} · {esc(lon_s)} (sim)</span>'
   f'<span class="ms-topbar-item">{icon_svg("clock")}{esc(now_live)}</span></div></div>')
render_flash()


# ============================================================
# DASHBOARD
# ============================================================
if page == "Dashboard":
    hero_image = asset_data_uri("ship_hero.svg")
    ui(f"""
    <div class="dashboard-hero">
      <div class="hero-copy">
        <div class="hero-kicker">VOYAGE CONTROL · {esc(VESSEL['voyage'])}</div>
        <div class="hero-title" role="heading" aria-level="1"><span class="hero-title-accent">Environmental</span><br>operations overview</div>
        <div class="hero-tags">
          <div class="hero-tag">
            <span class="hero-tag-label">Vessel details</span>
            <span class="hero-tag-value">{esc(VESSEL['name'])} · IMO {esc(VESSEL['imo'])} · {esc(VESSEL['flag'])}</span>
          </div>
          <div class="hero-tag">
            <span class="hero-tag-label">Signed in</span>
            <span class="hero-tag-value">{esc(st.session_state.user)} · {esc(st.session_state.role)}</span>
          </div>
        </div>
      </div>
      <div class="hero-art"><img src="{hero_image}" alt="Cargo vessel illustration"></div>
    </div>
    """)
    section_title("Operations snapshot", "Records, approvals, and screening prompts are drawn from MongoDB.")
    if st.session_state.role == "Cadet":
        st.info("Your dashboard is limited to records created by your account.")

    period_col, _ = st.columns([1.2, 3.8])
    with period_col:
        period = st.selectbox("Reporting period", ["30 days", "90 days", "12 months", "All records"], index=2)
    df = records_for_user(st.session_state.user_id, st.session_state.user, st.session_state.role)
    df["record_date_parsed"] = pd.to_datetime(df["record_date"], errors="coerce", format="mixed")
    if period != "All records":
        days = {"30 days": 30, "90 days": 90, "12 months": 365}[period]
        cutoff = pd.Timestamp(date.today() - timedelta(days=days))
        df = df[df["record_date_parsed"] >= cutoff].copy()
    alerts = collection_df("alerts", {"resolved": 0}) if st.session_state.role != "Cadet" else pd.DataFrame()
    total = len(df)
    pending = int(df["status"].eq("Pending").sum()) if total else 0
    approved = int(df["status"].eq("Approved").sum()) if total else 0
    linked_files = collection_df("attachments", projection={"_id": 0, "record_id": 1})
    evidence_count = int(linked_files["record_id"].isin(df["record_id"]).sum()) if total and not linked_files.empty else 0

    kpi_grid([
        ("Records in period", total, period, "teal", "file"),
        ("Approval completion", f"{approval_rate(df)}%", f"{approved} approved of {total}", "good", "check"),
        ("Awaiting review", pending, "Pending workflow", "warn", "clock"),
        ("Open screening prompts", len(alerts), "Requires human review", "bad" if len(alerts) else "good", "alert"),
        ("Evidence files saved", evidence_count, "Validated & linked", "info", "clip"),
        ("Awaiting sync", int(df["synced"].eq(0).sum()) if total else 0, "Local queue", "muted", "sync"),
    ])

    st.caption("Approval completion describes workflow state only; it does not assess regulatory compliance. Screening prompts require review by qualified personnel.")

    monthly_source = df.dropna(subset=["record_date_parsed"]).copy()
    if not monthly_source.empty:
        monthly_source["Month"] = monthly_source["record_date_parsed"].dt.to_period("M").dt.to_timestamp()
        monthly = monthly_source.groupby(["Month", "status"]).size().reset_index(name="Records")
    else:
        monthly = pd.DataFrame(columns=DEFAULT_COLUMNS.get("records", []))
    annex_counts = df.groupby("annex").size().reset_index(name="Records").sort_values("Records", ascending=True) if total else pd.DataFrame(columns=DEFAULT_COLUMNS.get("records", []))
    if not annex_counts.empty:
        leading_annex = annex_counts.iloc[-1]
        share = round(int(leading_annex["Records"]) / total * 100)
        st.info(
            f"{total} records in this period: {approved} approved and {pending} pending. "
            f"Most activity: {leading_annex['annex']} ({int(leading_annex['Records'])}, {share}%)."
        )

    chart_left, chart_right = st.columns([1.35, 1])
    with chart_left:
        with st.container(border=True):
            card_title("Monthly record activity", "Submitted operations by month and review state")
            if monthly.empty:
                st.info("Record activity will appear here after entries are submitted.")
            else:
                fig = px.bar(monthly, x="Month", y="Records", text="Records", color="status", barmode="stack",
                             color_discrete_map={"Approved": "#34d399", "Pending": "#e5b567"},
                             labels={"Month": "Month", "Records": "Records submitted", "status": "Review status"})
                fig.update_traces(
                    textposition="inside",
                    hovertemplate="%{x|%b %Y}<br>%{fullData.name}: %{y} records<extra></extra>",
                )
                fig.update_xaxes(title_text="Month", type="date", tickformat="%b %Y", dtick="M1")
                fig.update_yaxes(title_text="Records submitted", dtick=1)
                st.plotly_chart(style_figure(fig, 340), width="stretch", config={"displayModeBar": False})
    with chart_right:
        with st.container(border=True):
            card_title("Record review state", "Share of records by approval workflow status")
            state_counts = df["status"].value_counts().rename_axis("Status").reset_index(name="Records") if total else pd.DataFrame(columns=["Status", "Records"])
            if state_counts.empty:
                st.info("The status chart will appear after records are submitted.")
            else:
                fig = px.pie(state_counts, names="Status", values="Records", hole=.68,
                             color="Status", color_discrete_map={"Approved": "#34d399", "Pending": "#e5b567"},
                             labels={"Status": "Review state"})
                fig.update_traces(
                    textposition="inside",
                    textinfo="label+value+percent",
                    sort=False,
                    hovertemplate="%{label}: %{value} records (%{percent})<extra></extra>",
                )
                fig.add_annotation(text=f"{total}<br><span style='font-size:11px'>records</span>", x=.5, y=.5,
                                   xref="paper", yref="paper", showarrow=False,
                                   font=dict(size=20, color="#f1f5f9"))
                st.plotly_chart(style_figure(fig, 340), width="stretch", config={"displayModeBar": False})

    lower_left, lower_right = st.columns([1, 1.35])
    with lower_left:
        with st.container(border=True):
            card_title("Activity by MARPOL annex", "Submitted records in the selected period")
            if annex_counts.empty:
                st.info("Annex activity will appear here after records are submitted.")
            else:
                fig = px.bar(annex_counts, x="Records", y="annex", orientation="h", text="Records",
                             color_discrete_sequence=["#2dd4bf"],
                             labels={"annex": "MARPOL annex", "Records": "Records"})
                fig.update_traces(
                    textposition="outside",
                    cliponaxis=False,
                    marker_line_width=0,
                    hovertemplate="%{y}<br>%{x} records<extra></extra>",
                )
                fig.update_xaxes(title_text="Number of records", dtick=1)
                fig.update_yaxes(title_text="MARPOL annex")
                st.plotly_chart(style_figure(fig, 340), width="stretch", config={"displayModeBar": False})
    with lower_right:
        with st.container(border=True):
            card_title("Recent operations", "The latest records in the selected period")
            recent = df.head(7)[["record_id", "annex", "operation", "record_date", "status"]].copy()
            recent["record_date"] = recent["record_date"].map(format_record_datetime)
            recent.columns = ["Record ID", "Annex", "Operation", "Date", "Status"]
            recent["Status"] = recent["Status"].map(status_label)
            if recent.empty:
                st.info("New operations will appear here after submission.")
            else:
                st.dataframe(recent, hide_index=True, width="stretch")

    section_title("Vessel profile", "Current vessel and voyage details")
    with st.container(border=True):
        ui(kv_html([("Vessel", VESSEL["name"]), ("IMO", VESSEL["imo"]), ("Flag", VESSEL["flag"]),
                    ("Type", f"{VESSEL['type']} · {VESSEL['gt']}"), ("Voyage", VESSEL["voyage"]), ("Route", VESSEL["route"])]))
        st.caption(f"Demo position: {lat_s}, {lon_s} • Simulated coordinates (not wired to onboard NMEA/GPS).")


# ============================================================
# RECORD OPERATION
# ============================================================
elif page == "Record an Operation":
    page_header("Operations", "Record an operation",
                "Capture an operation, attach validated supporting files, and submit it to the review queue.")
    ui('<div class="ms-steps">'
       '<span class="ms-step"><span class="ms-step-n">1</span>Choose category</span>'
       '<span class="ms-step"><span class="ms-step-n">2</span>Enter details</span>'
       '<span class="ms-step"><span class="ms-step-n">3</span>Attach evidence</span>'
       '<span class="ms-step"><span class="ms-step-n">4</span>Submit for review</span></div>')

    with st.container(border=True):
        form_section("1", "Choose the category", "Pick the MARPOL annex, then the specific operation.")
        cat_a, cat_b = st.columns(2)
        with cat_a:
            annex = st.selectbox("Select Annex / Operation Category", list(ANNEXES.keys()))
        with cat_b:
            op = st.selectbox("Operation", OPERATIONS[annex])

        guidance = {
            "Annex I - Oil": "Oil Record Book",
            "Annex II - NLS": "Cargo Record Book",
            "Annex III - Packaged": "Packaged goods record",
            "Annex IV - Sewage": "Sewage Record Book",
            "Annex V - Garbage": "Garbage Record Book",
            "Annex VI - Air": "Air emissions record",
        }
        callout("teal", f'<b>Reference:</b> {esc(guidance[annex])}')

    with st.form("operation_form"):
        form_section("2", "When and where", "Date, time and position of the operation.")
        w1, w2 = st.columns(2)
        with w1:
            record_date = st.date_input("Date", value=date.today())
            position = st.text_input("Position (Latitude / Longitude)", f"{lat_s}, {lon_s}")
        with w2:
            record_time = st.time_input("Time")
            location = st.selectbox("Location", LOCATIONS)
        callout("info", f"<b>Demo position:</b> {esc(lat_s)}, {esc(lon_s)}. Verify against the approved navigation source.")

        form_section("3", "Quantity and equipment", "How much, in which unit, and using what equipment.")
        q1, q2 = st.columns(2)
        with q1:
            quantity = st.number_input("Quantity", min_value=0.0, value=25.0, step=0.5)
        with q2:
            unit = st.selectbox("Unit", ["m³", "kg", "L", "tonnes", "hours"])
        equipment = st.text_input("Equipment Used", "OWS-01 / Applicable Equipment")
        remarks = st.text_area("Remarks", "Operation completed in accordance with applicable MARPOL requirements.")

        form_section("4", "Supporting evidence", "PDF, JPG or PNG files up to 20 MB each.")
        uploaded = st.file_uploader(
            "Attach evidence files",
            type=["pdf", "jpg", "jpeg", "png"],
            accept_multiple_files=True,
            help="Validated for extension, MIME type, magic bytes, and 20 MB limit.",
        )
        evidence_state = st.selectbox("Evidence status when no file is attached", ["Pending", "Not Applicable"])

        submitted = st.form_submit_button("Submit for review  →", type="primary", width="stretch")

    if submitted:
        errors = []
        evidence = "Uploaded" if uploaded else evidence_state
        if not position.strip():
            errors.append("Position is required.")
        if quantity <= 0:
            errors.append("Quantity must be greater than zero.")
        if not equipment.strip():
            errors.append("Equipment is required.")
        for file in (uploaded or []):
            try:
                validate_evidence_file(file)
            except ValueError as val_err:
                errors.append(str(val_err))

        if errors:
            st.error("Validation failed: " + " ".join(errors))
        else:
            rid = generate_id(annex)
            while not collection_df("records", {"record_id": rid}, projection={"_id": 0, "record_id": 1}).empty:
                rid = generate_id(annex)

            now = utc_now_str()
            record_timestamp = datetime.combine(record_date, record_time).isoformat(timespec="minutes")
            record = (rid, annex, op, record_timestamp, location, position, quantity, unit,
                      equipment, remarks, evidence, "Pending", st.session_state.user, now, 0,
                      datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
            try:
                save_operation_record(record, uploaded or [], st.session_state.user, st.session_state.role)
            except (PyMongoError, OSError, ValueError, PermissionError) as err:
                st.error(f"The record could not be saved: {err}")
            else:
                st.session_state["last_record"] = rid
                flash("success", f"Record {rid} was saved and submitted for review.")
                if uploaded:
                    flash("info", f"{len(uploaded)} evidence file(s) were validated and linked to the record.")
                st.rerun()

    if "last_record" in st.session_state:
        ui(f'<div class="ms-latest">Latest record <code>{esc(st.session_state.last_record)}</code></div>')


# ============================================================
# MARPOL RECORDS
# ============================================================
elif page == "MARPOL Records":
    page_header("Records", "MARPOL records",
                "Search, filter and review operational records stored in MongoDB.")

    with st.container(border=True):
        c1, c2, c3, c4, c5 = st.columns([1.3, 1, 1, 1, 1.45])
        with c1: annex_filter = st.selectbox("Annex", ["All"] + list(ANNEXES.keys()))
        with c2: status_filter = st.selectbox("Status", ["All", "Approved", "Pending"])
        with c3: date_from = st.date_input("From", value=date.today() - timedelta(days=365))
        with c4: date_to = st.date_input("To", value=date.today())
        with c5: record_search = st.text_input("Search", placeholder="ID, operation, location")

    if st.session_state.role == "Cadet":
        df = records_for_user(st.session_state.user_id, st.session_state.user, st.session_state.role)
        st.info("Cadet view: only entries created by your account are shown.")
    else:
        df = collection_df("records", sort=[("record_date", -1)])

    if annex_filter != "All":
        df = df[df.annex == annex_filter]
    if status_filter != "All":
        df = df[df.status == status_filter]
    if date_from > date_to:
        st.warning("The start date is after the end date. Please adjust the date range.")
        df = df.iloc[0:0]
    elif not df.empty:
        dates = pd.to_datetime(df.record_date, errors="coerce", format="mixed").dt.date
        df = df[(dates >= date_from) & (dates <= date_to)]
    if record_search.strip() and not df.empty:
        searchable = df[["record_id", "annex", "operation", "location", "created_by"]].astype(str)
        match = searchable.apply(lambda column: column.str.contains(record_search.strip(), case=False, na=False, regex=False)).any(axis=1)
        df = df[match]

    approved_shown = int((df.status == "Approved").sum())
    pending_shown = int((df.status == "Pending").sum())
    ui(f'<div class="ms-toolbar"><span class="ms-count">{len(df)} <span>records shown</span></span>'
       f'{pill(f"{approved_shown} approved", "good")}{pill(f"{pending_shown} pending", "warn")}</div>')
    display = df[["record_id", "annex", "operation", "record_date", "location", "status", "evidence", "created_by", "synced"]].copy()
    display["record_date"] = display["record_date"].map(format_record_datetime)
    display["synced"] = display["synced"].map({0: "Queued", 1: "Processed"})
    display["status"] = display["status"].map(status_label)
    display.columns = ["Record ID", "Annex", "Operation", "Date", "Location", "Status", "Evidence", "Created By", "Sync Queue"]
    if df.empty:
        empty_state("No records match these filters", "Widen the date range, choose “All” for annex or status, or clear the search box.")
    else:
        st.dataframe(display, hide_index=True, width="stretch")

    if not df.empty:
        section_title("Record details", "Select a record to inspect the full entry")
        selected = st.selectbox("Select Record", df.record_id.tolist())
        row = df[df.record_id == selected].iloc[0]
        with st.container(border=True):
            ui(f'<div class="ms-detailhead"><div><div class="ms-id">{esc(row.record_id)}</div>'
               f'<div class="ms-subtle">{esc(row.annex)} · {esc(row.operation)}</div></div>{pill(row.status)}</div>')
            ui(kv_html([
                ("Date", format_record_datetime(row.record_date)),
                ("Location", nz(row.location)),
                ("Position", nz(row.position)),
                ("Quantity", f"{row.quantity} {row.unit}"),
                ("Equipment", nz(row.equipment)),
                ("Evidence", nz(row.evidence)),
                ("Created by", nz(row.created_by)),
                ("Submitted", nz(row.submitted_on)),
                ("Reviewed by", nz(row.reviewed_by)),
                ("Approved on", nz(row.approved_on)),
            ]))
            ui(f'<div class="ms-note"><div class="ms-kv-l">Remarks</div><div class="ms-kv-v">{esc(nz(row.remarks, "No remarks"))}</div></div>')

        attachments = collection_df("attachments", {"record_id": row.record_id}, [("id", 1)],
                                    {"_id": 0, "id": 1, "original_name": 1, "stored_name": 1, "mime_type": 1})
        section_title("Supporting files", "Evidence linked to this record")
        if attachments.empty:
            st.caption("No persisted files are linked to this record.")
        else:
            for _, attachment in attachments.iterrows():
                attachment_path = safe_evidence_path(attachment["stored_name"])
                if attachment_path and attachment_path.is_file():
                    st.download_button(
                        f"Download {attachment['original_name']}",
                        data=attachment_path.read_bytes(),
                        file_name=attachment["original_name"],
                        mime=attachment["mime_type"] or "application/octet-stream",
                        key=f"download_attachment_{attachment['id']}",
                    )
                else:
                    st.warning(f"The file {attachment['original_name']} is listed but missing or blocked by path validation.")

        if row.status == "Pending":
            if st.session_state.role in ["Admin", "Chief Engineer"]:
                if st.button("Approve selected record", type="primary"):
                    if review_record(row.record_id, "Approved", st.session_state.user, st.session_state.role):
                        flash("success", "Record approved and audit trail updated.")
                        st.rerun()
                    else:
                        st.warning("This record has already been reviewed. Refresh the list and try again.")
            else:
                st.caption("Approval is restricted to Admin and Chief Engineer roles.")


# ============================================================
# COMPLIANCE ALERTS
# ============================================================
elif page == "Compliance Alerts":
    page_header("Monitoring", "Operational screening alerts",
                "Prioritised review prompts, recommended actions, and a traceable resolution workflow.")
    all_alerts = collection_df("alerts", sort=[("id", -1)])
    open_alerts = all_alerts[all_alerts["resolved"].fillna(0).astype(int) == 0] if not all_alerts.empty else all_alerts
    kpi_grid([
        ("Open alerts", len(open_alerts), "Awaiting review", "warn" if len(open_alerts) else "good", "alert"),
        ("Errors", int((open_alerts["severity"] == "Error").sum()) if not open_alerts.empty else 0, "Open, highest priority", "bad", "pulse"),
        ("Warnings", int((open_alerts["severity"] == "Warning").sum()) if not open_alerts.empty else 0, "Open, needs attention", "warn", "clock"),
        ("Resolved", int((all_alerts["resolved"].fillna(0).astype(int) == 1).sum()) if not all_alerts.empty else 0, "Closed with audit entry", "good", "check"),
    ])

    with st.expander("Alert rules currently screened", expanded=False):
        st.markdown("""- **Evidence completeness:** evidence missing or still pending.
- **Position completeness:** operation has no usable position value.
- **Quantity validation:** quantity is zero, negative or unavailable.
- **Approval ageing:** pending record is at least 24 hours old.
- **Location review prompt:** discharge operation recorded at a port or anchorage, requiring manual verification.""")

    section_title("Alert register", "Filter the register, then inspect an alert to act on it")
    with st.container(border=True):
        f1, f2, f3 = st.columns([1.4, 1, 1.2])
        with f1: severity_filter = st.selectbox("Severity", ["All", "Error", "Warning", "Information"])
        with f2: state_filter = st.selectbox("State", ["Open", "Resolved", "All"], index=0)
        with f3: search_alert = st.text_input("Search alerts", placeholder="Alert ID, record ID, keyword")
    filtered = all_alerts.copy()
    if severity_filter != "All":
        filtered = filtered[filtered["severity"] == severity_filter]
    if state_filter == "Open":
        filtered = filtered[filtered["resolved"].fillna(0).astype(int) == 0]
    elif state_filter == "Resolved":
        filtered = filtered[filtered["resolved"].fillna(0).astype(int) == 1]
    if search_alert.strip():
        term = search_alert.strip().lower()
        mask = filtered.astype(str).apply(lambda col: col.str.lower().str.contains(term, na=False, regex=False)).any(axis=1)
        filtered = filtered[mask]

    if filtered.empty:
        st.success("No alerts match the selected filters.")
    else:
        view = filtered[["alert_id", "severity", "alert_type", "message", "related_record", "alert_date", "resolved"]].copy()
        view.columns = ["Alert ID", "Severity", "Rule", "Alert / Recommended action", "Related record", "Raised at", "Resolved"]
        view["Resolved"] = view["Resolved"].apply(lambda x: "✔ Resolved" if int(x or 0) else "● Open")
        view["Severity"] = view["Severity"].map(severity_label)
        st.dataframe(view, hide_index=True, width="stretch", height=min(420, 55 + len(view) * 42))
        choices = filtered["alert_id"].tolist()
        selected = st.selectbox("Inspect alert", choices, format_func=lambda x: f"{x} · {filtered.loc[filtered.alert_id == x, 'severity'].iloc[0]} — {filtered.loc[filtered.alert_id == x, 'alert_type'].iloc[0]}")
        alert = filtered[filtered["alert_id"] == selected].iloc[0]
        with st.container(border=True):
            severity = str(alert["severity"] or "Information")
            is_resolved = int(alert["resolved"] or 0) != 0
            ui(f'<div class="ms-detailhead"><div><div class="ms-id">{esc(alert["alert_type"] or "Compliance alert")}</div>'
               f'<div class="ms-subtle">{esc(alert["alert_id"])} · Related record: {esc(alert["related_record"] or "Not linked")} · Raised: {esc(alert["alert_date"] or "Unknown")}</div></div>'
               f'<div class="ms-chips">{pill(severity, SEVERITY_TONE.get(severity, "muted"))}{pill("Resolved" if is_resolved else "Open", "good" if is_resolved else "warn")}</div></div>')
            message_text = str(alert["message"] or "No message provided")
            main_message, _, action_text = message_text.partition("\nRecommended action: ")
            message_html = esc(main_message)
            if action_text:
                message_html += f'<br><b>Recommended action:</b> {esc(action_text)}'
            callout(SEVERITY_TONE.get(severity, "info"), message_html, title=severity.upper())
            if int(alert["resolved"] or 0) == 0:
                if st.session_state.role in ["Admin", "Chief Engineer"]:
                    if st.button("Mark alert as resolved", type="primary", key="resolve_selected_alert"):
                        if resolve_alert(selected, str(alert["related_record"] or ""), str(alert["alert_type"] or ""),
                                         st.session_state.user, st.session_state.role):
                            flash("success", "Alert resolution saved to the audit trail.")
                            st.rerun()
                        else:
                            st.info("This alert has already been resolved.")
                else:
                    st.info("You can inspect this alert. Resolution is restricted to the Chief Engineer and Admin.")
            else:
                st.success("This alert has been marked resolved.")
    if not all_alerts.empty:
        st.download_button("Export alert register (CSV)", all_alerts.to_csv(index=False).encode("utf-8"), "marpol_alert_register.csv", "text/csv")


# ============================================================
# APPROVAL QUEUE
# ============================================================
elif page == "Approval Queue":
    if st.session_state.role not in ["Admin", "Chief Engineer"]:
        st.error("Access denied: Approval Queue is restricted to Admin and Chief Engineer.")
        st.stop()
    page_header("Review", "Approval queue",
                "Restricted workflow: only the Chief Engineer and Admin can approve or return records.")
    callout("info", "Review the record and evidence before deciding.")

    pending = collection_df("records", {"status": "Pending"}, [("submitted_on", -1)])
    approved = collection_df("records", {"status": "Approved"}, [("approved_on", -1)])

    kpi_grid([
        ("Pending", len(pending), "Awaiting your decision", "warn" if len(pending) else "good", "clock"),
        ("Approved", len(approved), "Reviewed and approved", "good", "check"),
        ("Total records", len(pending) + len(approved), "Across both states", "teal", "file"),
    ])

    section_title("Pending approval", "Select a record below to review it")
    if pending.empty:
        st.success("Approval queue is clear.")
    else:
        st.dataframe(pending[["record_id", "annex", "operation", "created_by", "submitted_on", "evidence"]],
                     hide_index=True, width="stretch")
        selected = st.selectbox("Review Record", pending.record_id.tolist())
        row = pending[pending.record_id == selected].iloc[0]
        with st.container(border=True):
            ui(f'<div class="ms-detailhead"><div><div class="ms-id">{esc(row.record_id)}</div>'
               f'<div class="ms-subtle">{esc(row.annex)} · {esc(row.operation)} · Submitted {esc(row.submitted_on or "date unavailable")}</div></div>{pill("Pending")}</div>')
            ui(kv_html([
                ("Operation date", format_record_datetime(row.record_date)),
                ("Quantity", f"{row.quantity} {row.unit}"),
                ("Location", nz(row.location)),
                ("Position", nz(row.position)),
                ("Equipment", nz(row.equipment, "Not provided")),
                ("Evidence status", nz(row.evidence)),
            ]))
            ui(f'<div class="ms-note"><div class="ms-kv-l">Remarks</div><div class="ms-kv-v">{esc(nz(row.remarks, "No remarks"))}</div></div>')
            review_files = collection_df("attachments", {"record_id": selected}, [("id", 1)],
                                         {"_id": 0, "id": 1, "original_name": 1, "stored_name": 1, "mime_type": 1})
            if review_files.empty:
                st.caption("No persisted supporting files are linked to this record.")
            else:
                st.markdown("**Supporting files**")
                for _, attachment in review_files.iterrows():
                    attachment_path = safe_evidence_path(attachment["stored_name"])
                    if attachment_path and attachment_path.is_file():
                        st.download_button(
                            f"Download {attachment['original_name']}",
                            data=attachment_path.read_bytes(),
                            file_name=attachment["original_name"],
                            mime=attachment["mime_type"] or "application/octet-stream",
                            key=f"review_download_{attachment['id']}",
                        )
                    else:
                        st.warning(f"The file {attachment['original_name']} is listed but missing or invalid.")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("✓ Approve Record", type="primary", width="stretch"):
                if review_record(selected, "Approved", st.session_state.user, st.session_state.role):
                    flash("success", "Record approved and audit trail updated.")
                    st.rerun()
                else:
                    st.warning("This record has already been reviewed. Refresh the queue.")
        with c2:
            if st.button("Return for Evidence", width="stretch"):
                if review_record(selected, "Returned", st.session_state.user, st.session_state.role):
                    flash("warning", "Record returned for supporting evidence.")
                    st.rerun()
                else:
                    st.info("This record is no longer pending review.")


# ============================================================
# REPORTS & ANALYTICS
# ============================================================
elif page == "Reports & Analytics":
    page_header("Reporting", "Reports & analytics",
                "Interactive operational reporting generated from MongoDB.")

    df = records_for_user(st.session_state.user_id, st.session_state.user, st.session_state.role)
    section_title("Review workflow snapshot", "Counts reflect the records you can access")
    kpi_grid([
        ("Total records", len(df), "All dates", "teal", "file"),
        ("Approved", int((df.status == "Approved").sum()), "Reviewed and approved", "good", "check"),
        ("Pending", int((df.status == "Pending").sum()), "Awaiting review", "warn", "clock"),
        ("Approval completion", f"{approval_rate(df)}%", "Workflow percentage only", "info", "pulse"),
    ])
    if not df.empty:
        annex_totals = df["annex"].dropna().value_counts()
        leading_text = (
            f" Most active annex: {annex_totals.index[0]} ({int(annex_totals.iloc[0])} records)."
            if not annex_totals.empty else ""
        )
        st.info(
            f"{len(df)} records total: {int((df.status == 'Approved').sum())} approved, "
            f"{int((df.status == 'Pending').sum())} pending; {approval_rate(df)}% approved."
            f"{leading_text}"
        )

    chart_left, chart_right = st.columns(2)
    with chart_left:
        with st.container(border=True):
            card_title("Records by MARPOL annex", "Number of records per annex")
            annex_activity = df.groupby("annex").size().reset_index(name="Records").sort_values("Records", ascending=True) if not df.empty else pd.DataFrame(columns=DEFAULT_COLUMNS.get("records", []))
            if annex_activity.empty:
                st.info("No records are available for this report yet.")
            else:
                fig = px.bar(annex_activity, x="Records", y="annex", orientation="h", text="Records",
                             color_discrete_sequence=["#2dd4bf"],
                             labels={"annex": "MARPOL annex", "Records": "Records"})
                fig.update_traces(
                    textposition="outside",
                    cliponaxis=False,
                    marker_line_width=0,
                    hovertemplate="%{y}<br>%{x} records<extra></extra>",
                )
                fig.update_xaxes(title_text="Number of records", dtick=1)
                fig.update_yaxes(title_text="MARPOL annex")
                st.plotly_chart(style_figure(fig, 360), width="stretch", config={"displayModeBar": False})
    with chart_right:
        with st.container(border=True):
            card_title("Open screening prompts", "Unresolved prompts by level")
            open_alerts_df = collection_df("alerts", {"resolved": 0})
            alert_data = open_alerts_df.groupby("severity", as_index=False).size().rename(columns={"size": "count"}).sort_values("severity") if not open_alerts_df.empty else pd.DataFrame()
            if alert_data.empty:
                st.info("There are no open screening prompts.")
            else:
                fig = px.pie(alert_data, names="severity", values="count", hole=.58,
                             color="severity", color_discrete_map={"Error": "#f87171", "Warning": "#fbbf24", "Information": "#38bdf8"},
                             labels={"severity": "Prompt level", "count": "Prompts"})
                fig.update_traces(
                    textposition="inside",
                    textinfo="label+value+percent",
                    hovertemplate="%{label}: %{value} prompts (%{percent})<extra></extra>",
                )
                st.plotly_chart(style_figure(fig, 360), width="stretch", config={"displayModeBar": False})

    with st.container(border=True):
        card_title("Monthly submission volume", "Records by month and review state")
        trend_source = df.copy()
        trend_source["record_date"] = pd.to_datetime(trend_source["record_date"], errors="coerce", format="mixed")
        trend_source = trend_source.dropna(subset=["record_date"])
        if trend_source.empty:
            st.info("Dated records are needed to build the monthly trend.")
        else:
            trend_source["Month"] = trend_source["record_date"].dt.to_period("M").dt.to_timestamp()
            trend = trend_source.groupby(["Month", "status"]).size().reset_index(name="Records")
            fig = px.line(trend, x="Month", y="Records", color="status", markers=True,
                          color_discrete_map={"Approved": "#34d399", "Pending": "#e5b567"},
                          labels={"Month": "Month", "Records": "Records submitted", "status": "Review status"})
            fig.update_traces(
                hovertemplate="%{x|%b %Y}<br>%{fullData.name}: %{y} records<extra></extra>"
            )
            fig.update_xaxes(title_text="Month", type="date", tickformat="%b %Y", dtick="M1")
            fig.update_yaxes(title_text="Records submitted", dtick=1)
            st.plotly_chart(style_figure(fig, 350), width="stretch", config={"displayModeBar": False})

    section_title("Export data", "Download the underlying data as CSV")
    export_left, export_right = st.columns(2)
    csv = df.to_csv(index=False).encode("utf-8")
    with export_left:
        with st.container(border=True):
            card_title("Operation records", "Every record you can access, including status and evidence fields")
            st.download_button("Download Records CSV", csv, "marpol_records.csv", "text/csv", type="primary")
    alert_export = collection_df("alerts", sort=[("id", -1)])
    with export_right:
        with st.container(border=True):
            card_title("Alert register", "All screening prompts, open and resolved")
            st.download_button("Download Alert Register CSV", alert_export.to_csv(index=False).encode("utf-8"), "marpol_alert_register.csv", "text/csv")


# ============================================================
# AUDIT TRAIL
# ============================================================
elif page == "Audit Trail":
    if st.session_state.role not in ["Admin", "Chief Engineer"]:
        st.error("Access denied: Audit Trail is restricted to Admin and Chief Engineer.")
        st.stop()
    page_header("Traceability", "Audit trail",
                "UTC-stamped traceability: who created, submitted, reviewed and approved each record.")

    audit = collection_df("audit", sort=[("id", -1)])
    if audit.empty:
        st.info("Recorded actions will appear here.")
    else:
        kpi_grid([
            ("Recorded events", len(audit), "Everything logged so far", "teal", "pulse"),
            ("People involved", int(audit["user_name"].nunique()), "Distinct users in the log", "info", "users"),
            ("Latest event", nz(audit["event_time"].iloc[0]), f"{nz(audit['action'].iloc[0])} · {nz(audit['user_name'].iloc[0])}", "muted", "clock"),
        ])
        section_title("All events", "Newest first")
        st.dataframe(audit[["event_time", "user_name", "role", "action", "record_id", "details"]],
                     hide_index=True, width="stretch")
        record_ids = sorted([value for value in audit["record_id"].dropna().unique().tolist() if str(value).strip()])
        if record_ids:
            section_title("Activity for one record", "Follow a single record through its lifecycle")
            selected_trace_id = st.selectbox("Record ID", record_ids)
            trace = audit[audit["record_id"] == selected_trace_id][["event_time", "user_name", "role", "action", "details"]]
            st.dataframe(trace, hide_index=True, width="stretch")


# ============================================================
# MARPOL LIBRARY
# ============================================================
elif page == "MARPOL Library":
    page_header("Reference", "MARPOL library",
                "A searchable, source-linked reference index stored in MongoDB.")
    callout("info", "Verify requirements against current IMO publications and approved vessel procedures.")

    with st.container(border=True):
        filter_cols = st.columns([1.15, 1.35, 2.25])
        with filter_cols[0]:
            content_filter = st.selectbox("Library section", ["All library items", "Regulations", "Official sources", "Company guidance"])
        with filter_cols[1]:
            annex_filter = st.selectbox("Annex", ["All Annexes", "General"] + list(ANNEXES.keys()))
        with filter_cols[2]:
            library_search = st.text_input("Search the library", placeholder="Search annex, topic, reference, or source")

    all_library = collection_df("library_items")
    if not all_library.empty:
        all_library = all_library.assign(
            _sort=lambda frame: frame["content_type"].map({"Regulations": 0, "Official source": 1}).fillna(2)
        ).sort_values(["_sort", "annex", "title"]).drop(columns=["_sort"])

    if content_filter == "Regulations":
        all_library = all_library[all_library["content_type"] == "Regulations"]
    elif content_filter == "Official sources":
        all_library = all_library[all_library["content_type"] == "Official source"]
    elif content_filter == "Company guidance":
        all_library = all_library[all_library["content_type"] == "Company guidance"]
    if annex_filter != "All Annexes":
        all_library = all_library[all_library["annex"] == annex_filter]
    if library_search.strip() and not all_library.empty:
        search = library_search.strip().lower()
        searchable = all_library[["annex", "content_type", "reference", "title", "summary", "source_name"]].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
        all_library = all_library[searchable.str.contains(search, regex=False)]

    ui(f'<div class="ms-toolbar"><span class="ms-count">{len(all_library)} <span>matching items</span></span>'
       '<span class="ms-subtle" style="margin:0">Choose <b>Regulations</b> to browse the six indexed MARPOL Annex overviews.</span></div>')

    if all_library.empty:
        empty_state("No library items match those filters", "Try another Annex or search term.")
    else:
        type_tone = {"Regulations": "teal", "Official source": "info", "Company guidance": "warn"}
        for start_index in range(0, len(all_library), 2):
            card_cols = st.columns(2, gap="large")
            for offset, col in enumerate(card_cols):
                index = start_index + offset
                if index >= len(all_library):
                    continue
                item = all_library.iloc[index]
                with col:
                    with st.container(border=True):
                        ui(f'<div class="ms-libtop">{pill(item["content_type"], type_tone.get(str(item["content_type"]), "muted"))}'
                           f'{pill(item["annex"], "muted", plain=True)}</div>'
                           f'<div class="ms-libtitle">{esc(item["title"])}</div>'
                           f'<div class="ms-libsum">{esc(item["summary"])}</div>'
                           f'<div class="ms-libchips"><span class="ms-srcchip">{esc(item["reference"] or "Reference")}</span>'
                           f'<span class="ms-srcchip">{esc(item["source_name"] or "Source not specified")}</span></div>')
                        if item["source_url"]:
                            st.link_button("Open official source ↗", str(item["source_url"]))
                        st.caption(f"Source checked {item['source_checked'] or 'date not supplied'} · {item['source_version'] or 'Version not supplied'}")

    if st.session_state.role == "Admin":
        section_title("Administration", "Admins can extend the shared library")
        with st.expander("Add company guidance to the shared library"):
            with st.form("add_library_guidance"):
                guidance_cols = st.columns(2)
                with guidance_cols[0]:
                    guidance_title = st.text_input("Title")
                    guidance_annex = st.selectbox("Related Annex", ["General"] + list(ANNEXES.keys()))
                    guidance_reference = st.text_input("Reference / document number", placeholder="e.g. SMS-ENV-014")
                with guidance_cols[1]:
                    guidance_source = st.text_input("Source URL (optional)", placeholder="https://...")
                    guidance_summary = st.text_area("Guidance summary", height=110)
                guidance_submitted = st.form_submit_button("Save guidance", type="primary")
            if guidance_submitted:
                if not guidance_title.strip() or not guidance_summary.strip():
                    st.error("Enter both a title and a guidance summary.")
                elif guidance_source.strip() and not guidance_source.strip().lower().startswith("https://"):
                    st.error("Source links must use HTTPS.")
                else:
                    database = db()
                    database.library_items.insert_one({
                        "id": next_id(database, "library_items"),
                        "slug": f"company-{uuid.uuid4().hex}", "annex": guidance_annex,
                        "content_type": "Company guidance", "reference": guidance_reference.strip(),
                        "title": guidance_title.strip(), "summary": guidance_summary.strip(),
                        "source_name": "Company guidance", "source_url": guidance_source.strip() or None,
                        "source_version": "Company supplied", "source_checked": date.today().strftime("%d %b %Y"),
                        "created_by": st.session_state.user,
                    })
                    write_audit_row(database, "Added Library Guidance", "", guidance_title.strip(),
                                    st.session_state.user, st.session_state.role)
                    flash("success", "Guidance saved in the MongoDB library collection.")
                    st.rerun()


# ============================================================
# SYSTEM SETTINGS
# ============================================================
elif page == "System Settings":
    if st.session_state.role != "Admin":
        st.error("Access denied: System Settings is restricted to Admin.")
        st.stop()
    page_header("Administration", "System settings",
                "Manage vessel identity, crew access, password rotation, and database diagnostics.")

    tab_vessel, tab_users, tab_diag = st.tabs(["🚢 Vessel Profile", "👥 Crew & Access", "🛡️ Storage & Diagnostics"])

    with tab_vessel:
        with st.form("vessel_settings_form"):
            s1, s2 = st.columns(2)
            with s1:
                v_name = st.text_input("Vessel Name", value=VESSEL["name"])
                v_imo = st.text_input("IMO Number", value=VESSEL["imo"])
                v_flag = st.text_input("Flag State", value=VESSEL["flag"])
                v_type = st.text_input("Vessel Type", value=VESSEL["type"])
            with s2:
                v_gt = st.text_input("Gross Tonnage", value=VESSEL["gt"])
                v_voyage = st.text_input("Active Voyage", value=VESSEL["voyage"])
                v_route = st.text_input("Current Route", value=VESSEL["route"])
            save_vessel = st.form_submit_button("Save vessel profile", type="primary")

        if save_vessel:
            if not v_name.strip() or not v_imo.strip():
                st.error("Vessel Name and IMO Number are required.")
            else:
                updated_profile = {
                    "name": v_name.strip(), "imo": v_imo.strip(), "flag": v_flag.strip(),
                    "type": v_type.strip(), "gt": v_gt.strip(), "voyage": v_voyage.strip(),
                    "route": v_route.strip(),
                }
                save_vessel_profile(updated_profile, st.session_state.user, st.session_state.role)
                VESSEL.update(updated_profile)
                flash("success", "Vessel profile updated and recorded in the audit trail.")
                st.rerun()

    with tab_users:
        users_df = collection_df("users", projection={"_id": 0, "username": 1, "user_id": 1, "name": 1, "role": 1, "enabled": 1})
        st.dataframe(users_df, hide_index=True, width="stretch")

        col_add, col_edit = st.columns(2, gap="large")
        with col_add:
            section_title("Add new crew account", "Create a new role-scoped login")
            with st.form("create_user_form"):
                new_uname = st.text_input("Username", placeholder="e.g. second_eng")
                new_fname = st.text_input("Full Name", placeholder="e.g. Second Engineer")
                new_role = st.selectbox("Role", list(ROLE_PAGES.keys()), index=2)
                new_pass = st.text_input("Initial Password", type="password", placeholder="Minimum 8 characters")
                create_btn = st.form_submit_button("Create account", type="primary", width="stretch")
            if create_btn:
                try:
                    uid = create_crew_account(new_uname, new_fname, new_role, new_pass, st.session_state.user, st.session_state.role)
                    flash("success", f"Created account '{new_uname}' ({uid}).")
                    st.rerun()
                except (ValueError, PermissionError) as err:
                    st.error(str(err))

        with col_edit:
            section_title("Rotate password / status", "Update an existing account")
            if not users_df.empty:
                with st.form("user_credential_form"):
                    target_user = st.selectbox("Select account", users_df["username"].tolist())
                    new_pwd = st.text_input("New password (optional)", type="password", placeholder="Min 8 chars to rotate")
                    current_enabled = bool(users_df.loc[users_df["username"] == target_user, "enabled"].iloc[0])
                    acct_enabled = st.checkbox("Account enabled", value=current_enabled)
                    save_user_btn = st.form_submit_button("Update account", width="stretch")
                if save_user_btn:
                    try:
                        if update_user_credentials(target_user, new_pwd, acct_enabled, st.session_state.user, st.session_state.role):
                            flash("success", f"Account '{target_user}' updated.")
                            st.rerun()
                    except (ValueError, PermissionError) as err:
                        st.error(str(err))

    with tab_diag:
        queued_count = db().records.count_documents({"synced": 0})
        tls_status = "Enabled" if (MONGO_TLS or MONGO_URI.startswith("mongodb+srv://")) else "Disabled (local)"
        ui(f'<div class="ms-sysgrid">'
           f'<div class="ms-sys"><div class="ms-sys-l">Environment Mode</div><div class="ms-sys-v">{esc(APP_ENV.upper())}</div></div>'
           f'<div class="ms-sys"><div class="ms-sys-l">MongoDB Database / TLS</div><div class="ms-sys-v">{esc(MONGO_DATABASE)} · {esc(tls_status)}</div></div>'
           f'<div class="ms-sys"><div class="ms-sys-l">Evidence Store</div><div class="ms-sys-v">{esc(str(EVIDENCE_DIR))}</div></div>'
           f'<div class="ms-sys"><div class="ms-sys-l">Queued Records</div><div class="ms-sys-v">{queued_count} pending</div></div>'
           f'</div>')
        st.write("")
        if st.button("Process local sync queue", disabled=(queued_count == 0)):
            processed = process_demo_queue(st.session_state.user, st.session_state.role)
            flash("success", f"Marked {processed} queued record(s) as processed.")
            st.rerun()

elif page == "Database Explorer":
    if st.session_state.role != "Admin":
        st.error("Access denied: Database Explorer is restricted to Admin.")
        st.stop()

    page_header(
        "Administration",
        "Database explorer",
        "Browse application collections in read-only mode.",
    )
    database = db()
    collection_names = [
        name for name in DATABASE_EXPLORER_COLLECTIONS
        if name in database.list_collection_names()
    ]
    collection_counts = {
        name: database[name].count_documents({})
        for name in collection_names
    }

    summary_columns = st.columns(2)
    summary_columns[0].metric("Collections", len(collection_names))
    summary_columns[1].metric("Documents", sum(collection_counts.values()))

    if not collection_names:
        st.info("No application collections are available.")
    else:
        selected_collection = st.selectbox("Collection", collection_names)
        total_documents = collection_counts[selected_collection]
        documents, table_rows = database_document_rows(database, selected_collection)
        st.metric(f"{selected_collection} documents", total_documents)
        document_label = "documents" if selected_collection == "counters" else "newest documents"
        st.caption(
            f"Showing up to {len(documents)} {document_label}. "
            "Credential fields are redacted; login-attempt records are not shown."
        )
        if table_rows.empty:
            st.info("This collection is empty.")
        else:
            st.dataframe(
                table_rows,
                hide_index=True,
                width="stretch",
                height=min(520, 80 + len(table_rows) * 38),
            )
            with st.expander("Inspect sanitized document JSON"):
                st.code(json.dumps(documents, indent=2, default=str), language="json")


# -----------------------------
# Footer
# -----------------------------
ui(f'<div class="ms-footer"><span><b>MARPOL-SAFE</b> Shipboard Operations</span><span>•</span>'
   f'<span>{esc(VESSEL["name"])} (IMO {esc(VESSEL["imo"])})</span><span>•</span>'
   f'<span>MongoDB Backend ({esc(APP_ENV.upper())})</span></div>')