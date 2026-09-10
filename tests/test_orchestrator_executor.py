import sys
import json
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator_executor as ex

HOST = "192.168.14.222"

AGENTS = {
    "lex": {"agent_name": "LexAgent", "api_port": 9501, "timeout_sec": 60},
    "policy": {"agent_name": "PolicyAgent", "api_port": 9502, "timeout_sec": 60},
}


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_body(answer, sufficient=True, citations=None, grounding=None):
    return {
        "answer": answer,
        "sufficient": sufficient,
        "citations": citations if citations is not None else [],
        "grounding": grounding if grounding is not None else {},
        "agent": "LexAgent",
        "elapsed_ms": 1234,
    }


def test_ask_agent_returns_parsed_result():
    def handler(request):
        assert request.url.path == "/ask"
        assert json.loads(request.content)["question"] == "제15조?"
        return httpx.Response(200, json=_ok_body("답변입니다"))

    result = ex.ask_agent("lex", AGENTS["lex"], "제15조?", [], HOST, _client(handler))
    assert result.ok is True
    assert result.agent == "lex"
    assert result.answer == "답변입니다"
    assert result.sufficient is True
    assert result.error == ""


def test_ask_agent_sends_chat_history():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_body("답변"))

    history = [{"role": "user", "content": "앞 질문"}]
    ex.ask_agent("lex", AGENTS["lex"], "질문", history, HOST, _client(handler))
    assert captured["body"]["chat_history"] == history


def test_ask_agent_targets_registry_port():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_ok_body("답변"))

    ex.ask_agent("policy", AGENTS["policy"], "질문", [], HOST, _client(handler))
    assert captured["url"] == "http://192.168.14.222:9502/ask"


def test_ask_agent_marks_not_ok_on_http_500():
    def handler(request):
        return httpx.Response(500, text="서버 폭발")

    result = ex.ask_agent("lex", AGENTS["lex"], "질문", [], HOST, _client(handler))
    assert result.ok is False
    assert "500" in result.error
    assert result.answer == ""


def test_ask_agent_marks_not_ok_on_timeout():
    def handler(request):
        raise httpx.ReadTimeout("시간 초과", request=request)

    result = ex.ask_agent("lex", AGENTS["lex"], "질문", [], HOST, _client(handler))
    assert result.ok is False
    assert result.error


def test_ask_agent_marks_not_ok_on_connect_error():
    def handler(request):
        raise httpx.ConnectError("연결 거부", request=request)

    result = ex.ask_agent("lex", AGENTS["lex"], "질문", [], HOST, _client(handler))
    assert result.ok is False
    assert result.error


def test_ask_agent_marks_not_ok_on_invalid_json():
    def handler(request):
        return httpx.Response(200, text="이건 JSON이 아님")

    result = ex.ask_agent("lex", AGENTS["lex"], "질문", [], HOST, _client(handler))
    assert result.ok is False
    assert result.error


def test_ask_agent_defaults_missing_optional_fields():
    def handler(request):
        return httpx.Response(200, json={"answer": "답변만 있음"})

    result = ex.ask_agent("lex", AGENTS["lex"], "질문", [], HOST, _client(handler))
    assert result.ok is True
    assert result.sufficient is False
    assert result.citations == []
    assert result.grounding == {}


def test_ask_agents_returns_result_per_pick_in_pick_order():
    def handler(request):
        port = request.url.port
        return httpx.Response(200, json=_ok_body(f"포트{port}"))

    picks = [{"agent": "policy", "reason": ""}, {"agent": "lex", "reason": ""}]
    results = ex.ask_agents(picks, AGENTS, "질문", [], HOST, _client(handler))
    assert [r.agent for r in results] == ["policy", "lex"]
    assert results[0].answer == "포트9502"
    assert results[1].answer == "포트9501"


def test_ask_agents_isolates_failure_of_one_agent():
    def handler(request):
        if request.url.port == 9501:
            raise httpx.ConnectError("렉스 다운", request=request)
        return httpx.Response(200, json=_ok_body("폴리는 살아있음"))

    picks = [{"agent": "lex", "reason": ""}, {"agent": "policy", "reason": ""}]
    results = ex.ask_agents(picks, AGENTS, "질문", [], HOST, _client(handler))
    by_key = {r.agent: r for r in results}
    assert by_key["lex"].ok is False
    assert by_key["policy"].ok is True
    assert by_key["policy"].answer == "폴리는 살아있음"


def test_ask_agents_all_down_returns_all_failed_results():
    def handler(request):
        raise httpx.ConnectError("전부 다운", request=request)

    picks = [{"agent": "lex", "reason": ""}, {"agent": "policy", "reason": ""}]
    results = ex.ask_agents(picks, AGENTS, "질문", [], HOST, _client(handler))
    assert len(results) == 2
    assert all(r.ok is False for r in results)


def test_ask_agents_skips_pick_missing_from_registry():
    def handler(request):
        return httpx.Response(200, json=_ok_body("답변"))

    picks = [{"agent": "없는키", "reason": ""}, {"agent": "lex", "reason": ""}]
    results = ex.ask_agents(picks, AGENTS, "질문", [], HOST, _client(handler))
    assert [r.agent for r in results] == ["lex"]


