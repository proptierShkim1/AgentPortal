"""어댑터를 배포 서버에 올리고 user systemd로 상주시킨다.

경로 계산과 유닛 파일 생성은 순수 함수로 두고, SSH가 필요한 동작은 run 콜러블을
주입받는다. 그래야 서버 없이 테스트할 수 있다.

sudo를 쓰지 않는다 — 배포 사용자는 비밀번호 없는 sudo가 없다. 모든 서비스는
systemctl --user이고 유닛은 ~/.config/systemd/user/에 둔다.
"""
import hashlib
import io
import re
from datetime import datetime
from pathlib import Path

UNIT_TEMPLATE = """[Unit]
Description={description}
After=network.target

[Service]
Type=simple
WorkingDirectory={workdir}
ExecStart={exec_start}
Restart=on-failure
RestartSec=5
StandardOutput=append:{logfile}
StandardError=append:{logfile}

[Install]
WantedBy=default.target
"""


def expand_home(path: str, home: str) -> str:
    if path.startswith("~/"):
        return f"{home}/{path[2:]}"
    return path


def remote_dir(entry: dict, home: str) -> str:
    return expand_home(entry["deploy"]["remote_dir"], home).rstrip("/")


def local_dir(entry: dict, root: Path) -> Path:
    return root / entry["deploy"]["local_dir"]


def upload_pairs(entry: dict, root: Path, home: str) -> list:
    """(로컬 경로, 원격 경로) 목록. 선언된 순서를 유지한다."""
    base_local = local_dir(entry, root)
    base_remote = remote_dir(entry, home)
    return [(base_local / name, f"{base_remote}/{name}") for name in entry["deploy"]["files"]]


def unit_path(entry: dict, home: str) -> str:
    return f"{home}/.config/systemd/user/{entry['deploy']['unit']}"


def unit_text(entry: dict, home: str) -> str:
    dep = entry["deploy"]
    workdir = remote_dir(entry, home)
    return UNIT_TEMPLATE.format(
        description=dep.get("description") or dep["unit"],
        workdir=workdir,
        exec_start=f"{workdir}/{dep['exec']}",
        logfile=f"{workdir}/{dep.get('log') or 'adapter.log'}",
    )


