import json
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "data" / "visibility_config.json"


def load_visibility() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_visibility(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def visible_agents(agents: list, visibility: dict, is_deployed: bool) -> list:
    key = "visible_deploy" if is_deployed else "visible_local"
    return [a for a in agents if visibility.get(a["name"], {}).get(key, True)]