def test_ask_agent_recovers_from_non_numeric_elapsed_ms():
    def handler(request):
        return httpx.Response(200, json=_ok_body("답변") | {"elapsed_ms": "12ms"})

    result = ex.ask_agent("lex", AGENTS["lex"], "질문", [], HOST, _client(handler))
    # 계약을 어긴 elapsed_ms 하나 때문에 예외가 나면 안 된다 — 로컬 측정치로
    # 대체하거나 깔끔한 ok=False로 떨어져야 한다.
    assert isinstance(result.elapsed_ms, int)
    if result.ok:
        assert result.answer == "답변"
    else:
        assert result.error


def test_ask_agent_treats_non_list_citations_as_empty():
    def handler(request):
        return httpx.Response(200, json=_ok_body("답변", citations=["법령명만 문자열로 옴"]))

    result = ex.ask_agent("lex", AGENTS["lex"], "질문", [], HOST, _client(handler))
    assert result.ok is True
    assert result.citations == []


def test_ask_agent_treats_list_grounding_as_empty_dict():
    def handler(request):
        return httpx.Response(200, json=_ok_body("답변", grounding=["리스트로 옴"]))

    result = ex.ask_agent("lex", AGENTS["lex"], "질문", [], HOST, _client(handler))
    assert result.ok is True
    assert result.grounding == {}


def test_ask_agent_treats_non_string_answer_as_empty_string():
    def handler(request):
        return httpx.Response(200, json=_ok_body(123))

    result = ex.ask_agent("lex", AGENTS["lex"], "질문", [], HOST, _client(handler))
    assert result.ok is True
    assert result.answer == ""


def test_ask_agents_isolates_off_contract_body_from_healthy_agent():
    """가장 중요한 회귀 테스트 — 한 어댑터가 계약을 어긴 200 응답을 줘도
    ThreadPoolExecutor의 f.result()가 예외를 재발생시켜 건강한 다른 에이전트의
    결과까지 함께 날려선 안 된다."""
    def handler(request):
        if request.url.port == 9501:
            return httpx.Response(200, json=_ok_body("렉스", citations="이건 리스트가 아님"))
        return httpx.Response(200, json=_ok_body("폴리는 정상"))

    picks = [{"agent": "lex", "reason": ""}, {"agent": "policy", "reason": ""}]
    results = ex.ask_agents(picks, AGENTS, "질문", [], HOST, _client(handler))
    by_key = {r.agent: r for r in results}
    assert by_key["policy"].ok is True
    assert by_key["policy"].answer == "폴리는 정상"


def test_check_health_returns_ok_and_corpus_counts():
    def handler(request):
        assert request.url.path == "/health"
        return httpx.Response(200, json={"ok": True, "corpus_counts": {"laws": 1200}})

    health = ex.check_health(AGENTS["lex"], HOST, _client(handler))
    assert health["ok"] is True
    assert health["corpus_counts"] == {"laws": 1200}


def test_check_health_reports_not_ok_on_connect_error():
    def handler(request):
        raise httpx.ConnectError("다운", request=request)

    health = ex.check_health(AGENTS["lex"], HOST, _client(handler))
    assert health["ok"] is False
    assert health["error"]


# --- 헬스체크 타임아웃 출처 -------------------------------------------------
# 5초로 하드코딩돼 있어서 콜드 스타트 직후 첫 확인이 실패했다(렉스 7.8초,
# 프니 8~11초 실측). ask_agent와 같이 레지스트리에서 받도록 바꾼 것을 고정한다.


def _timeout_capturing_client(seen):
    def handler(request):
        seen.append(request.extensions.get("timeout", {}))
        return httpx.Response(200, json={"ok": True, "corpus_counts": {"laws": 1}})
    return _client(handler)


def test_check_health_uses_registry_timeout():
    seen = []
    entry = {"api_port": 9501, "health_timeout_sec": 20}

    ex.check_health(entry, HOST, client=_timeout_capturing_client(seen))

    assert seen[0]["read"] == 20


def test_check_health_falls_back_to_default_timeout():
    seen = []
    entry = {"api_port": 9501}          # health_timeout_sec 없음

    ex.check_health(entry, HOST, client=_timeout_capturing_client(seen))

    assert seen[0]["read"] == ex.DEFAULT_HEALTH_TIMEOUT_SEC


def test_default_health_timeout_is_longer_than_observed_cold_start():
    """콜드 스타트 실측이 8~11초였다. 기본값이 그보다 짧으면 멀쩡한 에이전트가
    기동 직후 항상 죽은 것으로 보고된다."""
    assert ex.DEFAULT_HEALTH_TIMEOUT_SEC >= 15


def test_health_timeout_is_shorter_than_ask_timeout():
    """헬스체크가 /ask만큼 오래 기다리면 상태 확인 화면이 그동안 멈춘다."""
    assert ex.DEFAULT_HEALTH_TIMEOUT_SEC < ex.DEFAULT_TIMEOUT_SEC
