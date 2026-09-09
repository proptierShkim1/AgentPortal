import streamlit as st
import os
from pathlib import Path
from dotenv import load_dotenv

from agents_data import AGENTS
from visibility_config import load_visibility, save_visibility, sort_by_order
from access_control import is_admin

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

if not is_admin(st.session_state.get("_client_ip", "") or ""):
    st.error("🔒 관리자 권한이 있는 IP에서만 접근할 수 있습니다.")
    st.stop()

st.title("⚙️ 설정")

# ── 카드 노출 설정 ──────────────────────────────────────────
st.subheader("🖥️ 카드 노출 설정")
st.caption("로컬 화면과 배포(가상화 서버) 화면에 각각 독립적으로 노출 여부를 설정하고, 포털 카드 순서를 지정합니다.")

_visibility = load_visibility()
_new_visibility = {}

for _i, _agent in enumerate(AGENTS):
    _name = _agent["name"]
    _current = _visibility.get(_name, {"visible_local": True, "visible_deploy": True, "order": _i})
    col_label, col_order, col_local, col_deploy = st.columns([2, 1, 1, 1])
    with col_label:
        st.markdown(f"**{_agent['icon']} {_name}** ({_agent['nickname']})")
    with col_order:
        _order = st.number_input("순서", min_value=0, step=1, value=_current.get("order", _i), key=f"vis_order_{_name}")
    with col_local:
        _vl = st.checkbox("로컬 노출", value=_current.get("visible_local", True), key=f"vis_local_{_name}")
    with col_deploy:
        _vd = st.checkbox("배포 노출", value=_current.get("visible_deploy", True), key=f"vis_deploy_{_name}")
    _new_visibility[_name] = {"visible_local": _vl, "visible_deploy": _vd, "order": _order}

if _new_visibility != _visibility:
    save_visibility(_new_visibility)

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ── 서버 배포 ──────────────────────────────────────────────
st.subheader("🚀 서버 배포")

_DEPLOY_HOST     = os.getenv("DEPLOY_HOST", "")
_DEPLOY_SSH_PORT = int(os.getenv("DEPLOY_SSH_PORT", "9922"))
_DEPLOY_USER     = os.getenv("DEPLOY_USER", "")
_DEPLOY_PASS     = os.getenv("DEPLOY_PASS", "")
_DEPLOY_REMOTE   = os.getenv("DEPLOY_REMOTE_PATH", f"/home/{os.getenv('DEPLOY_USER','')}/AgentPortal")
_DEPLOY_APP_PORT = int(os.getenv("DEPLOY_APP_PORT", "9000"))

_UPLOAD_SUFFIXES    = {".py", ".toml", ".txt", ".md", ".sh"}
_UPLOAD_DIRS        = {".streamlit", "scripts", "pages"}
_UPLOAD_ROOT_EXTRAS = {".env"}
_SFTP_SKIP          = {"__pycache__", ".git", "lex-env", "venv"}


def _ssh_connect():
    import paramiko
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(_DEPLOY_HOST, port=_DEPLOY_SSH_PORT,
                username=_DEPLOY_USER, password=_DEPLOY_PASS, timeout=15)
    return ssh


def _ssh_run(ssh, cmd: str, timeout: int = 120):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    return stdout.read().decode(), stderr.read().decode(), rc


def _sftp_mkdir_p(sftp, remote: str):
    parts = remote.strip("/").split("/")
    cur = ""
    for p in parts:
        cur += "/" + p
        try:
            sftp.stat(cur)
        except OSError:
            try:
                sftp.mkdir(cur)
            except OSError:
                pass


def _sftp_upload_dir(sftp, local_dir: Path, remote_dir: str, log):
    _sftp_mkdir_p(sftp, remote_dir)
    for item in sorted(local_dir.iterdir()):
        if item.name in _SFTP_SKIP or item.suffix == ".pyc":
            continue
        remote_item = f"{remote_dir}/{item.name}"
        if item.is_dir():
            _sftp_upload_dir(sftp, item, remote_item, log)
        else:
            sftp.put(str(item), remote_item)
            log(f"↑ {item.relative_to(ROOT)}")


