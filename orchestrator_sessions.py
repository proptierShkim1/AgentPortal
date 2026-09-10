"""오케스트레이터 대화를 클라이언트(IP)별 파일로 저장한다.

새로고침·페이지 이동 뒤에도 지난 대화를 다시 열어 이어서 물을 수 있게 하려는
것이다. LexAgent의 `chat_session_store.py`와 같은 구조를 따른다 — 리포가 다르니
import하지 않고 같은 패턴으로 포팅했다.

저장 형식은 IP별 단일 JSON 파일이다.

    data/orchestrator_sessions/<IP>.json
    {"sessions": [{"id", "started_at", "messages": [{"role", "content", "meta"?}]}]}

`meta`에는 어느 에이전트가 답했는지 같은 부가 정보를 담는다. 본문(content)과 분리해
두는 이유는, 나중에 표시 방식이 바뀌어도 저장된 대화 본문은 그대로 두기 위해서다.
"""
import datetime
import json
import re
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).parent
SESSIONS_DIR = ROOT / "data" / "orchestrator_sessions"
KST = datetime.timezone(datetime.timedelta(hours=9))

# 한 사람이 탭 2개를 열고 거의 동시에 질문하면, 각 탭이 메모리에 들고 있던 sessions가
# 서로의 최신 상태를 모른 채 파일 전체를 덮어써서 상대 탭의 대화가 사라질 수 있다.
# 저장 직전에 락을 잡고 파일을 다시 읽어 그 위에 병합해서 막는다.
_lock = threading.Lock()

# 한 IP의 세션이 무한정 쌓이면 파일이 커지고 선택 목록도 못 쓰게 된다.
_MAX_SESSIONS = 50


def _sessions_path(client_ip: str) -> Path:
    # IP 문자열이 그대로 파일명이 되므로 경로 조작 문자를 막는다.
    safe = re.sub(r"[^0-9a-zA-Z_.-]", "_", client_ip or "unknown")
    return SESSIONS_DIR / f"{safe}.json"


def now_label() -> str:
    return datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M")


def load_sessions(client_ip: str) -> list:
    """저장된 세션 목록을 오래된 것부터 반환한다. 파일이 없거나 깨졌으면 빈 목록."""
    path = _sessions_path(client_ip)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        sessions = data.get("sessions", [])
        return sessions if isinstance(sessions, list) else []
    except Exception:
        # 파일이 깨졌다고 대화 페이지 자체가 죽으면 안 된다 — 빈 목록으로 시작한다.
        return []


def _save_sessions(client_ip: str, sessions: list) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    trimmed = sessions[-_MAX_SESSIONS:]
    _sessions_path(client_ip).write_text(
        json.dumps({"sessions": trimmed}, ensure_ascii=False), encoding="utf-8"
    )


def create_session(client_ip: str) -> dict:
    """새 세션을 만들어 저장하고 그 세션을 반환한다."""
    session = {"id": str(uuid.uuid4()), "started_at": now_label(), "messages": []}
    with _lock:
        current = load_sessions(client_ip)
        current.append(session)
        _save_sessions(client_ip, current)
    return session


def append_message(client_ip: str, session_id: str, role: str, content: str,
                   meta: dict = None) -> None:
    """세션 하나에 메시지를 붙이고 전체를 저장한다.

    저장 직전에 파일을 다시 읽으므로, 다른 탭이 그 사이에 남긴 대화를 덮어쓰지 않는다.
    대상 세션이 파일에 없으면(이미 정리된 경우 등) 조용히 무시한다 — 대화 한 줄을
    못 남기는 것이 페이지 전체를 죽이는 것보다 낫다."""
    with _lock:
        current = load_sessions(client_ip)
        target = next((s for s in current if s.get("id") == session_id), None)
        if target is None:
            return
        message = {"role": role, "content": content}
        if meta:
            message["meta"] = meta
        target.setdefault("messages", []).append(message)
        _save_sessions(client_ip, current)


def delete_session(client_ip: str, session_id: str) -> None:
    with _lock:
        current = [s for s in load_sessions(client_ip) if s.get("id") != session_id]
        _save_sessions(client_ip, current)


def session_label(session: dict) -> str:
    """선택 목록에 쓸 한 줄 라벨 — 시작 시각 + 첫 질문 미리보기.

    시각만 있으면 어느 대화인지 구분이 안 되고, 질문만 있으면 순서를 알 수 없다."""
    started = session.get("started_at") or "시각 미기록"
    preview = next(
        (m.get("content", "")[:24] for m in session.get("messages", [])
         if m.get("role") == "user"),
        "",
    )
    count = sum(1 for m in session.get("messages", []) if m.get("role") == "user")
    if not preview:
        return f"{started} · 빈 대화"
    return f"{started} · {preview} ({count}문)"
