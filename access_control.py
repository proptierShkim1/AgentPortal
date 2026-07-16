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
