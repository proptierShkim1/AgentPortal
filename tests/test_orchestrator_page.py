"""오케스트레이터 페이지의 헤드리스 렌더 테스트.

streamlit.testing.v1.AppTest로 실제 Streamlit 런타임 위에서 페이지 스크립트를
돌린다. API 키도, 어댑터도 필요 없는 두 경로만 검증한다 — 그 이상(LLM 라우팅,
실제 어댑터 호출)은 orchestrator_router/executor/synth 단위 테스트가 이미
페이크로 덮는다.

access_control.CONFIG_PATH / orchestrator_registry.CONFIG_PATH를 tmp_path로
monkeypatch해서 이 리포에 커밋된 실제 data/access_config.json,
data/orchestrator_registry.json 내용과 무관하게 결정적으로 동작하게 한다."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from streamlit.testing.v1 import AppTest

import access_control
import orchestrator_registry

PAGE_PATH = "pages/오케스트레이터.py"


def test_page_warns_and_stops_when_no_agent_enabled(tmp_path, monkeypatch):
    # access_config.json이 존재하지 않으면 부트스트랩 모드로 누구나 admin이다 —
    # 이 테스트가 보고 싶은 것은 admin 게이팅이 아니라 "에이전트 없음" 분기다.
    monkeypatch.setattr(access_control, "CONFIG_PATH", tmp_path / "access_config.json")
    registry_path = tmp_path / "orchestrator_registry.json"
    registry_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(orchestrator_registry, "CONFIG_PATH", registry_path)

    at = AppTest.from_file(PAGE_PATH, default_timeout=30)
    at.session_state["_client_ip"] = "1.2.3.4"
    at.run()

    assert not at.exception
    assert len(at.warning) == 1
    assert "연결된 에이전트가 없습니다" in at.warning[0].value
    # st.stop()이 chat_input보다 먼저 걸려서 채팅 UI 자체가 그려지지 않아야 한다.
    assert len(at.chat_input) == 0


def test_page_blocks_non_admin(tmp_path, monkeypatch):
    # 부트스트랩 모드(admin 미등록 시 전원 허용)에서는 admin 게이트가 아무도
    # 막지 않으므로, 이 분기를 실제로 구동하려면 admin이 등록된 access_config를
    # 준비해야 한다 — 그래서 tmp_path에 admin 1명을 등록한 설정을 만든다.
    cfg = {"allowed_ips": [
        {"ip": "9.9.9.9", "name": "등록된 관리자", "is_admin": True, "can_view_history": True}
    ]}
    access_config_path = tmp_path / "access_config.json"
    access_config_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(access_control, "CONFIG_PATH", access_config_path)
    # 레지스트리 내용은 이 테스트와 무관하지만, 실제 커밋된 파일을 읽지 않도록
    # 똑같이 격리해둔다.
    registry_path = tmp_path / "orchestrator_registry.json"
    registry_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(orchestrator_registry, "CONFIG_PATH", registry_path)

    at = AppTest.from_file(PAGE_PATH, default_timeout=30)
    at.session_state["_client_ip"] = "1.2.3.4"  # 등록된 admin(9.9.9.9)이 아님
    at.run()

    assert not at.exception
    assert len(at.error) == 1
    assert "관리자만 사용할 수 있습니다" in at.error[0].value
    # admin 게이트에서 멈춰서 제목도, 경고도 그려지지 않아야 한다.
    assert len(at.title) == 0
    assert len(at.warning) == 0