def backup_name(remote_path: str, now: datetime = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M")
    return f"{remote_path}.bak-{stamp}"


def _local_md5(path: Path) -> str:
    # 로컬은 Windows라 CRLF가 섞인다. 서버 파일은 LF이므로 정규화하고 비교한다.
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.md5(data).hexdigest()


def file_state(run, local: Path, remote: str) -> str:
    """원격 파일이 로컬과 같은지. "동일" / "다름" / "없음"."""
    out, _, rc = run(f"md5sum {remote} 2>/dev/null | cut -d' ' -f1")
    digest = out.strip()
    if rc != 0 or not digest:
        return "없음"
    return "동일" if digest == _local_md5(local) else "다름"


def upload_files(sftp, run, entry: dict, root: Path, home: str, log) -> int:
    """변경된 파일만 올린다. 덮어쓰기 전에 원격 백업을 남긴다."""
    uploaded = 0
    for local, remote in upload_pairs(entry, root, home):
        if not local.exists():
            raise FileNotFoundError(f"로컬 파일이 없습니다: {local}")
        state = file_state(run, local, remote)
        if state == "동일":
            log(f"= {remote} (동일, 건너뜀)")
            continue
        if state == "다름":
            backup = backup_name(remote)
            run(f"cp -p {remote} {backup}")
            log(f"↩ 백업: {backup}")
        sftp.put(str(local), remote)
        log(f"↑ {remote}")
        uploaded += 1
    return uploaded


def _pip(entry: dict, home: str) -> str:
    return f"{remote_dir(entry, home)}/venv/bin/pip"


def pip_dry_run(run, entry: dict, home: str) -> tuple:
    """설치가 기존 패키지를 건드리는지 미리 본다.

    'Would uninstall'이 하나라도 보이면 막는다 — fastapi 핀을 잘못 잡아 starlette이
    내려가면 그 venv로 돌고 있는 streamlit 앱이 깨진다."""
    pkgs = " ".join(entry["deploy"].get("pip", []))
    if not pkgs:
        return True, "설치할 패키지 없음"
    out, err, _ = run(f"{_pip(entry, home)} install --dry-run {pkgs} 2>&1", timeout=240)
    text = (out or "") + (err or "")
    lines = [ln.strip() for ln in text.splitlines()
             if "Would install" in ln or "Would uninstall" in ln]
    summary = "\n".join(lines) or text.strip()[-300:]
    if "Would uninstall" in text:
        return False, summary
    return True, summary


def install_pip(sftp, run, entry: dict, home: str, log) -> bool:
    pkgs = " ".join(entry["deploy"].get("pip", []))
    if not pkgs:
        return True
    ok, summary = pip_dry_run(run, entry, home)
    log(f"· dry-run: {summary}")
    if not ok:
        log("❌ 기존 패키지가 제거/다운그레이드됩니다. 설치를 중단합니다.")
        return False
    out, err, rc = run(f"{_pip(entry, home)} install {pkgs} 2>&1", timeout=600)
    if rc == 0:
        log("✅ 의존성 설치 완료")
        return True
    log(f"❌ 설치 실패:\n{((out or '') + (err or '')).strip()[-400:]}")
    return False


def register_unit(sftp, run, entry: dict, home: str, log) -> bool:
    """유닛을 올리고 등록만 한다. 기동은 재시작 버튼의 몫이다."""
    path = unit_path(entry, home)
    run(f"mkdir -p {home}/.config/systemd/user")
    # heredoc으로 쉘에 넘기면 한글 Description이 인코딩 문제를 낸다. SFTP로 직접 쓴다.
    sftp.putfo(io.BytesIO(unit_text(entry, home).encode("utf-8")), path)
    log(f"↑ {path}")
    _, err, rc = run("systemctl --user daemon-reload")
    if rc != 0:
        log(f"❌ daemon-reload 실패: {err.strip()}")
        return False
    _, err, rc = run(f"systemctl --user enable {entry['deploy']['unit']}")
    if rc != 0:
        log(f"❌ enable 실패: {err.strip()}")
        return False
    log("✅ 유닛 등록 완료 (기동은 재시작 버튼으로)")
    return True


def unit_port(entry: dict):
    """유닛이 바인딩하려는 포트.

    thread 모드 유닛은 어댑터가 아니라 앱 자체를 띄우므로 exec의 --server.port가
    실제로 잡는 포트다. service 모드는 어댑터 포트를 그대로 쓴다."""
    dep = entry["deploy"]
    if dep["mode"] == "thread":
        match = re.search(r"--server\.port\s+(\d+)", dep.get("exec", ""))
        return int(match.group(1)) if match else None
    return entry.get("api_port")


def port_conflict(run, entry: dict) -> bool:
    """유닛이 쓸 포트를 지금 다른 프로세스가 잡고 있는가.

    렉스·폴리를 nohup으로 띄워둔 채 서비스를 start하면 바인딩에 실패하고
    Restart=on-failure가 5초마다 재시도하는 무한 루프가 된다(실제로 1,600회
    반복된 적이 있다). 자기 자신이 active면 충돌이 아니다 — 그건 정상 재시작이다."""
    port = unit_port(entry)
    if port is None:
        return False
    if service_state(run, entry) == "active":
        return False
    out, _, _ = run(f"ss -tln 2>/dev/null | grep -c ':{port} '")
    return out.strip() not in ("", "0")


def restart_unit(run, entry: dict, home: str, log) -> bool:
    unit = entry["deploy"]["unit"]
    if port_conflict(run, entry):
        port = unit_port(entry)
        log(f"❌ 포트 {port}을 다른 프로세스가 이미 쓰고 있어 재시작하지 않습니다.")
        log(f"   지금 start하면 바인딩 실패 → 5초마다 재시작 루프가 됩니다.")
        log(f"   기존 프로세스를 먼저 정리하세요: ps -eo pid,cmd | grep 'port {port}'")
        return False
    _, err, rc = run(f"systemctl --user restart {unit}", timeout=60)
    if rc != 0:
        log(f"❌ 재시작 실패: {err.strip()}")
        log(f"   로그 확인: journalctl --user -u {unit} -n 50 --no-pager")
        return False
    log(f"🔄 {unit} 재시작")
    return True


def service_state(run, entry: dict) -> str:
    out, _, _ = run(f"systemctl --user is-active {entry['deploy']['unit']}")
    return out.strip() or "unknown"


def needs_first_visit(entry: dict) -> bool:
    """thread 모드는 Streamlit이 페이지를 열어야 app.py를 실행하므로, 서비스를
    재시작해도 첫 접속 전까지 어댑터 스레드가 뜨지 않는다."""
    return entry["deploy"]["mode"] == "thread"
