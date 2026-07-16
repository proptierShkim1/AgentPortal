import streamlit as st
import socket

AGENTS = [
    {
        "name": "LexAgent",
        "nickname": "렉스",
        "desc": "개인정보 법령 RAG 분석",
        "detail": "법령 데이터 기반 질의응답 및 조항 분석",
        "host": "192.168.10.169",
        "port": 9001,
        "path": r"C:\Users\USER\Desktop\Project Agent\LexAgent",
        "icon": "⚖️",
        "color": "#4F8EF7",
    },
    {
        "name": "PolicyAgent",
        "nickname": "폴리",
        "desc": "개인정보 처리방침 분석",
        "detail": "처리방침 문서 검토 및 체크리스트 자동화",
        "host": "192.168.10.169",
        "port": 8502,
        "path": r"C:\Users\USER\Desktop\Project Agent\PolicyAgent",
        "icon": "🔐",
        "color": "#43C59E",
    },
    {
        "name": "GosiAgent",
        "nickname": "고시",
        "desc": "고시 수집 및 알림",
        "detail": "행정 고시 자동 수집 및 실시간 알림",
        "host": "192.168.10.169",
        "port": 9003,
        "path": r"C:\Users\USER\Desktop\Project Agent\GosiAgent",
        "icon": "🏛️",
        "color": "#F7934F",
    },
    {
        "name": "ModelTLab",
        "nickname": "모델랩",
        "desc": "AI 모델 파인튜닝·채팅 테스트",
        "detail": "파인튜닝 모델 실험 및 채팅 인터페이스",
        "host": "192.168.14.222",
        "port": 3010,
        "path": r"C:\Users\USER\Desktop\Project Agent\ModelTLab",
        "icon": "🧫",
        "color": "#D4956A",
        "visible": False,
    },
    {
        "name": "gov_kr",
        "nickname": "고브",
        "desc": "건축물대장 조회",
        "detail": "건축물대장 자동 조회 및 정보 확인",
        "host": "192.168.14.222",
        "port": 1001,
        "path": r"C:\Users\USER\Desktop\Project Agent\gov_kr",
        "icon": "🏢",
        "color": "#6C63FF",
        "visible": False,
    },
    {
        "name": "SonarGuard",
        "nickname": "소나",
        "desc": "코드 취약점 스캐너",
        "detail": "정적 분석 기반 코드 보안 취약점 스캐닝",
        "host": "192.168.14.222",
        "port": 2001,
        "path": r"C:\Users\USER\Desktop\Project Agent\local_sonar_test",
        "icon": "🛡️",
        "color": "#E05C4A",
        "visible": False,
    },
    {
        "name": "AIpartner(세무)",
        "nickname": "삼일PWC",
        "desc": "세무 관련 법안 분석",
        "detail": "세무법안 관련 수집 및 분석",
        "host": "192.168.14.222",
        "port": 9101,
        "path": r"C:\Users\USER\Desktop\Project Agent\pwc_poc",
        "icon": "🤝",
        "color": "#8B5CF6",
        "visible": False,
    },
]


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
        max-width: 1100px;
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
    }
    .agent-card:hover {
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.13);
        transform: translateY(-4px);
    }
    .card-icon    { font-size: 2.8rem; margin-bottom: 0.75rem; }
    .card-name    { font-size: 1.35rem; font-weight: 700; color: #1a1a2e; }
    .card-nick    { font-size: 0.85rem; color: #7a85a0; margin-bottom: 0.65rem; }
    .card-desc    { font-size: 0.92rem; color: #2e3a50; line-height: 1.6; margin-bottom: 0.4rem; font-weight: 500; }
    .card-detail  { font-size: 0.8rem; color: #6b7591; margin-bottom: 1.25rem; }

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
VISIBLE_AGENTS = [a for a in AGENTS if a.get("visible", True)]

for row_start in range(0, len(VISIBLE_AGENTS), 3):
    row_agents = VISIBLE_AGENTS[row_start:row_start + 3]
    cols = st.columns(3, gap="large")

    for j, agent in enumerate(row_agents):
        i = row_start + j
        running = is_running(agent["host"], agent["port"])
        url = f"http://{agent['host']}:{agent['port']}"
        badge = (
            '<span class="badge-on">● 실행 중</span>'
            if running
            else '<span class="badge-off">● 중지됨</span>'
        )

        with cols[j]:
            st.markdown(
                f"""
                <div class="agent-card" style="border-top-color:{agent['color']};">
                    <div class="card-icon">{agent['icon']}</div>
                    <div class="card-name">{agent['name']}</div>
                    <div class="card-nick">{agent['nickname']}</div>
                    <div class="card-desc">{agent['desc']}</div>
                    <div class="card-detail">{agent['detail']}</div>
                    {badge}
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

            b1, b2 = st.columns(2)
            with b1:
                st.button("▶  실행", key=f"launch_{i}", use_container_width=True, disabled=True)
            with b2:
                if running:
                    st.link_button("→  이동", url, use_container_width=True)
                else:
                    st.button("→  이동", key=f"open_{i}", use_container_width=True, disabled=True)

    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown(
    '<div class="portal-footer">Proptier · Agent Portal · 2026</div>',
    unsafe_allow_html=True,
)