def _start_streamlit(ssh, log):
    script = f"{_DEPLOY_REMOTE}/scripts/start_server.sh"
    cmd = (
        f"sed -i 's/\\r$//' {script} 2>/dev/null || true; "
        f"chmod +x {script}; "
        f"PORTAL_ROOT={_DEPLOY_REMOTE} PORTAL_PORT={_DEPLOY_APP_PORT} PORTAL_ENV=deploy bash {script}"
    )
    out, err, rc = _ssh_run(ssh, cmd, timeout=30)
    text = (out + err).strip()
    if rc == 0 and "NOT_LISTENING" not in text:
        log(f"🟢 Streamlit 기동 완료")
        log(f"접속 주소: http://{_DEPLOY_HOST}:{_DEPLOY_APP_PORT}")
    else:
        log(f"🔴 기동 실패:\n{text[-500:]}")


def _deploy():
    log_box = st.empty()
    lines = []

    def log(msg):
        lines.append(msg)
        log_box.code("\n".join(lines[-50:]), language=None)

    try:
        log(f"SSH 연결 중... {_DEPLOY_USER}@{_DEPLOY_HOST}:{_DEPLOY_SSH_PORT}")
        ssh = _ssh_connect()
        log("✅ SSH 연결 완료")

        out, _, _ = _ssh_run(ssh, f"test -d {_DEPLOY_REMOTE}/venv && echo YES || echo NO")
        first_deploy = out.strip() != "YES"

        sftp = ssh.open_sftp()
        _ssh_run(ssh, f"mkdir -p {_DEPLOY_REMOTE}")

        log("\n--- 코드 업로드 ---")
        for item in sorted(ROOT.iterdir()):
            if item.is_file() and (item.suffix in _UPLOAD_SUFFIXES or item.name in _UPLOAD_ROOT_EXTRAS):
                sftp.put(str(item), f"{_DEPLOY_REMOTE}/{item.name}")
                log(f"↑ {item.name}")
        for dir_name in _UPLOAD_DIRS:
            local_sub = ROOT / dir_name
            if local_sub.exists():
                _sftp_upload_dir(sftp, local_sub, f"{_DEPLOY_REMOTE}/{dir_name}", log)
        log("✅ 코드 업로드 완료")

        # data/ 전체는 올리지 않는다 — 배포 서버의 access_config.json을 로컬 IP로
        # 덮어써 실제 사용자를 잠가버린다. 로컬이 원본인 파일만 개별 업로드한다.
        for _name in ("visibility_config.json", "orchestrator_registry.json"):
            _local = ROOT / "data" / _name
            if _local.exists():
                _sftp_mkdir_p(sftp, f"{_DEPLOY_REMOTE}/data")
                sftp.put(str(_local), f"{_DEPLOY_REMOTE}/data/{_name}")
                log(f"↑ data/{_name}")

        sftp.close()

        if first_deploy:
            log("\n--- 가상환경 설치 ---")
            out, err, rc = _ssh_run(ssh, f"python3 -m venv {_DEPLOY_REMOTE}/venv", timeout=60)
            log("✅ venv 생성" if rc == 0 else f"❌ venv 실패: {err.strip()}")

            pip = f"{_DEPLOY_REMOTE}/venv/bin/pip"
            req = f"{_DEPLOY_REMOTE}/requirements.txt"
            log("패키지 설치 중...")
            out, err, rc = _ssh_run(ssh, f"{pip} install --upgrade pip && {pip} install -r {req}", timeout=300)
            log("✅ 패키지 설치 완료" if rc == 0 else f"❌ 설치 실패:\n{err.strip()[-400:]}")

        log("\n--- Streamlit 기동 ---")
        _start_streamlit(ssh, log)
        ssh.close()

    except Exception as e:
        log(f"\n❌ 배포 오류: {e}")


if not _DEPLOY_HOST:
    st.info(".env에 DEPLOY_HOST 등 배포 설정이 없습니다.")
else:
    st.caption(f"대상: `{_DEPLOY_USER}@{_DEPLOY_HOST}:{_DEPLOY_APP_PORT}` (SSH: {_DEPLOY_SSH_PORT}) → `{_DEPLOY_REMOTE}`")
    st.caption("최초 배포 시 venv 생성 및 패키지 설치 포함 / 이후 업데이트는 코드만 전송")

    col_dep, col_svc = st.columns(2)
    with col_dep:
        if st.button("🚀 서버에 배포", type="primary", use_container_width=True):
            _deploy()
    with col_svc:
        if st.button("🔄 Streamlit 재시작", use_container_width=True):
            log_box2 = st.empty()
            lines2 = []
            try:
                ssh2 = _ssh_connect()
                def log2(m):
                    lines2.append(m)
                    log_box2.code("\n".join(lines2), language=None)
                _start_streamlit(ssh2, log2)
                ssh2.close()
            except Exception as e:
                st.error(f"오류: {e}")
