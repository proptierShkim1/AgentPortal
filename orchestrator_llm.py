"""오케스트레이터용 LLM 호출 — 라우터(JSON)와 합성기(장문)가 공유한다.

Anthropic 키가 있으면 Claude를 먼저 쓰고, 없거나 실패하면 Gemini로 넘어간다
(하위 에이전트 LexAgent/llm_client.py와 같은 모양). 전환은 서버 로그에만 남는다 —
호출자에게 어느 모델이 답했는지 돌려주려면 반환 타입을 바꿔야 하고, 그러면
라우터·합성기·페이지가 전부 바뀐다. 화면에 필요해지면 그때 올린다.

Gemini 키는 `GEMINI_API_KEYS`에 쉼표로 여러 개 넣는다(고시·프니·에리와 같은 규약).
키는 라운드로빈으로 돌려 쓰고, 실패하면 다음 키로 넘어간다.

모델 ID는 여기 한 곳에만 둔다. `client` / `gemini_factory` 인자는 테스트에서
페이크를 주입하기 위한 것이고, 운영에서는 None으로 두어 환경 자격증명을 쓴다."""
import json
import os
import threading

ANTHROPIC_MODEL = "claude-opus-5"
GEMINI_MODEL_DEFAULT = "gemini-2.5-flash"

# 동시 사용자 수만큼 무제한 병렬 호출하면, Claude가 실패했을 때 한꺼번에 전원이
# Gemini로 쏠려 무료 키 일일 쿼터를 순식간에 소진한 적이 실제로 있다
# (LexAgent/llm_client.py에 기록된 사고). 완전한 해결책은 아니지만 순간적인
# 동시 폭주는 완화한다.
_MAX_CONCURRENT_LLM_CALLS = 5
_llm_semaphore = threading.Semaphore(_MAX_CONCURRENT_LLM_CALLS)

# 429가 이만큼 연속되면 특정 키 문제가 아니라 전체 할당량 소진으로 보고 멈춘다.
# 남은 키를 헛되게 순회하면 지연만 늘어난다 (GosiAgent/analyzer.py와 같은 판단).
_MAX_CONSECUTIVE_429 = 3

_gemini_key_index = 0
_key_lock = threading.Lock()

# Gemini의 response_schema는 JSON Schema가 아니라 OpenAPI 서브셋이고 타입이
# 대문자다. 호출자는 평범한 JSON Schema를 넘기고, 변환은 이 모듈 안에 갇힌다 —
# 라우터가 어느 공급자를 쓰는지 알게 되면 공급자를 바꿀 때 라우터도 바뀐다.
_GEMINI_KEEP_KEYS = ("description", "enum", "required")


def gemini_keys() -> list:
    value = os.getenv("GEMINI_API_KEYS", "")
    return [k.strip() for k in value.split(",") if k.strip()]


def gemini_model() -> str:
    return os.getenv("GEMINI_MODEL") or GEMINI_MODEL_DEFAULT


def to_gemini_schema(schema: dict) -> dict:
    """JSON Schema를 Gemini response_schema(OpenAPI 서브셋)로 변환한다.

    타입을 대문자로 올리고, OpenAPI 서브셋에 없는 `additionalProperties`는 버린다."""
    if not isinstance(schema, dict):
        return schema

    out = {}
    node_type = schema.get("type")
    if isinstance(node_type, str):
        out["type"] = node_type.upper()

    for key in _GEMINI_KEEP_KEYS:
        if key in schema:
            out[key] = schema[key]

    if isinstance(schema.get("properties"), dict):
        out["properties"] = {
            name: to_gemini_schema(sub) for name, sub in schema["properties"].items()
        }
    if "items" in schema:
        out["items"] = to_gemini_schema(schema["items"])

    return out


def normalize_null_strings(data: dict) -> dict:
    """문자열 "null"/"none"을 빈 문자열로 바꾼다.

    response_schema를 강제하면 모델이 실제 JSON null 대신 문자열 "null"을 채워
    넣는 경우가 있다(GosiAgent/analyzer.py에 기록된 현상). 그대로 두면 라우터의
    none_reason 자리에 "null"이라는 글자가 사용자에게 표시된다."""
    if not isinstance(data, dict):
        return data
    return {
        k: ("" if isinstance(v, str) and v.strip().lower() in ("null", "none") else v)
        for k, v in data.items()
    }


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic()


