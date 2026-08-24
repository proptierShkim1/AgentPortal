import streamlit as st
import socket

from agents_data import AGENTS
import os
from visibility_config import load_visibility, visible_agents, sort_by_order

IS_DEPLOYED = os.environ.get("PORTAL_ENV") == "deploy"
LOCAL_HOST = "192.168.14.222"
DEPLOY_HOST = "192.168.10.169"
AGENT_HOST = DEPLOY_HOST if IS_DEPLOYED else LOCAL_HOST


def is_running(host, port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False



st.markdown("""
<style>
    #MainMenu, footer { visibility: hidden; }

    .block-container {
        padding-top: 2.5rem;
        padding-bottom: 3rem;
        max-width: 1650px;
    }

    .portal-header {
        text-align: center;
        padding: 1rem 0 1.5rem;
        position: sticky;
        top: 0;
        z-index: 999;
        background: #F0F2F8;
    }
    .brand-tag {
        display: inline-block;
        background: #4F8EF7;
        color: #ffffff;
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 2.5px;
        padding: 4px 16px;
        border-radius: 20px;
        margin-bottom: 1.2rem;
    }
    .portal-title {
        font-size: 2.6rem;
        font-weight: 900;
        background: linear-gradient(90deg, #1a1a2e 0%, #4F8EF7 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-bottom: 0.5rem;
        letter-spacing: -0.5px;
    }
    .portal-subtitle {
        font-size: 1rem;
        color: #555e72;
        font-weight: 500;
    }

    .agent-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, 300px);
        justify-content: center;
        gap: 28px;
    }

    .agent-card {
        background: #ffffff;
        border-radius: 20px;
        padding: 2rem 1.5rem 1.75rem;
        box-shadow: 0 2px 18px rgba(0, 0, 0, 0.07);
        text-align: center;
        border-top-width: 5px;
        border-top-style: solid;
        transition: box-shadow 0.2s ease, transform 0.2s ease;
        min-height: 250px;
        display: flex;
        flex-direction: column;
    }
    .agent-card:hover {
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.13);
        transform: translateY(-4px);
    }
    .card-icon    { font-size: 2.8rem; margin-bottom: 0.75rem; }
    .card-name    { font-size: 1.35rem; font-weight: 700; color: #1a1a2e; }
    .card-nick    { font-size: 0.85rem; color: #7a85a0; margin-bottom: 0.65rem; }
    .card-desc    { font-size: 0.92rem; color: #2e3a50; line-height: 1.6; margin-bottom: 0.4rem; font-weight: 500; }
    .card-detail  { font-size: 0.8rem; color: #6b7591; margin-bottom: 1.25rem; flex-grow: 1; }

    .btn-row { display: flex; gap: 12px; margin-top: auto; padding-top: 12px; }
    .btn-static, .btn-link {
        flex: 1;
        padding: 8px 0;
        border-radius: 8px;
        font-size: 0.85rem;
        font-weight: 600;
        text-align: center;
    }
    .btn-static {
        background: #f0f1f5;
        color: #aab1c0;
        cursor: not-allowed;
    }
    .btn-link, .btn-link:hover, .btn-link:visited {
        background: #e4e7ef;
        color: #3d4560;
        text-decoration: none !important;
    }
    .btn-link:hover { background: #d6dae8; }

    .badge-on {
        display: inline-block;
        background: #e6f9f0;
        color: #1db954;
        font-size: 0.78rem;
        font-weight: 600;
        padding: 3px 14px;
        border-radius: 20px;
    }
    .badge-off {
        display: inline-block;
        background: #fef0ef;
        color: #e05c4a;
        font-size: 0.78rem;
        font-weight: 600;
        padding: 3px 14px;
        border-radius: 20px;
    }

    .portal-footer {
        text-align: center;
        color: #c0c8d4;
        font-size: 0.8rem;
        padding-top: 2.5rem;
    }
</style>
""", unsafe_allow_html=True)

# ── Header ──────────────────────────────────────────────────────────────────
st.markdown("""
<div class="portal-header">
    <div class="brand-tag">PROPTIER</div>
    <div class="portal-title">Agent Portal</div>
    <div class="portal-subtitle">에이전트를 선택하여 이동하세요</div>
</div>
""", unsafe_allow_html=True)

# ── Refresh ──────────────────────────────────────────────────────────────────
_, col_btn = st.columns([6, 1])
with col_btn:
    if st.button("↺  새로고침", use_container_width=True):
        st.rerun()

st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

# ── Cards ────────────────────────────────────────────────────────────────────
_visibility = load_visibility()
VISIBLE_AGENTS = sort_by_order(visible_agents(AGENTS, _visibility, IS_DEPLOYED), _visibility)

_card_html = []
for agent in VISIBLE_AGENTS:
    running = is_running(AGENT_HOST, agent["port"])
    url = f"http://{AGENT_HOST}:{agent['port']}"
    badge = (
        '<span class="badge-on">● 실행 중</span>'
        if running
        else '<span class="badge-off">● 중지됨</span>'
    )
    move_btn = (
        f'<a class="btn-link" href="{url}" target="_blank">→  이동</a>'
        if running
        else '<span class="btn-static">→  이동</span>'
    )

    _card_html.append(
        f'<div class="agent-card" style="border-top-color:{agent["color"]};">'
        f'<div class="card-icon">{agent["icon"]}</div>'
        f'<div class="card-name">{agent["name"]}</div>'
        f'<div class="card-nick">{agent["nickname"]}</div>'
        f'<div class="card-desc">{agent["desc"]}</div>'
        f'<div class="card-detail">{agent["detail"]}</div>'
        f'{badge}'
        f'<div class="btn-row">'
        f'<span class="btn-static">▶  실행</span>'
        f'{move_btn}'
        f'</div>'
        f'</div>'
    )

st.markdown(f'<div class="agent-grid">{"".join(_card_html)}</div>', unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(
    '<div class="portal-footer">Proptier · Agent Portal · 2026</div>',
    unsafe_allow_html=True,
)
