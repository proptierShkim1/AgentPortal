"""설정 페이지의 어댑터 배포 섹션 렌더 테스트.

SSH도 서버도 없이 '섹션이 뜨고 대상이 전부 나오는가'만 본다. 실제 업로드/재시작은
adapter_deploy 단위 테스트가 가짜 run으로 덮는다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from streamlit.testing.v1 import AppTest

import access_control

PAGE_PATH = "pages/설정.py"


def _run_page(tmp_path, monkeypatch):
    # access_config.json이 없으면 부트스트랩 모드라 누구나 admin이다.
    monkeypatch.setattr(access_control, "CONFIG_PATH", tmp_path / "access_config.json")
    at = AppTest.from_file(PAGE_PATH, default_timeout=60)
    at.session_state["_client_ip"] = "127.0.0.1"
    return at.run()


def test_settings_page_renders_adapter_section(tmp_path, monkeypatch):
    at = _run_page(tmp_path, monkeypatch)
    assert not at.exception
    assert "🔌 어댑터 배포" in [s.value for s in at.subheader]


def test_adapter_section_lists_every_deploy_target(tmp_path, monkeypatch):
    at = _run_page(tmp_path, monkeypatch)
    body = " ".join(m.value for m in at.markdown)
    for key in ("lex", "policy", "hana", "radar"):
        assert f"`{key}`" in body


def test_thread_mode_rows_carry_restart_warning(tmp_path, monkeypatch):
    # 렉스·폴리만 앱 안 스레드라 재시작이 사용자에게 보인다.
    at = _run_page(tmp_path, monkeypatch)
    body = " ".join(m.value for m in at.markdown)
    assert body.count("⚠️재시작=사용자 끊김") == 2
