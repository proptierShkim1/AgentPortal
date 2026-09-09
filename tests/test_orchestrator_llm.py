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


def test_model_is_opus_5():
    assert llm.MODEL == "claude-opus-5"


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
