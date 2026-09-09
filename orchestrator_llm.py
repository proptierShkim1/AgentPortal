"""오케스트레이터용 LLM 호출 — 라우터(JSON)와 합성기(장문)가 공유한다.

모델 ID를 여기 한 곳에만 둔다. client 인자는 테스트에서 페이크를 주입하기 위한
것이고, 운영에서는 None으로 두어 환경 자격증명을 그대로 쓴다."""
import json

MODEL = "claude-opus-5"


def _client():
    import anthropic
    return anthropic.Anthropic()


def _text_of(response) -> str:
    return "".join(b.text for b in response.content if b.type == "text")


def call_json(system: str, user: str, schema: dict, max_tokens: int = 2000, client=None) -> dict:
    """구조화 출력으로 JSON을 받는다. output_config.format이 유효한 JSON을
    보장하므로 텍스트 블록을 그대로 json.loads한다."""
    client = client or _client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    text = _text_of(response)
    if not text:
        raise RuntimeError("LLM 응답에 텍스트 블록이 없습니다.")
    return json.loads(text)


def call_text(system: str, user: str, max_tokens: int = 16000, client=None) -> str:
    client = client or _client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return _text_of(response)
