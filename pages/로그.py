import streamlit as st
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.append(str(ROOT))
load_dotenv(ROOT / ".env")

from access_control import is_admin
from access_log import load_logs

if not is_admin(st.session_state.get("_client_ip", "") or ""):
    st.error("🔒 관리자 권한이 있는 IP에서만 접근할 수 있습니다.")
    st.stop()

st.title("🧾 접속 로그")
st.caption("포털 접속 IP와 이동한 화면(행위)을 기록합니다. 이 PC 로컬에만 저장돼 있습니다.")
st.divider()

logs = load_logs()

if not logs:
    st.info("기록된 접속 로그가 없습니다.")
else:
    logs = list(reversed(logs))
    all_pages = sorted(set(l["page"] for l in logs if l.get("page")))
    page_options = ["전체"] + all_pages

    fc1, fc2, fc3 = st.columns([1.4, 3, 1.3])
    with fc1:
        sel_page = st.selectbox("행위 필터", page_options, key="log_page_filter")
    with fc2:
        search = st.text_input("검색 (IP / 이름)", placeholder="검색어 입력...", key="log_q")
    with fc3:
        page_size = st.selectbox("페이지당 개수", [20, 50, 100, 200], index=0, key="log_page_size")

    filter_sig = (sel_page, search, page_size)
    if st.session_state.get("log_filter_sig") != filter_sig:
        st.session_state["log_filter_sig"] = filter_sig
        st.session_state["log_page"] = 1

    filtered = logs
    if sel_page != "전체":
        filtered = [l for l in filtered if l.get("page") == sel_page]
    if search:
        q = search.lower()
        filtered = [
            l for l in filtered
            if q in l.get("ip", "").lower() or q in l.get("name", "").lower()
        ]

    total_all = len(logs)
    total = len(filtered)
    st.caption(f"전체 {total_all}건 | 검색 결과 **{total}건**")

    if "log_page" not in st.session_state:
        st.session_state["log_page"] = 1
    total_pages = max(1, (total + page_size - 1) // page_size)
    st.session_state["log_page"] = min(st.session_state["log_page"], total_pages)
    page = st.session_state["log_page"]
    start = (page - 1) * page_size
    end = min(start + page_size, total)

    st.divider()

    h = st.columns([0.7, 1.6, 1.6, 1.4, 2.0])
    for col, label in zip(h, ["번호", "일시", "IP", "이름", "행위"]):
        col.markdown(f"**{label}**")

    for i, l in enumerate(filtered[start:end]):
        rank = total - start - i
        row = st.columns([0.7, 1.6, 1.6, 1.4, 2.0])
        row[0].write(rank)
        row[1].write(l.get("ts", ""))
        row[2].write(l.get("ip", ""))
        row[3].write(l.get("name") or "-")
        row[4].write(l.get("page", ""))

    st.divider()
    pc1, pc2, pc3, pc4, pc5 = st.columns([1, 1, 2, 1, 1])
    if pc1.button("◀◀ 처음", disabled=page <= 1):
        st.session_state["log_page"] = 1
        st.rerun()
    if pc2.button("◀ 이전", disabled=page <= 1):
        st.session_state["log_page"] -= 1
        st.rerun()
    pc3.markdown(f"<div style='text-align:center;padding-top:6px'>{page} / {total_pages} 페이지</div>", unsafe_allow_html=True)
    if pc4.button("다음 ▶", disabled=page >= total_pages):
        st.session_state["log_page"] += 1
        st.rerun()
    if pc5.button("끝 ▶▶", disabled=page >= total_pages):
        st.session_state["log_page"] = total_pages
        st.rerun()