def _text_of(response) -> str:
    return "".join(b.text for b in response.content if b.type == "text")


def _call_anthropic(system: str, user: str, schema, max_tokens: int, client) -> str:
    kwargs = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if schema is not None:
        kwargs["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    response = client.messages.create(**kwargs)
    return _text_of(response)


def _next_gemini_key(keys: list) -> str:
    global _gemini_key_index
    with _key_lock:
        key = keys[_gemini_key_index % len(keys)]
        _gemini_key_index = (_gemini_key_index + 1) % len(keys)
    return key


def _gemini_config(system: str, schema, max_tokens: int):
    from google.genai import types

    kwargs = {"system_instruction": system, "max_output_tokens": max_tokens}
    if schema is not None:
        kwargs["response_mime_type"] = "application/json"
        kwargs["response_schema"] = to_gemini_schema(schema)
        # 사고 토큰이 max_output_tokens를 먼저 소진해 응답 본문이 잘리는 문제가
        # 분류·JSON 응답에서 실제로 발생한다 (LexAgent/llm_client.py 기록).
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return types.GenerateContentConfig(**kwargs)


def _default_gemini_factory(api_key: str):
    from google import genai
    return genai.Client(api_key=api_key)


def _call_gemini(system: str, user: str, schema, max_tokens: int, gemini_factory) -> str:
    keys = gemini_keys()
    if not keys:
        raise RuntimeError("GEMINI_API_KEYS가 설정되지 않았습니다.")

    factory = gemini_factory or _default_gemini_factory
    config = _gemini_config(system, schema, max_tokens)

    last_error = None
    consecutive_429 = 0
    for _ in range(len(keys)):
        key = _next_gemini_key(keys)
        try:
            client = factory(key)
            response = client.models.generate_content(
                model=gemini_model(),
                contents=user,
                config=config,
            )
            return (response.text or "").strip()
        except Exception as e:
            last_error = e
            print(f"  Gemini 키 실패 ({key[:8]}...): {e}")
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                consecutive_429 += 1
                if consecutive_429 >= _MAX_CONSECUTIVE_429:
                    print(f"  Gemini 429 연속 {_MAX_CONSECUTIVE_429}회 — 전체 할당량 소진으로 판단, 중단")
                    raise last_error
            else:
                consecutive_429 = 0

    raise RuntimeError(f"Gemini 키 전부 실패. 마지막 오류: {last_error}")


def _call(system: str, user: str, schema, max_tokens: int, client, gemini_factory) -> str:
    """Anthropic 우선, 실패하거나 키가 없으면 Gemini.

    client가 명시적으로 주어지면 그것을 그대로 쓴다(테스트의 주입이 환경변수보다
    우선한다)."""
    with _llm_semaphore:
        if client is not None:
            return _call_anthropic(system, user, schema, max_tokens, client)

        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                return _call_anthropic(
                    system, user, schema, max_tokens, _anthropic_client()
                )
            except Exception as e:
                print(f"Claude 오류: {e} → Gemini로 전환")
        else:
            print("ANTHROPIC_API_KEY 없음 → Gemini 사용")

        return _call_gemini(system, user, schema, max_tokens, gemini_factory)


def call_json(system: str, user: str, schema: dict, max_tokens: int = 2000,
              client=None, gemini_factory=None) -> dict:
    """구조화 출력으로 JSON을 받는다.

    Anthropic은 output_config.format이, Gemini는 response_schema가 유효한 JSON을
    보장하므로 응답 텍스트를 그대로 json.loads한다."""
    text = _call(system, user, schema, max_tokens, client, gemini_factory)
    if not text:
        raise RuntimeError("LLM 응답에 텍스트 블록이 없습니다.")
    return normalize_null_strings(json.loads(text))


def call_text(system: str, user: str, max_tokens: int = 16000,
              client=None, gemini_factory=None) -> str:
    return _call(system, user, None, max_tokens, client, gemini_factory)
