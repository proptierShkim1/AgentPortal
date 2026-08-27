import json
from datetime import datetime
from pathlib import Path

from access_control import load_config

ROOT = Path(__file__).parent
LOG_PATH = ROOT / "data" / "access_log.jsonl"


def _lookup_name(ip: str) -> str:
    for entry in load_config().get("allowed_ips", []):
        if isinstance(entry, dict) and entry.get("ip") == ip:
            return entry.get("name", "")
    return ""


def log_visit(ip: str, page: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ip": ip or "",
        "name": _lookup_name(ip),
        "page": page,
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_logs() -> list:
    if not LOG_PATH.exists():
        return []
    logs = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            logs.append(json.loads(line))
        except Exception:
            continue
    return logs
