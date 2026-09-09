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
