import hashlib
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import adapter_deploy as ad

HOME = "/home/shkim1"
ROOT = Path("C:/repo/AgentPortal")


def _entry(**over):
    dep = {
        "local_dir": "../hana_p",
        "remote_dir": "~/hana_p",
        "files": ["api.py"],
        "mode": "service",
        "unit": "hana-adapter.service",
        "description": "프니 어댑터",
        "exec": "venv/bin/python api.py",
        "log": "adapter.log",
        "pip": ["fastapi==0.138.0", "uvicorn==0.42.0"],
    }
    dep.update(over)
    return {"agent_name": "Proptier AI News", "api_port": 7500, "deploy": dep}


def test_expand_home_replaces_tilde():
    assert ad.expand_home("~/hana_p", HOME) == "/home/shkim1/hana_p"


def test_expand_home_leaves_absolute_path():
    assert ad.expand_home("/srv/hana_p", HOME) == "/srv/hana_p"


def test_upload_pairs_maps_local_file_to_remote_path():
    pairs = ad.upload_pairs(_entry(), ROOT, HOME)
    assert pairs == [(ROOT / ".." / "hana_p" / "api.py", "/home/shkim1/hana_p/api.py")]


def test_upload_pairs_includes_entrypoint_for_thread_mode():
    entry = _entry(mode="thread", files=["api.py", "app.py"])
    remotes = [r for _, r in ad.upload_pairs(entry, ROOT, HOME)]
    assert remotes == ["/home/shkim1/hana_p/api.py", "/home/shkim1/hana_p/app.py"]


def test_unit_path_points_at_user_systemd_dir():
    # sudo가 없으므로 시스템 경로(/etc/systemd/system)를 쓰면 안 된다.
    assert ad.unit_path(_entry(), HOME) == "/home/shkim1/.config/systemd/user/hana-adapter.service"


def test_unit_text_uses_absolute_exec_and_workdir():
    text = ad.unit_text(_entry(), HOME)
    assert "WorkingDirectory=/home/shkim1/hana_p" in text
    assert "ExecStart=/home/shkim1/hana_p/venv/bin/python api.py" in text
    assert "Description=프니 어댑터" in text


def test_unit_text_appends_both_streams_to_one_log():
    text = ad.unit_text(_entry(), HOME)
    assert "StandardOutput=append:/home/shkim1/hana_p/adapter.log" in text
    assert "StandardError=append:/home/shkim1/hana_p/adapter.log" in text


def test_unit_text_restarts_on_failure_and_installs_to_default_target():
    text = ad.unit_text(_entry(), HOME)
    assert "Restart=on-failure" in text
    assert "WantedBy=default.target" in text


def test_backup_name_appends_timestamp():
    now = datetime(2026, 9, 11, 14, 30)
    assert ad.backup_name("/home/shkim1/LexAgent/app.py", now) == \
        "/home/shkim1/LexAgent/app.py.bak-20260911-1430"


