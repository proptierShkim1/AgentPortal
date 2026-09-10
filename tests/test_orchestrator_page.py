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


# --- 질문 -> 라우팅 -> 호출 -> 합성 -> 세션 저장 종단 --------------------
# 세션 저장 기능을 넣으면서 페이지를 다시 짰는데, 그 뒤로 실제 질문이 지나간
# 적이 없다. LLM과 어댑터는 페이크로 막고 페이지 자체의 글루(히스토리 구성,
# 저장 호출, 렌더)만 검증한다.
import orchestrator_executor
import orchestrator_router
import orchestrator_sessions
import orchestrator_synth


def _wire(tmp_path, monkeypatch, *, picks=None, results=None, synth=None):
    monkeypatch.setattr(access_control, "CONFIG_PATH", tmp_path / "access_config.json")
    registry_path = tmp_path / "orchestrator_registry.json"
    registry_path.write_text(json.dumps({"lex": {
        "agent_name": "LexAgent", "role": "법령", "when_to_use": "법령",
        "api_port": 9501, "timeout_sec": 60, "enabled": True,
    }}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(orchestrator_registry, "CONFIG_PATH", registry_path)
    monkeypatch.setattr(orchestrator_sessions, "SESSIONS_DIR", tmp_path / "sessions")

    monkeypatch.setattr(orchestrator_router, "route", lambda q, a, **kw: {
        "picks": picks if picks is not None else [{"agent": "lex", "reason": "법령 질문"}],
        "none_reason": None if picks is None or picks else "담당 없음",
    })
    monkeypatch.setattr(orchestrator_executor, "ask_agents",
                        lambda *a, **kw: results if results is not None else [])
    monkeypatch.setattr(orchestrator_synth, "synthesize", lambda *a, **kw: synth or {
        "answer": "합성된 답변", "citations": [], "mode": "single", "failed": [],
    })
    monkeypatch.setattr(orchestrator_synth, "direct_answer", lambda *a, **kw: {
        "answer": "근거 없는 직접 답변", "citations": [], "mode": "direct", "failed": [],
    })


def _ask(question):
    at = AppTest.from_file(PAGE_PATH, default_timeout=60)
    at.session_state["_client_ip"] = "1.2.3.4"
    at.run()
    at.chat_input[0].set_value(question).run()
    return at


def test_question_and_answer_are_persisted_to_the_session(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)

    at = _ask("개인정보보호법 제17조 알려줘")

    assert not at.exception
    saved = orchestrator_sessions.load_sessions("1.2.3.4")[0]["messages"]
    assert [m["role"] for m in saved] == ["user", "assistant"]
    assert saved[0]["content"] == "개인정보보호법 제17조 알려줘"
    assert saved[1]["content"] == "합성된 답변"


def test_answer_records_which_agents_were_called(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)

    _ask("질문")

    meta = orchestrator_sessions.load_sessions("1.2.3.4")[0]["messages"][1]["meta"]
    assert meta["mode"] == "single"
    assert meta["agents"]          # 라벨이 비어 있지 않아야 지난 대화에서 알아볼 수 있다


def test_history_excludes_the_current_question(tmp_path, monkeypatch):
    """이번 질문까지 히스토리에 실어 보내면 에이전트가 같은 질문을 두 번 받는다."""
    seen = {}
    _wire(tmp_path, monkeypatch)

    def _spy(picks, agents, question, history, host, **kw):
        seen["question"] = question
        seen["history"] = history
        return []
    monkeypatch.setattr(orchestrator_executor, "ask_agents", _spy)

    _ask("첫 질문")

    assert seen["question"] == "첫 질문"
    assert seen["history"] == []


def test_follow_up_question_carries_previous_turns_as_history(tmp_path, monkeypatch):
    seen = {}
    _wire(tmp_path, monkeypatch)
    at = AppTest.from_file(PAGE_PATH, default_timeout=60)
    at.session_state["_client_ip"] = "1.2.3.4"
    at.run()
    at.chat_input[0].set_value("첫 질문").run()

    def _spy(picks, agents, question, history, host, **kw):
        seen["history"] = history
        return []
    monkeypatch.setattr(orchestrator_executor, "ask_agents", _spy)
    at.chat_input[0].set_value("이어지는 질문").run()

    assert [m["content"] for m in seen["history"]] == ["첫 질문", "합성된 답변"]
    assert all(set(m) == {"role", "content"} for m in seen["history"])


def test_direct_answer_is_used_and_saved_when_no_agent_matches(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, picks=[])

    at = _ask("점심 뭐 먹지")

    assert not at.exception
    saved = orchestrator_sessions.load_sessions("1.2.3.4")[0]["messages"]
    assert saved[1]["content"] == "근거 없는 직접 답변"
    assert saved[1]["meta"]["mode"] == "direct"


def test_citations_and_reasons_survive_in_the_saved_session(tmp_path, monkeypatch):
    """지난 대화를 다시 열었을 때 근거를 되짚을 수 있어야 한다."""
    _wire(tmp_path, monkeypatch, synth={
        "answer": "합성된 답변",
        "citations": [{"type": "law", "law_name": "개인정보 보호법",
                       "article": "제17조", "text": "조문 본문"}],
        "mode": "synth", "failed": [],
    })

    _ask("제17조 관련 질문")

    meta = orchestrator_sessions.load_sessions("1.2.3.4")[0]["messages"][1]["meta"]
    assert meta["citations"][0]["article"] == "제17조"
    assert meta["picks"][0]["reason"] == "법령 질문"
