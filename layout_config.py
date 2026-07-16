import json
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "data" / "layout_config.json"

DEFAULT_COLUMNS = 3
VALID_COLUMNS = (3, 4, 5)


def load_columns() -> int:
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            columns = cfg.get("columns", DEFAULT_COLUMNS)
            if columns in VALID_COLUMNS:
                return columns
        except Exception:
            pass
    return DEFAULT_COLUMNS


def save_columns(columns: int) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"columns": columns}, ensure_ascii=False, indent=2), encoding="utf-8")
