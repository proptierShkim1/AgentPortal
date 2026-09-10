"""IP별 대화 세션 저장소 테스트.

SESSIONS_DIR을 tmp_path로 monkeypatch해서 실제 data/orchestrator_sessions/를
건드리지 않는다. 이 저장소가 지키려는 것은 두 가지다 — (1) IP가 다르면 대화가
섞이지 않는다 (2) 탭 2개가 거의 동시에 써도 상대 대화가 사라지지 않는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator_sessions as store


def _use_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SESSIONS_DIR", tmp_path / "orchestrator_sessions")


def test_load_returns_empty_for_unknown_ip(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    assert store.load_sessions("1.2.3.4") == []


def test_create_and_load_roundtrip(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    created = store.create_session("1.2.3.4")

    loaded = store.load_sessions("1.2.3.4")

    assert len(loaded) == 1
    assert loaded[0]["id"] == created["id"]
    assert loaded[0]["messages"] == []


def test_append_message_persists(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    s = store.create_session("1.2.3.4")

    store.append_message("1.2.3.4", s["id"], "user", "질문")
    store.append_message("1.2.3.4", s["id"], "assistant", "답변", meta={"mode": "synth"})

    messages = store.load_sessions("1.2.3.4")[0]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["meta"] == {"mode": "synth"}
    # meta가 없으면 키 자체를 만들지 않는다 — 저장 형식을 불필요하게 부풀리지 않는다.
    assert "meta" not in messages[0]


def test_sessions_are_isolated_per_ip(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    a = store.create_session("1.1.1.1")
    b = store.create_session("2.2.2.2")
    store.append_message("1.1.1.1", a["id"], "user", "A의 질문")

    assert len(store.load_sessions("1.1.1.1")) == 1
    assert len(store.load_sessions("2.2.2.2")) == 1
    assert store.load_sessions("2.2.2.2")[0]["messages"] == []
    assert b["id"] != a["id"]


def test_append_does_not_clobber_another_tabs_session(tmp_path, monkeypatch):
    """탭 A가 오래된 목록을 들고 있어도, 저장 직전 파일을 다시 읽어 병합하므로
    탭 B가 만든 세션이 사라지지 않는다."""
    _use_tmp(tmp_path, monkeypatch)
    first = store.create_session("1.2.3.4")
    second = store.create_session("1.2.3.4")   # 다른 탭이 만든 세션

    store.append_message("1.2.3.4", first["id"], "user", "첫 탭 질문")

    loaded = store.load_sessions("1.2.3.4")
    assert [s["id"] for s in loaded] == [first["id"], second["id"]]


def test_append_to_missing_session_is_ignored(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    store.create_session("1.2.3.4")

    store.append_message("1.2.3.4", "존재하지-않는-id", "user", "질문")

    assert store.load_sessions("1.2.3.4")[0]["messages"] == []


def test_delete_session(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    a = store.create_session("1.2.3.4")
    b = store.create_session("1.2.3.4")

    store.delete_session("1.2.3.4", a["id"])

    assert [s["id"] for s in store.load_sessions("1.2.3.4")] == [b["id"]]


def test_corrupted_file_does_not_raise(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    store.create_session("1.2.3.4")
    store._sessions_path("1.2.3.4").write_text("{ 깨진 JSON", encoding="utf-8")

    # 대화 파일이 깨졌다고 페이지 전체가 죽으면 안 된다.
    assert store.load_sessions("1.2.3.4") == []


def test_ip_with_path_characters_cannot_escape_the_directory(tmp_path, monkeypatch):
    """IP 문자열이 그대로 파일명이 되므로 경로를 벗어나지 못해야 한다.

    점(.)은 정상 IP에 쓰이니 남기고, 구분자만 제거한다 — 결과 파일명에 ".."가
    남아도 구분자가 없으면 상위로 올라갈 수 없다. 그래서 문자열이 아니라
    '파일이 실제로 저장 디렉터리 안에 있는지'를 단정한다."""
    _use_tmp(tmp_path, monkeypatch)
    store.create_session("../../etc/passwd")

    sessions_dir = (tmp_path / "orchestrator_sessions").resolve()
    written = list(sessions_dir.iterdir())
    assert len(written) == 1
    assert written[0].resolve().parent == sessions_dir
    assert "/" not in written[0].name and "\\" not in written[0].name


def test_old_sessions_are_trimmed(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "_MAX_SESSIONS", 3)
    for _ in range(5):
        store.create_session("1.2.3.4")

    assert len(store.load_sessions("1.2.3.4")) == 3


def test_session_label_shows_time_and_first_question(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    s = store.create_session("1.2.3.4")
    store.append_message("1.2.3.4", s["id"], "user", "처리방침 개정 관련 질문입니다")
    store.append_message("1.2.3.4", s["id"], "assistant", "답변")

    label = store.session_label(store.load_sessions("1.2.3.4")[0])

    assert "처리방침 개정" in label
    assert "(1문)" in label


def test_session_label_marks_empty_conversation(tmp_path, monkeypatch):
    _use_tmp(tmp_path, monkeypatch)
    s = store.create_session("1.2.3.4")

    assert "빈 대화" in store.session_label(s)
