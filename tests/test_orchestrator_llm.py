import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator_llm as llm


class _Block:
    def __init__(self, text, type_="text"):
        self.type = type_
        self.text = text


class _Response:
    def __init__(self, blocks):
        self.content = blocks


class _FakeMessages:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def test_anthropic_model_is_opus_5():
    assert llm.ANTHROPIC_MODEL == "claude-opus-5"


def test_call_json_parses_json_text_block():
    client = _FakeClient(_Response([_Block('{"picks": [], "none_reason": "해당 없음"}')]))
    result = llm.call_json("시스템", "질문", {"type": "object"}, client=client)
    assert result == {"picks": [], "none_reason": "해당 없음"}


def test_call_json_sends_schema_in_output_config():
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    client = _FakeClient(_Response([_Block("{}")]))
    llm.call_json("시스템", "질문", schema, client=client)
    sent = client.messages.calls[0]
    assert sent["model"] == "claude-opus-5"
    assert sent["output_config"] == {"format": {"type": "json_schema", "schema": schema}}
    assert sent["system"] == "시스템"
    assert sent["messages"] == [{"role": "user", "content": "질문"}]


def test_call_json_skips_non_text_blocks():
    client = _FakeClient(_Response([_Block("", "thinking"), _Block('{"ok": true}')]))
    assert llm.call_json("s", "u", {"type": "object"}, client=client) == {"ok": True}


def test_call_json_raises_on_no_text_block():
    client = _FakeClient(_Response([_Block("", "thinking")]))
    with pytest.raises(RuntimeError, match="텍스트 블록"):
        llm.call_json("s", "u", {"type": "object"}, client=client)


def test_call_text_returns_concatenated_text_blocks():
    client = _FakeClient(_Response([_Block("앞부분 "), _Block("뒷부분")]))
    assert llm.call_text("s", "u", client=client) == "앞부분 뒷부분"


def test_call_text_does_not_send_output_config():
    client = _FakeClient(_Response([_Block("답변")]))
    llm.call_text("s", "u", client=client)
    assert "output_config" not in client.messages.calls[0]


# ---------------------------------------------------------------------------
# Gemini 폴백 — 다중 키 라운드로빈
# ---------------------------------------------------------------------------

class _GeminiResponse:
    def __init__(self, text):
        self.text = text


class _FakeGeminiModels:
    def __init__(self, owner):
        self._owner = owner

    def generate_content(self, **kwargs):
        self._owner.calls.append(kwargs)
        behavior = self._owner.behavior
        if isinstance(behavior, Exception):
            raise behavior
        if callable(behavior):
            return behavior(self._owner.api_key, kwargs)
        return _GeminiResponse(behavior)


class _FakeGeminiClient:
    def __init__(self, api_key, behavior, calls):
        self.api_key = api_key
        self.behavior = behavior
        self.calls = calls
        self.models = _FakeGeminiModels(self)


def _gemini_factory(behavior, calls, used_keys):
    """behavior: 문자열(응답 텍스트) / Exception(항상 실패) / callable(api_key, kwargs)."""
    def _factory(api_key):
        used_keys.append(api_key)
        return _FakeGeminiClient(api_key, behavior, calls)
    return _factory


