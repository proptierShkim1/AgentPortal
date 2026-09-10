"""질문을 읽고 어느 에이전트를 부를지 정한다.

읽는 것은 레지스트리의 role/when_to_use/when_not_to_use뿐이다. 0개를 고르는
것도 정상 결과다 — 담당 에이전트가 없는 질문에 전부 호출하면 노이즈와 비용만
늘어난다."""
import orchestrator_llm

ROUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["agent", "reason"],
                "additionalProperties": False,
            },
        },
        # 유니온 타입(["string","null"])을 쓰지 않는다 — 구조화 출력 스키마에서
        # 거부될 수 있다. 고를 에이전트가 있으면 빈 문자열을 받고, route()가
        # 그것을 None으로 정규화한다.
        "none_reason": {"type": "string"},
    },
    "required": ["picks", "none_reason"],
    "additionalProperties": False,
}

SYSTEM = """너는 사내 AI 에이전트 오케스트레이터의 라우터다.
사용자 질문을 읽고, 아래 에이전트 목록 중 그 질문에 실제로 답할 수 있는 것만 고른다.

규칙:
- 각 에이전트의 "언제 쓰는가"와 "언제 쓰지 않는가"를 모두 근거로 삼는다.
- 질문이 여러 에이전트에 걸치면 걸친 만큼 모두 고른다.
- 확실하지 않다고 해서 넓게 고르지 않는다. 관련 없는 에이전트를 부르면 답변에 노이즈가 섞인다.
- 어느 에이전트도 담당하지 않는 질문이면 picks를 빈 배열로 두고 none_reason에 한국어로 이유를 쓴다.
- picks가 비어 있지 않으면 none_reason은 빈 문자열("")로 둔다.
- agent 값은 반드시 목록에 있는 키를 그대로 쓴다.
- reason은 왜 그 에이전트를 골랐는지 한국어 한 문장으로 쓴다.

판단 예시:
- "처리방침 개정할 때 최근 법령 중 반영해야 할 게 있나?" -> 처리방침 실무와 법령 근거가
  모두 필요하므로 둘 다 고른다. 한쪽만 고르면 답변에 근거나 실무 관점 중 하나가 빠진다.
- "개인정보보호법 제17조 제3자 제공 요건이 뭐야?" -> 순수 법령 해석이므로 법령 담당 하나만
  고른다. 처리방침 담당을 함께 부르면 질문과 무관한 내용이 섞인다."""


def build_catalog(agents: dict) -> str:
    lines = []
    for key, entry in agents.items():
        lines.append(
            f"- 키: {key}\n"
            f"  이름: {entry.get('agent_name', '')}\n"
            f"  역할: {entry.get('role', '')}\n"
            f"  담당 도메인: {', '.join(entry.get('domain', []) or [])}\n"
            f"  언제 쓰는가: {entry.get('when_to_use', '')}\n"
            f"  언제 쓰지 않는가: {entry.get('when_not_to_use', '')}"
        )
    return "\n".join(lines)


def route(question: str, agents: dict, call_json=orchestrator_llm.call_json) -> dict:
    if not agents:
        return {"picks": [], "none_reason": "현재 오케스트레이터에 연결된 에이전트가 없습니다."}

    user = f"[에이전트 목록]\n{build_catalog(agents)}\n\n[사용자 질문]\n{question}"
    raw = call_json(SYSTEM, user, ROUTE_SCHEMA)

    picks, seen = [], set()
    for pick in raw.get("picks") or []:
        key = pick.get("agent")
        if key not in agents or key in seen:
            continue
        seen.add(key)
        picks.append({"agent": key, "reason": pick.get("reason") or ""})

    if picks:
        return {"picks": picks, "none_reason": None}

    none_reason = raw.get("none_reason") or "이 질문을 담당하는 에이전트를 찾지 못했습니다."
    return {"picks": [], "none_reason": none_reason}
