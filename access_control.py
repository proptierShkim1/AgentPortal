import json
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "data" / "access_config.json"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"allowed_ips": []}


def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def is_allowed(ip: str) -> bool:
    allowed_ips = load_config().get("allowed_ips", [])
    if not allowed_ips:
        return True
    if not ip:
        return True
    return any(
        (entry["ip"] if isinstance(entry, dict) else entry) == ip
        for entry in allowed_ips
    )


def is_admin(ip: str) -> bool:
    """관리자로 등록된 IP인지 확인. 관리자로 등록된 IP가 하나도 없으면 모두 허용
    (부트스트랩 모드 — 최초 1명이 설정 페이지에서 자신을 관리자로 지정할 수 있어야 함)."""
    admin_ips = [
        entry["ip"] for entry in load_config().get("allowed_ips", [])
        if isinstance(entry, dict) and entry.get("is_admin")
    ]
    if not admin_ips:
        return True
    if not ip:
        return False
    return ip in admin_ips


def can_view_history(ip: str) -> bool:
    """버전 이력(git 커밋 로그) 조회 권한이 있는 IP인지 확인. 관리자는 자동으로 포함.
    관리자도 이력열람 권한자도 하나도 없으면 모두 허용 (부트스트랩 모드)."""
    entries = [e for e in load_config().get("allowed_ips", []) if isinstance(e, dict)]
    granted_ips = {e["ip"] for e in entries if e.get("is_admin") or e.get("can_view_history")}
    if not granted_ips:
        return True
    if not ip:
        return False
    return ip in granted_ips
