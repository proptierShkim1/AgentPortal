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


def move_agent(visibility: dict, agents: list, name: str, delta: int) -> dict:
    """표시 순서에서 에이전트를 delta칸 옮긴 새 설정을 돌려준다.

    설정 화면의 ▲▼ 버튼이 쓴다. 숫자를 직접 입력받지 않는 이유는, 중간에 하나를
    끼워넣을 때 뒤쪽 번호를 전부 다시 매겨야 하고 같은 번호를 두 개 넣는 것도
    막을 수 없기 때문이다.

    이동이 성립하면 순서를 0..n-1로 다시 매긴다 — 기존 설정에 중복이나 결측
    order가 있어도 한 번의 이동으로 정리된다. 범위를 벗어나는 이동(맨 위에서 ▲,
    맨 아래에서 ▼)과 모르는 이름은 입력을 그대로 돌려준다.

    입력은 변경하지 않는다.
    """
    ordered = [a["name"] for a in sort_by_order(agents, visibility)]
    if name not in ordered:
        return visibility

    src = ordered.index(name)
    dst = src + delta
    if dst < 0 or dst >= len(ordered):
        return visibility

    ordered[src], ordered[dst] = ordered[dst], ordered[src]

    moved = {}
    for position, agent_name in enumerate(ordered):
        entry = dict(visibility.get(agent_name, {}))
        entry.setdefault("visible_local", True)
        entry.setdefault("visible_deploy", True)
        entry["order"] = position
        moved[agent_name] = entry
    return moved


def sort_by_order(agents: list, visibility: dict) -> list:
    ordered = sorted(
        enumerate(agents),
        key=lambda pair: visibility.get(pair[1]["name"], {}).get("order", pair[0]),
    )
    return [agent for _, agent in ordered]
