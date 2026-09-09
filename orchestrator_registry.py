"""오케스트레이터 레지스트리 — 어느 에이전트가 붙어 있고 각자 무슨 역할인지.

라우터가 읽는 것은 코드가 아니라 이 파일의 role/when_to_use/when_not_to_use다.
에이전트 추가는 여기 항목 1개를 넣는 것으로 끝나야 하고, 오케스트레이터 코드는
바뀌지 않아야 한다."""
import json
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "data" / "orchestrator_registry.json"

# role/when_to_use가 비어 있으면 라우터가 근거 없이 고르게 되고, api_port가 없으면
# 호출 자체가 불가능하다. 그런 항목은 조용히 제외한다.
REQUIRED_FIELDS = ("agent_name", "role", "when_to_use", "api_port")


def load_registry() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_registry(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def enabled_agents(registry: dict) -> dict:
    result = {}
    for key, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        if not entry.get("enabled"):
            continue
        if any(not entry.get(field) for field in REQUIRED_FIELDS):
            continue
        result[key] = entry
    return result


def agent_url(entry: dict, host: str, path: str = "/ask") -> str:
    return f"http://{host}:{entry['api_port']}{path}"