class FakeRun:
    """run(cmd) -> (out, err, rc). 명령별 응답을 미리 지정하고 호출을 기록한다."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def __call__(self, cmd, timeout=None):
        self.calls.append(cmd)
        for needle, resp in self.responses.items():
            if needle in cmd:
                return resp
        return ("", "", 0)


class FakeSftp:
    def __init__(self):
        self.puts = []
        self.putfos = []

    def put(self, local, remote):
        self.puts.append((local, remote))

    def putfo(self, fileobj, remote):
        self.putfos.append((fileobj.read().decode("utf-8"), remote))


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_file_state_missing_when_remote_absent(tmp_path):
    local = _write(tmp_path, "api.py", "print(1)")
    run = FakeRun({"md5sum": ("", "No such file", 1)})
    assert ad.file_state(run, local, "/home/shkim1/hana_p/api.py") == "없음"


def test_file_state_same_when_md5_matches(tmp_path):
    local = _write(tmp_path, "api.py", "print(1)")
    digest = hashlib.md5(b"print(1)").hexdigest()
    run = FakeRun({"md5sum": (f"{digest}\n", "", 0)})
    assert ad.file_state(run, local, "/home/shkim1/hana_p/api.py") == "동일"


def test_file_state_differs_when_md5_differs(tmp_path):
    local = _write(tmp_path, "api.py", "print(1)")
    run = FakeRun({"md5sum": ("0" * 32 + "\n", "", 0)})
    assert ad.file_state(run, local, "/home/shkim1/hana_p/api.py") == "다름"


def test_file_state_normalizes_crlf_before_hashing(tmp_path):
    # 로컬은 Windows다. CRLF 때문에 매번 '다름'으로 보이면 대조가 무의미해진다.
    local = tmp_path / "api.py"
    local.write_bytes(b"print(1)\r\nprint(2)\r\n")
    digest = hashlib.md5(b"print(1)\nprint(2)\n").hexdigest()
    run = FakeRun({"md5sum": (f"{digest}\n", "", 0)})
    assert ad.file_state(run, local, "/x/api.py") == "동일"


def test_upload_files_backs_up_existing_remote_file_before_overwrite(tmp_path):
    local = _write(tmp_path, "api.py", "print(1)")
    entry = _entry(local_dir=".", files=["api.py"])
    run = FakeRun({"md5sum": ("0" * 32 + "\n", "", 0)})
    sftp = FakeSftp()
    ad.upload_files(sftp, run, entry, tmp_path, HOME, log=lambda m: None)
    assert any("cp -p /home/shkim1/hana_p/api.py /home/shkim1/hana_p/api.py.bak-" in c
               for c in run.calls)
    assert sftp.puts == [(str(local), "/home/shkim1/hana_p/api.py")]


def test_upload_files_skips_backup_when_remote_missing(tmp_path):
    _write(tmp_path, "api.py", "print(1)")
    entry = _entry(local_dir=".", files=["api.py"])
    run = FakeRun({"md5sum": ("", "No such file", 1)})
    ad.upload_files(FakeSftp(), run, entry, tmp_path, HOME, log=lambda m: None)
    assert not any("cp -p" in c for c in run.calls)


def test_upload_files_skips_identical_file(tmp_path):
    # 같은 파일을 매번 올리면 백업만 쌓인다.
    _write(tmp_path, "api.py", "print(1)")
    digest = hashlib.md5(b"print(1)").hexdigest()
    entry = _entry(local_dir=".", files=["api.py"])
    sftp = FakeSftp()
    count = ad.upload_files(sftp, FakeRun({"md5sum": (f"{digest}\n", "", 0)}),
                            entry, tmp_path, HOME, log=lambda m: None)
    assert count == 0
    assert sftp.puts == []


def test_upload_files_raises_when_local_file_missing(tmp_path):
    # 선언만 하고 api.py를 안 만든 경우 조용히 넘어가면 '배포됐다'고 착각한다.
    entry = _entry(local_dir=".", files=["api.py"])
    with pytest.raises(FileNotFoundError):
        ad.upload_files(FakeSftp(), FakeRun(), entry, tmp_path, HOME, log=lambda m: None)


def test_pip_dry_run_allows_pure_additions():
    run = FakeRun({"--dry-run": ("Would install fastapi-0.138.0 uvicorn-0.42.0\n", "", 0)})
    ok, msg = ad.pip_dry_run(run, _entry(), HOME)
    assert ok is True
    assert "fastapi-0.138.0" in msg


def test_pip_dry_run_blocks_when_existing_package_would_be_removed():
    # starlette 다운그레이드가 streamlit을 깨뜨린 사례가 있다. 설치 전에 막는다.
    run = FakeRun({"--dry-run": ("Would uninstall starlette-1.3.1\nWould install starlette-0.49.3\n", "", 0)})
    ok, msg = ad.pip_dry_run(run, _entry(), HOME)
    assert ok is False
    assert "starlette" in msg


def test_pip_dry_run_uses_repo_venv_pip():
    run = FakeRun()
    ad.pip_dry_run(run, _entry(), HOME)
    assert any("/home/shkim1/hana_p/venv/bin/pip install --dry-run" in c for c in run.calls)


def test_pip_dry_run_never_uses_requirements_file():
    # -r requirements.txt는 streamlit 등 돌고 있는 앱의 핀까지 움직인다.
    run = FakeRun()
    ad.pip_dry_run(run, _entry(), HOME)
    assert not any("-r " in c for c in run.calls)


def test_install_pip_aborts_when_dry_run_blocks():
    run = FakeRun({"--dry-run": ("Would uninstall starlette-1.3.1\n", "", 0)})
    assert ad.install_pip(FakeSftp(), run, _entry(), HOME, log=lambda m: None) is False
    assert not any("install fastapi" in c and "--dry-run" not in c for c in run.calls)


def test_register_unit_uploads_unit_and_enables_without_starting():
    run = FakeRun()
    sftp = FakeSftp()
    assert ad.register_unit(sftp, run, _entry(), HOME, log=lambda m: None) is True
    joined = " ".join(run.calls)
    assert "systemctl --user daemon-reload" in joined
    assert "systemctl --user enable hana-adapter.service" in joined
    assert "start" not in joined and "restart" not in joined
    assert sftp.putfos[0][1] == "/home/shkim1/.config/systemd/user/hana-adapter.service"


def test_register_unit_never_uses_sudo():
    run = FakeRun()
    ad.register_unit(FakeSftp(), run, _entry(), HOME, log=lambda m: None)
    assert not any("sudo" in c for c in run.calls)


def test_restart_unit_calls_systemctl_restart():
    run = FakeRun()
    assert ad.restart_unit(run, _entry(), HOME, log=lambda m: None) is True
    assert any("systemctl --user restart hana-adapter.service" in c for c in run.calls)


def test_restart_unit_reports_failure_with_journal_hint():
    run = FakeRun({"restart": ("", "Job failed", 1)})
    msgs = []
    assert ad.restart_unit(run, _entry(), HOME, log=msgs.append) is False
    assert any("journalctl --user -u hana-adapter.service" in m for m in msgs)


def test_service_state_returns_systemctl_output():
    run = FakeRun({"is-active": ("active\n", "", 0)})
    assert ad.service_state(run, _entry()) == "active"


def test_service_state_returns_inactive_on_nonzero_exit():
    run = FakeRun({"is-active": ("inactive\n", "", 3)})
    assert ad.service_state(run, _entry()) == "inactive"


def test_needs_first_visit_true_for_thread_mode():
    # Streamlit은 누가 페이지를 열어야 app.py를 실행한다. 재시작만으로는 어댑터가 안 뜬다.
    assert ad.needs_first_visit(_entry(mode="thread")) is True


def test_needs_first_visit_false_for_service_mode():
    assert ad.needs_first_visit(_entry(mode="service")) is False


def test_unit_port_reads_server_port_for_thread_mode():
    # thread 모드 유닛은 어댑터가 아니라 앱을 띄운다. 충돌하는 포트는 앱 포트다.
    entry = _entry(mode="thread", exec="venv/bin/python -m streamlit run app.py "
                                       "--server.address 0.0.0.0 --server.port 9001 --server.headless true")
    assert ad.unit_port(entry) == 9001


def test_unit_port_uses_api_port_for_service_mode():
    assert ad.unit_port(_entry()) == 7500


def test_port_conflict_true_when_port_held_and_service_down():
    # 기존 nohup 프로세스가 9001을 잡고 있는 상태. 여기서 start하면 무한 재시작 루프다.
    entry = _entry(mode="thread", exec="venv/bin/python -m streamlit run app.py --server.port 9001")
    run = FakeRun({"is-active": ("inactive\n", "", 3), "grep -c": ("1\n", "", 0)})
    assert ad.port_conflict(run, entry) is True


def test_port_conflict_false_when_port_free():
    entry = _entry(mode="thread", exec="venv/bin/python -m streamlit run app.py --server.port 9001")
    run = FakeRun({"is-active": ("inactive\n", "", 3), "grep -c": ("0\n", "", 0)})
    assert ad.port_conflict(run, entry) is False


def test_port_conflict_false_when_service_itself_is_active():
    # 자기 자신이 잡고 있는 포트는 충돌이 아니다 — 재시작이 정상 동작이다.
    entry = _entry(mode="thread", exec="venv/bin/python -m streamlit run app.py --server.port 9001")
    run = FakeRun({"is-active": ("active\n", "", 0), "grep -c": ("1\n", "", 0)})
    assert ad.port_conflict(run, entry) is False


def test_restart_unit_refuses_when_another_process_holds_the_port():
    entry = _entry(mode="thread", exec="venv/bin/python -m streamlit run app.py --server.port 9001")
    run = FakeRun({"is-active": ("inactive\n", "", 3), "grep -c": ("1\n", "", 0)})
    msgs = []
    assert ad.restart_unit(run, entry, HOME, log=msgs.append) is False
    # 재시작을 시도조차 하지 않아야 한다. 시도하면 5초마다 재시작 루프가 된다.
    assert not any("systemctl --user restart" in c for c in run.calls)
    assert any("9001" in m for m in msgs)


def test_restart_unit_proceeds_when_port_free():
    entry = _entry(mode="thread", exec="venv/bin/python -m streamlit run app.py --server.port 9001")
    run = FakeRun({"is-active": ("inactive\n", "", 3), "grep -c": ("0\n", "", 0)})
    assert ad.restart_unit(run, entry, HOME, log=lambda m: None) is True
    assert any("systemctl --user restart" in c for c in run.calls)


def test_remote_health_parses_corpus_counts():
    # 어댑터가 루프백에만 열려 있으므로 로컬에서 직접 HTTP를 못 친다. SSH로 curl한다.
    run = FakeRun({"curl": ('{"ok": true, "corpus_counts": {"mentions": 65908}}', "", 0)})
    result = ad.remote_health(run, _entry())
    assert result["ok"] is True
    assert result["corpus_counts"] == {"mentions": 65908}


def test_remote_health_curls_loopback_not_lan_ip():
    run = FakeRun()
    ad.remote_health(run, _entry())
    assert any("127.0.0.1:7500/health" in c for c in run.calls)
    assert not any("192.168" in c for c in run.calls)


def test_remote_health_reports_error_when_curl_fails():
    run = FakeRun({"curl": ("", "Connection refused", 7)})
    result = ad.remote_health(run, _entry())
    assert result["ok"] is False
    assert result["error"]


def test_remote_health_reports_error_on_unparsable_body():
    run = FakeRun({"curl": ("<html>502</html>", "", 0)})
    result = ad.remote_health(run, _entry())
    assert result["ok"] is False
