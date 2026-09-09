import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator_router as router

AGENTS = {
    "lex": {
        "agent_name": "LexAgent",
        "role": "개인정보 법령 해석",
        "domain": ["개인정보보호법"],
        "when_to_use": "법 조항을 물을 때",
        "when_not_to_use": "처리방침 검토는 policy",
        "api_port": 9501,
    },
    "radar": {
        "agent_name": "AI RADAR",
        "role": "AI 업계 동향",
        "domain": ["AI 뉴스"],
        "when_to_use": "AI 뉴스를 물을 때",
        "when_not_to_use": "법령은 lex",
        "api_port": 4501,
    },
}


def _fake_call_json(payload, capture=None):
    def _call(system, user, schema, max_tokens=2000, client=None):
        if capture is not None:
            capture.append({"system": system, "user": user, "schema": schema})
        return payload
    return _call


def test_build_catalog_includes_key_role_and_both_when_fields():
    catalog = router.build_catalog(AGENTS)
    assert "lex" in catalog
    assert "개인정보 법령 해석" in catalog
    assert "법 조항을 물을 때" in catalog
    assert "처리방침 검토는 policy" in catalog


def test_route_returns_picks_from_llm():
    payload = {"picks": [{"agent": "lex", "reason": "법령 질문"}], "none_reason": None}
    result = router.route("제15조가 뭐야?", AGENTS, call_json=_fake_call_json(payload))
    assert result == {"picks": [{"agent": "lex", "reason": "법령 질문"}], "none_reason": None}


def test_route_returns_multiple_picks():
    payload = {
        "picks": [
            {"agent": "lex", "reason": "근거 법령"},
            {"agent": "radar", "reason": "최근 동향"},
        ],
        "none_reason": None,
    }
    result = router.route("AI 규제 동향과 근거 법령", AGENTS, call_json=_fake_call_json(payload))
    assert [p["agent"] for p in result["picks"]] == ["lex", "radar"]


def test_route_returns_empty_picks_with_none_reason():
    payload = {"picks": [], "none_reason": "회의실 예약은 담당 에이전트가 없습니다"}
    result = router.route("회의실 예약 어떻게 해?", AGENTS, call_json=_fake_call_json(payload))
    assert result["picks"] == []
    assert "회의실" in result["none_reason"]


def test_route_drops_pick_for_unknown_agent_key():
    """LLM이 레지스트리에 없는 키를 만들어내도 호출로 이어지지 않아야 한다."""
    payload = {"picks": [{"agent": "존재하지않음", "reason": "환각"},
                         {"agent": "lex", "reason": "정상"}], "none_reason": None}
    result = router.route("질문", AGENTS, call_json=_fake_call_json(payload))
    assert [p["agent"] for p in result["picks"]] == ["lex"]


def test_route_sets_none_reason_when_all_picks_dropped():
    payload = {"picks": [{"agent": "없는키", "reason": "환각"}], "none_reason": None}
    result = router.route("질문", AGENTS, call_json=_fake_call_json(payload))
    assert result["picks"] == []
    assert result["none_reason"]


def test_route_dedupes_repeated_agent_key():
    payload = {"picks": [{"agent": "lex", "reason": "첫번째"},
                         {"agent": "lex", "reason": "중복"}], "none_reason": None}
    result = router.route("질문", AGENTS, call_json=_fake_call_json(payload))
    assert [p["agent"] for p in result["picks"]] == ["lex"]
    assert result["picks"][0]["reason"] == "첫번째"


def test_route_with_no_agents_returns_none_reason_without_calling_llm():
    calls = []
    result = router.route("질문", {}, call_json=_fake_call_json({}, capture=calls))
    assert result["picks"] == []
    assert result["none_reason"]
    assert calls == []


def test_route_passes_question_and_catalog_to_llm():
    calls = []
    payload = {"picks": [], "none_reason": "없음"}
    router.route("제15조가 뭐야?", AGENTS, call_json=_fake_call_json(payload, capture=calls))
    assert "제15조가 뭐야?" in calls[0]["user"]
    assert "lex" in calls[0]["user"]
    assert calls[0]["schema"] == router.ROUTE_SCHEMA


def test_route_tolerates_missing_reason_field():
    payload = {"picks": [{"agent": "lex"}], "none_reason": None}
    result = router.route("질문", AGENTS, call_json=_fake_call_json(payload))
    assert result["picks"] == [{"agent": "lex", "reason": ""}]
