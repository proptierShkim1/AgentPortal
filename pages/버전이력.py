import streamlit as st
import sys
import subprocess
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.append(str(ROOT))
load_dotenv(ROOT / ".env")

from access_control import can_view_history

if not can_view_history(st.session_state.get("_client_ip", "") or ""):
    st.error("🔒 이력 열람 권한이 있는 IP에서만 접근할 수 있습니다.")
    st.stop()

st.title("📜 버전 이력")
st.caption("이 앱의 코드가 시간순으로 어떻게 바뀌어왔는지 보여줍니다 (git 커밋 이력). 이 PC 로컬에만 저장돼 있습니다.")
st.divider()

GS, RS = "\x1f", "\x1e"


def _run_git(args: list) -> str:
    try:
        result = subprocess.run(
            ["git"] + args, cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""


@st.cache_data(ttl=30)
def _load_commits() -> list:
    out = _run_git([
        "log", "--date=format:%Y-%m-%d %H:%M",
        f"--pretty=format:%H{GS}%ad{GS}%an{GS}%s{RS}",
    ])
    commits = []
    for chunk in out.split(RS):
        if not chunk.strip():
            continue
        parts = chunk.split(GS)
        if len(parts) == 4:
            commits.append({"hash": parts[0], "date": parts[1], "author": parts[2], "subject": parts[3]})
    return commits


@st.dialog("커밋 상세", width="large")
def _show_commit_detail(commit_hash: str, subject: str):
    st.subheader(subject)
    detail = _run_git([
        "show", "--stat", "--date=format:%Y-%m-%d %H:%M:%S",
        "--format=커밋: %H%n작성자: %an%n일시: %ad%n%n%B", commit_hash,
    ])
    st.code(detail or "상세 정보를 불러올 수 없습니다.", language=None)


commits = _load_commits()

if not commits:
    st.info("커밋 이력을 불러올 수 없습니다. (git 저장소가 아니거나 접근 권한 문제)")
else:
    all_authors = sorted(set(c["author"] for c in commits if c["author"]))
    author_options = ["전체"] + all_authors

    fc1, fc2, fc3 = st.columns([2, 3, 1.3])
    with fc1:
        sel_author = st.selectbox("작성자 필터", author_options, key="verhist_author")
    with fc2:
        search = st.text_input("검색 (커밋 메시지)", placeholder="검색어 입력...", key="verhist_q")
    with fc3:
        page_size = st.selectbox("페이지당 개수", [10, 20, 50, 100], index=0, key="verhist_page_size")

    filter_sig = (sel_author, search, page_size)
    if st.session_state.get("verhist_filter_sig") != filter_sig:
        st.session_state["verhist_filter_sig"] = filter_sig
        st.session_state["verhist_page"] = 1

    filtered = commits
    if sel_author != "전체":
        filtered = [c for c in filtered if c["author"] == sel_author]
    if search:
        filtered = [c for c in filtered if search.lower() in c["subject"].lower()]

    total_all = len(commits)
    total = len(filtered)
    st.caption(f"전체 {total_all}개 커밋 | 검색 결과 **{total}건**")

    if "verhist_page" not in st.session_state:
        st.session_state["verhist_page"] = 1
    total_pages = max(1, (total + page_size - 1) // page_size)
    st.session_state["verhist_page"] = min(st.session_state["verhist_page"], total_pages)
    page = st.session_state["verhist_page"]
    start = (page - 1) * page_size
    end = min(start + page_size, total)

    st.divider()

    h = st.columns([0.7, 1.6, 1.2, 5.3, 1.0])
    for col, label in zip(h, ["번호", "일시", "작성자", "제목", ""]):
        col.markdown(f"**{label}**")

    for i, c in enumerate(filtered[start:end]):
        rank = total - start - i
        row = st.columns([0.7, 1.6, 1.2, 5.3, 1.0])
        row[0].write(rank)
        row[1].write(c["date"])
        row[2].write(c["author"])
        row[3].write(c["subject"])
        if row[4].button("보기", key=f"vh_view_{c['hash']}", use_container_width=True):
            _show_commit_detail(c["hash"], c["subject"])

    st.divider()
    pc1, pc2, pc3, pc4, pc5 = st.columns([1, 1, 2, 1, 1])
    if pc1.button("◀◀ 처음", disabled=page <= 1):
        st.session_state["verhist_page"] = 1
        st.rerun()
    if pc2.button("◀ 이전", disabled=page <= 1):
        st.session_state["verhist_page"] -= 1
        st.rerun()
    pc3.markdown(f"<div style='text-align:center;padding-top:6px'>{page} / {total_pages} 페이지</div>", unsafe_allow_html=True)
    if pc4.button("다음 ▶", disabled=page >= total_pages):
        st.session_state["verhist_page"] += 1
        st.rerun()
    if pc5.button("끝 ▶▶", disabled=page >= total_pages):
        st.session_state["verhist_page"] = total_pages
        st.rerun()
