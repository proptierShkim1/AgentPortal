import streamlit as st
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent
sys.path.append(str(ROOT))
load_dotenv(ROOT / ".env")

st.set_page_config(
    page_title="AgentPortal · Proptier",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
[data-testid="stSidebarNavLink"] {
    font-size: 16px !important;
    padding-top: 0.6rem !important;
    padding-bottom: 0.6rem !important;
}
[data-testid="stSidebarNav"]::before {
    content: "🏢  AgentPortal";
    display: block;
    font-size: 20px;
    font-weight: 700;
    padding: 1.2rem 1rem 1rem 1rem;
    border-bottom: 1px solid rgba(255,255,255,0.15);
    margin-bottom: 0.4rem;
}
</style>
""", unsafe_allow_html=True)


def _get_client_ip() -> str:
    try:
        from streamlit.runtime.context import _get_client_context
        ctx = _get_client_context()
        return (ctx.remote_ip or "") if ctx else ""
    except Exception:
        pass
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        from streamlit.runtime import get_instance
        ctx = get_script_run_ctx()
        session = get_instance().get_session_info(ctx.session_id)
        return session.client.request.remote_ip or ""
    except Exception:
        return ""


from access_control import is_admin, can_view_history
from access_log import log_visit

_client_ip = _get_client_ip()
st.session_state["_client_ip"] = _client_ip

_pages = [st.Page("pages/포털.py", title="포털", icon="🏢")]
if is_admin(_client_ip):
    _pages.append(st.Page("pages/설정.py", title="설정", icon="⚙️"))
    _pages.append(st.Page("pages/로그.py", title="로그", icon="🧾"))
if can_view_history(_client_ip):
    _pages.append(st.Page("pages/버전이력.py", title="버전 이력", icon="📜"))

pg = st.navigation(_pages)

if st.session_state.get("_last_logged_page") != pg.title:
    st.session_state["_last_logged_page"] = pg.title
    log_visit(_client_ip, pg.title)

pg.run()
