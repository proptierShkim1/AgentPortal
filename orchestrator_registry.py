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

# 배포에 필요한 선언. 하나라도 비면 어디에 무엇을 올릴지 알 수 없으므로 제외한다.
DEPLOY_REQUIRED_FIELDS = ("local_dir", "remote_dir", "files", "mode", "unit", "exec")
DEPLOY_MODES = ("service", "thread")


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


def deploy_targets(registry: dict) -> dict:
    """배포 정보가 온전히 선언된 항목만 돌려준다.

    deploy 블록이 없는 항목은 오류가 아니라 '로컬 전용 에이전트'로 보고 조용히
    제외한다. enabled는 보지 않는다 — 어댑터를 먼저 올려두고 나중에 켜는 운영이
    가능해야 한다."""
    result = {}
    for key, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        dep = entry.get("deploy")
        if not isinstance(dep, dict):
            continue
        if any(not dep.get(field) for field in DEPLOY_REQUIRED_FIELDS):
            continue
        if dep.get("mode") not in DEPLOY_MODES:
            continue
        result[key] = entry
    return result


def agent_url(entry: dict, host: str, path: str = "/ask") -> str:
    return f"http://{host}:{entry['api_port']}{path}"


def agent_labels(agents: dict, meta_agents: list) -> dict:
    """레지스트리 키 -> 화면 표시 라벨. agents_data.AGENTS의 아이콘·닉네임을
    agent_name으로 조인해 재사용한다. AGENTS에 없는 agent_name이면 그 이름을
    그대로 라벨로 쓴다 — 빈 라벨이 화면에 나가면 어느 에이전트가 답했는지
    알 수 없게 된다."""
    meta = {a["name"]: a for a in meta_agents}
    labels = {}
    for key, entry in agents.items():
        name = entry.get("agent_name", "")
        info = meta.get(name, {})
        icon = info.get("icon", "")
        nickname = info.get("nickname") or name
        labels[key] = f"{icon} {nickname}".strip()
    return labels