def _no_anthropic(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def _keys(monkeypatch, value):
    monkeypatch.setenv("GEMINI_API_KEYS", value)
    monkeypatch.setattr(llm, "_gemini_key_index", 0)


def test_gemini_keys_splits_on_comma_and_strips(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", " k1 , k2,k3 , ")
    assert llm.gemini_keys() == ["k1", "k2", "k3"]


def test_gemini_keys_returns_empty_when_unset(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    assert llm.gemini_keys() == []


def test_gemini_model_defaults_when_env_unset(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert llm.gemini_model() == "gemini-2.5-flash"


def test_gemini_model_honours_env(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.0-pro")
    assert llm.gemini_model() == "gemini-3.0-pro"


def test_to_gemini_schema_uppercases_types():
    src = {"type": "object", "properties": {"name": {"type": "string"}}}
    assert llm.to_gemini_schema(src) == {
        "type": "OBJECT",
        "properties": {"name": {"type": "STRING"}},
    }


def test_to_gemini_schema_converts_nested_array_items():
    src = {
        "type": "object",
        "properties": {
            "picks": {"type": "array", "items": {"type": "object",
                                                 "properties": {"agent": {"type": "string"}}}},
        },
    }
    out = llm.to_gemini_schema(src)
    assert out["properties"]["picks"]["type"] == "ARRAY"
    assert out["properties"]["picks"]["items"]["type"] == "OBJECT"
    assert out["properties"]["picks"]["items"]["properties"]["agent"]["type"] == "STRING"


def test_to_gemini_schema_drops_additional_properties():
    src = {"type": "object", "properties": {}, "additionalProperties": False}
    assert "additionalProperties" not in llm.to_gemini_schema(src)


def test_to_gemini_schema_keeps_required_and_description():
    src = {"type": "object", "properties": {"a": {"type": "string", "description": "설명"}},
           "required": ["a"]}
    out = llm.to_gemini_schema(src)
    assert out["required"] == ["a"]
    assert out["properties"]["a"]["description"] == "설명"


def test_normalize_null_strings_blanks_literal_null():
    assert llm.normalize_null_strings({"none_reason": "null"}) == {"none_reason": ""}


def test_normalize_null_strings_is_case_insensitive_and_trims():
    assert llm.normalize_null_strings({"a": " NULL ", "b": "None"}) == {"a": "", "b": ""}


def test_normalize_null_strings_leaves_real_values_alone():
    data = {"none_reason": "담당 에이전트가 없습니다", "picks": []}
    assert llm.normalize_null_strings(data) == data


def test_call_text_uses_gemini_when_no_anthropic_key(monkeypatch):
    _no_anthropic(monkeypatch)
    _keys(monkeypatch, "k1")
    calls, used = [], []
    out = llm.call_text("시스템", "질문",
                        gemini_factory=_gemini_factory("제미나이 답변", calls, used))
    assert out == "제미나이 답변"
    assert used == ["k1"]


def test_call_text_sends_system_instruction_to_gemini(monkeypatch):
    _no_anthropic(monkeypatch)
    _keys(monkeypatch, "k1")
    calls, used = [], []
    llm.call_text("시스템 지시", "질문",
                  gemini_factory=_gemini_factory("답변", calls, used))
    assert calls[0]["config"].system_instruction == "시스템 지시"
    assert calls[0]["contents"] == "질문"


def test_call_json_sends_response_schema_to_gemini(monkeypatch):
    _no_anthropic(monkeypatch)
    _keys(monkeypatch, "k1")
    calls, used = [], []
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "additionalProperties": False}
    llm.call_json("시스템", "질문", schema,
                  gemini_factory=_gemini_factory('{"ok": true}', calls, used))
    config = calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema == {"type": "OBJECT", "properties": {"ok": {"type": "BOOLEAN"}}}


def test_call_json_disables_thinking_on_gemini(monkeypatch):
    _no_anthropic(monkeypatch)
    _keys(monkeypatch, "k1")
    calls, used = [], []
    llm.call_json("시스템", "질문", {"type": "object"},
                  gemini_factory=_gemini_factory("{}", calls, used))
    assert calls[0]["config"].thinking_config.thinking_budget == 0


def test_call_text_does_not_disable_thinking_on_gemini(monkeypatch):
    _no_anthropic(monkeypatch)
    _keys(monkeypatch, "k1")
    calls, used = [], []
    llm.call_text("시스템", "질문", gemini_factory=_gemini_factory("답변", calls, used))
    assert calls[0]["config"].thinking_config is None


def test_call_json_normalizes_literal_null_from_gemini(monkeypatch):
    _no_anthropic(monkeypatch)
    _keys(monkeypatch, "k1")
    calls, used = [], []
    out = llm.call_json("시스템", "질문", {"type": "object"},
                        gemini_factory=_gemini_factory('{"none_reason": "null"}', calls, used))
    assert out == {"none_reason": ""}


def test_gemini_round_robin_advances_key_between_calls(monkeypatch):
    _no_anthropic(monkeypatch)
    _keys(monkeypatch, "k1,k2,k3")
    calls, used = [], []
    factory = _gemini_factory("답변", calls, used)
    llm.call_text("s", "u", gemini_factory=factory)
    llm.call_text("s", "u", gemini_factory=factory)
    llm.call_text("s", "u", gemini_factory=factory)
    assert used == ["k1", "k2", "k3"]


def test_gemini_round_robin_wraps_around(monkeypatch):
    _no_anthropic(monkeypatch)
    _keys(monkeypatch, "k1,k2")
    calls, used = [], []
    factory = _gemini_factory("답변", calls, used)
    for _ in range(3):
        llm.call_text("s", "u", gemini_factory=factory)
    assert used == ["k1", "k2", "k1"]


def test_gemini_falls_over_to_next_key_on_failure(monkeypatch):
    _no_anthropic(monkeypatch)
    _keys(monkeypatch, "bad,good")
    calls, used = [], []

    def behavior(api_key, kwargs):
        if api_key == "bad":
            raise RuntimeError("키 거부")
        return _GeminiResponse("살아있는 키의 답변")

    out = llm.call_text("s", "u", gemini_factory=_gemini_factory(behavior, calls, used))
    assert out == "살아있는 키의 답변"
    assert used == ["bad", "good"]


def test_gemini_raises_when_every_key_fails(monkeypatch):
    _no_anthropic(monkeypatch)
    _keys(monkeypatch, "k1,k2")
    calls, used = [], []
    with pytest.raises(RuntimeError):
        llm.call_text("s", "u",
                      gemini_factory=_gemini_factory(RuntimeError("전부 실패"), calls, used))


def test_gemini_stops_after_three_consecutive_429(monkeypatch):
    """429가 연속 3회면 전체 할당량 소진으로 보고 남은 키를 헛되게 순회하지 않는다."""
    _no_anthropic(monkeypatch)
    _keys(monkeypatch, "k1,k2,k3,k4,k5,k6")
    calls, used = [], []
    with pytest.raises(Exception):
        llm.call_text("s", "u",
                      gemini_factory=_gemini_factory(
                          RuntimeError("429 RESOURCE_EXHAUSTED"), calls, used))
    assert len(used) == 3


def test_gemini_raises_when_no_keys_configured(monkeypatch):
    _no_anthropic(monkeypatch)
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEYS"):
        llm.call_text("s", "u")


def test_anthropic_is_preferred_when_key_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    _keys(monkeypatch, "k1")
    calls, used = [], []
    anthropic_client = _FakeClient(_Response([_Block("클로드 답변")]))
    monkeypatch.setattr(llm, "_anthropic_client", lambda: anthropic_client)
    out = llm.call_text("s", "u", gemini_factory=_gemini_factory("제미나이 답변", calls, used))
    assert out == "클로드 답변"
    assert used == []


def test_gemini_takes_over_when_anthropic_raises(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    _keys(monkeypatch, "k1")
    calls, used = [], []

    class _Boom:
        @property
        def messages(self):
            raise RuntimeError("크레딧 소진")

    monkeypatch.setattr(llm, "_anthropic_client", lambda: _Boom())
    out = llm.call_text("s", "u", gemini_factory=_gemini_factory("제미나이 답변", calls, used))
    assert out == "제미나이 답변"
    assert used == ["k1"]
