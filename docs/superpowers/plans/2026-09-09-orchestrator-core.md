# 오케스트레이터 코어 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AgentPortal 안에 오케스트레이터 코어(레지스트리·라우터·실행기·합성기)와 admin 전용 UI를 만들어, 페이크 어댑터만으로 종단 동작하는 상태까지 완성한다.

**Architecture:** 루트 평면 모듈 4개(`orchestrator_registry` / `orchestrator_llm` / `orchestrator_router` / `orchestrator_executor` / `orchestrator_synth`)와 Streamlit 페이지 1개. 하위 에이전트는 HTTP 사이드카(`POST /ask`, `GET /health`)로 호출하며, 이 계획에서는 실제 어댑터를 만들지 않고 스텁 트랜스포트로 테스트한다. 라우터·합성기의 LLM 호출은 전부 주입 가능한 함수 인자로 두어 페이크로 대체한다.

**Tech Stack:** Python, Streamlit, `anthropic` SDK (모델 `claude-opus-5`), `httpx`(동기) + `ThreadPoolExecutor`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-09-orchestrator-design.md`

## Global Constraints

- 모듈은 **루트 평면 배치**. `orchestrator/` 패키지를 만들지 않는다 — `pages/설정.py`의 배포 플로우가 루트 파일과 `.streamlit`/`scripts`/`pages`만 업로드하므로 새 패키지 디렉터리는 배포 때 빠진다.
- Anthropic 모델 ID는 **`claude-opus-5`** 고정. 하위 리포의 `claude-sonnet-4-6`을 따라가지 않는다.
- Anthropic 호출은 **공식 `anthropic` SDK**만 사용한다. `requests`/`httpx`로 Anthropic REST를 직접 치지 않는다.
- 어댑터 호출(우리 사이드카)은 **`httpx`**(동기)를 쓴다. `anthropic` 1.x는 내부적으로 `httpx2`를 쓰지만 그것과 섞지 않는다 — 두 라이브러리 사이로 객체를 넘기지 않으며, `httpx`는 `requirements.txt`에 명시 선언한다.
- `asyncio`를 쓰지 않는다. Streamlit은 동기 런타임이고 페이지 안에서 `asyncio.run`은 이벤트 루프 충돌을 일으킨다. 병렬은 `ThreadPoolExecutor`로 한다.
- 테스트는 기존 `tests/test_visibility_config.py` 관례를 따른다: `sys.path.insert(0, str(Path(__file__).parent.parent))` 후 모듈 import, 설정 경로는 `monkeypatch.setattr(mod, "CONFIG_PATH", tmp_path / ...)`로 갈아끼운다.
- 실행 명령은 저장소 루트에서 `pytest`. pytest 설정 파일은 없다(기본 디스커버리).
- 로컬 실행 시 주소/포트를 반드시 CLI로 덮어쓴다: `python -m streamlit run app.py --server.address 192.168.14.222 --server.port 9000`
- 어댑터 포트 규칙: `에이전트 포트 + 500` (렉스 9501, 폴리 9502, 프니 7500, 에리 4501, 삼일 9601).
- 커밋 메시지는 한국어로 쓴다(저장소 관례).

---

### Task 1: 호스트 해석 공용 모듈

`pages/포털.py:8-11`에 `IS_DEPLOYED`/`LOCAL_HOST`/`DEPLOY_HOST`/`AGENT_HOST`가 하드코딩돼 있다. 오케스트레이터도 같은 호스트를 알아야 하는데, 페이지에서 import하는 것은 Streamlit 구조상 부적절하다. 값이 두 곳으로 갈라지면 어댑터 호출이 조용히 엉뚱한 호스트로 간다. 루트 모듈로 뽑고 `포털.py`가 그것을 쓰게 한다.

**Files:**
- Create: `agent_host.py`
- Modify: `pages/포털.py:5-11`
- Test: `tests/test_agent_host.py`

**Interfaces:**
- Consumes: 없음
- Produces: `agent_host.LOCAL_HOST: str`, `agent_host.DEPLOY_HOST: str`, `agent_host.is_deployed() -> bool`, `agent_host.agent_host() -> str`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

```python
# tests/test_agent_host.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import agent_host


def test_is_deployed_false_when_env_unset(monkeypatch):
    monkeypatch.delenv("PORTAL_ENV", raising=False)
    assert agent_host.is_deployed() is False


def test_is_deployed_true_only_for_exact_deploy_value(monkeypatch):
    monkeypatch.setenv("PORTAL_ENV", "deploy")
    assert agent_host.is_deployed() is True
    monkeypatch.setenv("PORTAL_ENV", "DEPLOY")
    assert agent_host.is_deployed() is False


def test_agent_host_returns_local_when_not_deployed(monkeypatch):
    monkeypatch.delenv("PORTAL_ENV", raising=False)
    assert agent_host.agent_host() == "192.168.14.222"


def test_agent_host_returns_deploy_when_deployed(monkeypatch):
    monkeypatch.setenv("PORTAL_ENV", "deploy")
    assert agent_host.agent_host() == "192.168.10.169"
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `pytest tests/test_agent_host.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_host'`

- [ ] **Step 3: 최소 구현을 작성한다**

```python
# agent_host.py
"""에이전트 호스트 해석 — 로컬/배포 환경에 따라 하나의 호스트를 돌려준다.

에이전트는 개별 host 필드를 갖지 않는다. 환경마다 호스트가 하나이고 포트만
다르다. 이 값이 여러 곳에 복사되면 링크와 어댑터 호출이 서로 다른 서버를
가리키게 되므로 여기서만 정의한다."""
import os

LOCAL_HOST = "192.168.14.222"
DEPLOY_HOST = "192.168.10.169"


def is_deployed() -> bool:
    return os.environ.get("PORTAL_ENV") == "deploy"


def agent_host() -> str:
    return DEPLOY_HOST if is_deployed() else LOCAL_HOST
```

- [ ] **Step 4: 테스트가 통과하는 것을 확인한다**

Run: `pytest tests/test_agent_host.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: `포털.py`가 새 모듈을 쓰도록 바꾼다**

`pages/포털.py`의 5-11행을 찾는다:

```python
from agents_data import AGENTS
import os
from visibility_config import load_visibility, visible_agents, sort_by_order

IS_DEPLOYED = os.environ.get("PORTAL_ENV") == "deploy"
LOCAL_HOST = "192.168.14.222"
DEPLOY_HOST = "192.168.10.169"
AGENT_HOST = DEPLOY_HOST if IS_DEPLOYED else LOCAL_HOST
```

이것으로 교체한다:

```python
from agents_data import AGENTS
from visibility_config import load_visibility, visible_agents, sort_by_order
from agent_host import agent_host, is_deployed

IS_DEPLOYED = is_deployed()
AGENT_HOST = agent_host()
```

`import os`를 지웠으므로 `포털.py`에서 `os.`를 다른 곳에서도 쓰는지 확인한다:

Run: `grep -n "os\." "pages/포털.py"`
Expected: 출력 없음. 출력이 있으면 `import os`를 지우지 말고 남긴다.

- [ ] **Step 6: 앱이 여전히 뜨는지 확인한다**

Run: `python -m streamlit run app.py --server.address 192.168.14.222 --server.port 9000`
Expected: 포털 페이지에 카드가 이전과 동일하게 렌더링된다. `LOCAL_HOST`/`DEPLOY_HOST` 이름을 `포털.py` 안에서 참조하던 곳이 남아 있으면 `NameError`가 난다 — 그 경우 `AGENT_HOST`로 바꾼다. 확인 후 Ctrl+C로 종료한다.

- [ ] **Step 7: 커밋한다**

```bash
git add agent_host.py tests/test_agent_host.py pages/포털.py
git commit -m "에이전트 호스트 해석을 agent_host.py로 분리"
```

---

### Task 2: 레지스트리

**Files:**
- Create: `orchestrator_registry.py`
- Create: `data/orchestrator_registry.json`
- Test: `tests/test_orchestrator_registry.py`

**Interfaces:**
- Consumes: 없음
- Produces: `orchestrator_registry.CONFIG_PATH: Path`, `load_registry() -> dict`, `save_registry(cfg: dict) -> None`, `enabled_agents(registry: dict) -> dict`, `agent_url(entry: dict, host: str, path: str = "/ask") -> str`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

```python
# tests/test_orchestrator_registry.py
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator_registry as reg


def _entry(**over):
    base = {
        "agent_name": "LexAgent",
        "role": "개인정보 법령 해석",
        "domain": ["개인정보보호법"],
        "when_to_use": "법 조항을 물을 때",
        "when_not_to_use": "처리방침 검토 → policy로",
        "api_port": 9501,
        "timeout_sec": 60,
        "enabled": True,
    }
    base.update(over)
    return base


def test_load_registry_missing_file_returns_empty_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "CONFIG_PATH", tmp_path / "orchestrator_registry.json")
    assert reg.load_registry() == {}


def test_load_registry_corrupted_file_returns_empty_dict(tmp_path, monkeypatch):
    path = tmp_path / "orchestrator_registry.json"
    path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(reg, "CONFIG_PATH", path)
    assert reg.load_registry() == {}


def test_load_registry_valid_file_returns_parsed_dict(tmp_path, monkeypatch):
    path = tmp_path / "orchestrator_registry.json"
    data = {"lex": _entry()}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(reg, "CONFIG_PATH", path)
    assert reg.load_registry() == data


def test_save_registry_creates_data_dir_and_writes_json(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "orchestrator_registry.json"
    monkeypatch.setattr(reg, "CONFIG_PATH", path)
    cfg = {"lex": _entry()}
    reg.save_registry(cfg)
    assert json.loads(path.read_text(encoding="utf-8")) == cfg


def test_enabled_agents_keeps_only_enabled_entries():
    registry = {"lex": _entry(), "policy": _entry(agent_name="PolicyAgent", enabled=False)}
    assert list(reg.enabled_agents(registry)) == ["lex"]


def test_enabled_agents_drops_entry_missing_role():
    registry = {"lex": _entry(role="")}
    assert reg.enabled_agents(registry) == {}


def test_enabled_agents_drops_entry_missing_when_to_use():
    registry = {"lex": _entry(when_to_use="")}
    assert reg.enabled_agents(registry) == {}


def test_enabled_agents_drops_entry_missing_api_port():
    registry = {"lex": _entry(api_port=None)}
    assert reg.enabled_agents(registry) == {}


def test_enabled_agents_ignores_non_dict_entry():
    registry = {"lex": "이건 dict가 아니다"}
    assert reg.enabled_agents(registry) == {}


def test_agent_url_builds_ask_endpoint_by_default():
    assert reg.agent_url(_entry(), "192.168.14.222") == "http://192.168.14.222:9501/ask"


def test_agent_url_accepts_explicit_path():
    url = reg.agent_url(_entry(), "192.168.10.169", path="/health")
    assert url == "http://192.168.10.169:9501/health"
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `pytest tests/test_orchestrator_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator_registry'`

- [ ] **Step 3: 최소 구현을 작성한다**

```python
# orchestrator_registry.py
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


def agent_url(entry: dict, host: str, path: str = "/ask") -> str:
    return f"http://{host}:{entry['api_port']}{path}"
```

- [ ] **Step 4: 테스트가 통과하는 것을 확인한다**

Run: `pytest tests/test_orchestrator_registry.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: 초기 레지스트리 파일을 만든다**

`data/orchestrator_registry.json`. 이 계획 단계에서 실제 어댑터는 아직 없으므로 4개 모두 `enabled: false`로 넣는다 — 어댑터가 준비된 뒤 해당 항목만 `true`로 바꾼다.

```json
{
  "lex": {
    "agent_name": "LexAgent",
    "role": "개인정보 법령 해석",
    "domain": ["개인정보보호법", "시행령", "고시", "심결례"],
    "when_to_use": "개인정보보호법 조항의 의미·요건·위반 여부를 묻거나, 근거 조문과 심결례를 찾을 때",
    "when_not_to_use": "특정 회사의 처리방침 문서를 검토하는 것이면 policy를, 뉴스·동향이면 hana나 radar를 쓴다",
    "api_port": 9501,
    "timeout_sec": 60,
    "enabled": false
  },
  "policy": {
    "agent_name": "PolicyAgent",
    "role": "개인정보 처리방침 분석",
    "domain": ["처리방침", "체크리스트", "적정성 검토"],
    "when_to_use": "처리방침 문서의 항목 누락·적정성·개선안을 묻거나, 처리방침 작성·개정 실무를 물을 때",
    "when_not_to_use": "처리방침과 무관한 순수 법령 해석이면 lex를 쓴다",
    "api_port": 9502,
    "timeout_sec": 60,
    "enabled": false
  },
  "hana": {
    "agent_name": "Proptier AI News",
    "role": "부동산 뉴스·정책 동향",
    "domain": ["부동산 뉴스", "브랜드 언급", "정책 이벤트"],
    "when_to_use": "부동산 업계 뉴스, 브랜드 언급량, 정책 이벤트 동향을 물을 때",
    "when_not_to_use": "AI 업계 동향이면 radar를, 법령 해석이면 lex를 쓴다",
    "api_port": 7500,
    "timeout_sec": 90,
    "enabled": false
  },
  "radar": {
    "agent_name": "AI RADAR",
    "role": "AI 업계 뉴스·기술 동향",
    "domain": ["AI 뉴스", "arxiv", "기술 트렌드", "수집 통계"],
    "when_to_use": "AI 업계 뉴스·논문·기술 동향, 또는 수집 건수·기간별 집계를 물을 때",
    "when_not_to_use": "부동산 뉴스면 hana를, 법령이면 lex를 쓴다",
    "api_port": 4501,
    "timeout_sec": 90,
    "enabled": false
  }
}
```

- [ ] **Step 6: 커밋한다**

```bash
git add orchestrator_registry.py tests/test_orchestrator_registry.py data/orchestrator_registry.json
git commit -m "오케스트레이터 레지스트리 모듈 및 초기 설정 파일 추가"
```

---

### Task 3: LLM 클라이언트

라우터와 합성기가 공통으로 쓰는 얇은 래퍼. 모델 ID와 에러 처리를 한 곳에 모으고, 테스트에서 페이크로 갈아끼울 수 있게 한다.

Gemini 폴백은 넣지 않는다. 하위 리포(`LexAgent/llm_client.py`)에는 있지만 이 스펙이 요구하지 않았고, 폴백 경로가 생기면 "어느 모델이 답했는지"가 합성기 출처 표기에서 흐려진다.

**Files:**
- Create: `orchestrator_llm.py`
- Modify: `requirements.txt`
- Modify: `.env.example`
- Test: `tests/test_orchestrator_llm.py`

**Interfaces:**
- Consumes: 없음
- Produces: `orchestrator_llm.MODEL: str`, `call_json(system: str, user: str, schema: dict, max_tokens: int = 2000, client=None) -> dict`, `call_text(system: str, user: str, max_tokens: int = 16000, client=None) -> str`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

실제 API를 때리지 않는다. `client` 인자로 가짜 객체를 넣어 요청 파라미터와 응답 파싱만 검증한다.

```python
# tests/test_orchestrator_llm.py
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
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `pytest tests/test_orchestrator_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator_llm'`

- [ ] **Step 3: 최소 구현을 작성한다**

```python
# orchestrator_llm.py
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
```

- [ ] **Step 4: 테스트가 통과하는 것을 확인한다**

Run: `pytest tests/test_orchestrator_llm.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: 의존성과 환경변수 예시를 추가한다**

`requirements.txt`를 이것으로 바꾼다:

```
streamlit
python-dotenv
paramiko
anthropic
httpx
```

`httpx`를 명시 선언하는 이유: `anthropic` 1.x는 내부적으로 `httpx2`를 쓰므로 `httpx`가 자동으로 깔린다고 가정할 수 없다. 어댑터 호출(Task 5)이 `httpx`를 직접 쓴다.

`.env.example` 끝에 한 줄 추가한다:

```
ANTHROPIC_API_KEY=sk-ant-...
```

- [ ] **Step 6: 설치하고 임포트가 되는지 확인한다**

Run: `pip install -r requirements.txt -r requirements-dev.txt`
Run: `python -c "import orchestrator_llm; print(orchestrator_llm.MODEL)"`
Expected: `claude-opus-5` 출력

- [ ] **Step 7: 커밋한다**

```bash
git add orchestrator_llm.py tests/test_orchestrator_llm.py requirements.txt .env.example
git commit -m "오케스트레이터 LLM 클라이언트 추가 (claude-opus-5)"
```

---

### Task 4: 라우터

**Files:**
- Create: `orchestrator_router.py`
- Test: `tests/test_orchestrator_router.py`

**Interfaces:**
- Consumes: `orchestrator_llm.call_json(system, user, schema, max_tokens=..., client=...) -> dict`
- Produces: `orchestrator_router.ROUTE_SCHEMA: dict`, `build_catalog(agents: dict) -> str`, `route(question: str, agents: dict, call_json=orchestrator_llm.call_json) -> dict` — 반환은 항상 `{"picks": [{"agent": str, "reason": str}, ...], "none_reason": str | None}`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

```python
# tests/test_orchestrator_router.py
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
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `pytest tests/test_orchestrator_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator_router'`

- [ ] **Step 3: 최소 구현을 작성한다**

```python
# orchestrator_router.py
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
- picks가 비어 있지 않으면 none_reason은 null이다.
- agent 값은 반드시 목록에 있는 키를 그대로 쓴다.
- reason은 왜 그 에이전트를 골랐는지 한국어 한 문장으로 쓴다."""


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
```

- [ ] **Step 4: 테스트가 통과하는 것을 확인한다**

Run: `pytest tests/test_orchestrator_router.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: 커밋한다**

```bash
git add orchestrator_router.py tests/test_orchestrator_router.py
git commit -m "오케스트레이터 라우터 추가 — 레지스트리 기반 에이전트 선택"
```

---

### Task 5: 실행기

**Files:**
- Create: `orchestrator_executor.py`
- Test: `tests/test_orchestrator_executor.py`

**Interfaces:**
- Consumes: `orchestrator_registry.agent_url(entry, host, path)`
- Produces: `orchestrator_executor.AgentResult` (dataclass: `agent: str`, `ok: bool`, `answer: str`, `sufficient: bool`, `citations: list`, `grounding: dict`, `elapsed_ms: int`, `error: str`), `ask_agent(key, entry, question, chat_history, host, client) -> AgentResult`, `ask_agents(picks, agents, question, chat_history, host, client=None) -> list[AgentResult]`, `check_health(entry, host, client) -> dict`

`httpx.Client`를 인자로 받는다. 테스트는 `httpx.MockTransport`로 만든 클라이언트를 넘긴다 — 실제 네트워크를 쓰지 않는다.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

```python
# tests/test_orchestrator_executor.py
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
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `pytest tests/test_orchestrator_executor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator_executor'`

- [ ] **Step 3: 최소 구현을 작성한다**

```python
# orchestrator_executor.py
"""선택된 에이전트들을 병렬로 호출하고 결과를 모은다.

ThreadPoolExecutor를 쓴다. Streamlit은 동기 런타임이고 페이지 안에서
asyncio.run을 쓰면 이벤트 루프가 충돌한다.

실패는 격리한다 — 하나가 죽어도 나머지 답변은 살아서 와야 하고, 죽은 것은
결과 목록에 error가 채워진 항목으로 남아야 한다. 조용히 사라지면 사용자는
답변이 왜 부실한지 알 수 없다."""
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx

from orchestrator_registry import agent_url

DEFAULT_TIMEOUT_SEC = 60
MAX_PARALLEL = 5


@dataclass
class AgentResult:
    agent: str
    ok: bool
    answer: str = ""
    sufficient: bool = False
    citations: list = field(default_factory=list)
    grounding: dict = field(default_factory=dict)
    elapsed_ms: int = 0
    error: str = ""


def ask_agent(key: str, entry: dict, question: str, chat_history: list,
              host: str, client: httpx.Client) -> AgentResult:
    url = agent_url(entry, host, path="/ask")
    timeout = entry.get("timeout_sec") or DEFAULT_TIMEOUT_SEC
    started = time.monotonic()
    try:
        response = client.post(
            url,
            json={"question": question, "chat_history": chat_history},
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as e:
        return AgentResult(agent=key, ok=False, error=f"HTTP {e.response.status_code}",
                           elapsed_ms=_ms_since(started))
    except Exception as e:
        return AgentResult(agent=key, ok=False, error=f"{type(e).__name__}: {e}",
                           elapsed_ms=_ms_since(started))

    if not isinstance(body, dict):
        return AgentResult(agent=key, ok=False, error="응답이 JSON 객체가 아닙니다.",
                           elapsed_ms=_ms_since(started))

    return AgentResult(
        agent=key,
        ok=True,
        answer=body.get("answer") or "",
        sufficient=bool(body.get("sufficient")),
        citations=body.get("citations") or [],
        grounding=body.get("grounding") or {},
        elapsed_ms=int(body.get("elapsed_ms") or _ms_since(started)),
    )


def ask_agents(picks: list, agents: dict, question: str, chat_history: list,
               host: str, client: httpx.Client = None) -> list:
    targets = [(p["agent"], agents[p["agent"]]) for p in picks if p.get("agent") in agents]
    if not targets:
        return []

    owns_client = client is None
    client = client or httpx.Client()
    try:
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(targets))) as pool:
            futures = [
                pool.submit(ask_agent, key, entry, question, chat_history, host, client)
                for key, entry in targets
            ]
            return [f.result() for f in futures]
    finally:
        if owns_client:
            client.close()


def check_health(entry: dict, host: str, client: httpx.Client = None) -> dict:
    url = agent_url(entry, host, path="/health")
    owns_client = client is None
    client = client or httpx.Client()
    try:
        response = client.get(url, timeout=5)
        response.raise_for_status()
        body = response.json()
        return {"ok": bool(body.get("ok")),
                "corpus_counts": body.get("corpus_counts") or {},
                "error": ""}
    except Exception as e:
        return {"ok": False, "corpus_counts": {}, "error": f"{type(e).__name__}: {e}"}
    finally:
        if owns_client:
            client.close()


def _ms_since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
```

- [ ] **Step 4: 테스트가 통과하는 것을 확인한다**

Run: `pytest tests/test_orchestrator_executor.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: 커밋한다**

```bash
git add orchestrator_executor.py tests/test_orchestrator_executor.py
git commit -m "오케스트레이터 실행기 추가 — 병렬 호출 및 실패 격리"
```

---

### Task 6: 합성기

**Files:**
- Create: `orchestrator_synth.py`
- Test: `tests/test_orchestrator_synth.py`

**Interfaces:**
- Consumes: `orchestrator_executor.AgentResult`, `orchestrator_llm.call_text(system, user, max_tokens=..., client=...) -> str`
- Produces: `orchestrator_synth.citation_key(citation: dict) -> tuple`, `dedupe_citations(results: list) -> list`, `synthesize(question: str, results: list, labels: dict = None, call_text=orchestrator_llm.call_text) -> dict` — 반환은 `{"answer": str, "citations": list, "mode": str, "failed": list}`, `mode`는 `"all_failed"` / `"single"` / `"synth"` 중 하나

- [ ] **Step 1: 실패하는 테스트를 작성한다**

```python
# tests/test_orchestrator_synth.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator_synth as synth
from orchestrator_executor import AgentResult

LABELS = {"lex": "렉스", "policy": "폴리"}


def _law(law_name, article, text="조문 내용"):
    return {"type": "law", "law_name": law_name, "article": article, "text": text}


def _fake_call_text(reply, capture=None):
    def _call(system, user, max_tokens=16000, client=None):
        if capture is not None:
            capture.append({"system": system, "user": user})
        return reply
    return _call


def test_citation_key_uses_law_name_and_article():
    assert synth.citation_key(_law("개인정보보호법", "제15조")) == ("law", "개인정보보호법", "제15조")


def test_dedupe_citations_removes_same_law_and_article_across_agents():
    results = [
        AgentResult(agent="lex", ok=True, answer="a", citations=[_law("개인정보보호법", "제15조")]),
        AgentResult(agent="policy", ok=True, answer="b", citations=[_law("개인정보보호법", "제15조")]),
    ]
    assert len(synth.dedupe_citations(results)) == 1


def test_dedupe_citations_keeps_different_articles():
    results = [
        AgentResult(agent="lex", ok=True, answer="a",
                    citations=[_law("개인정보보호법", "제15조"), _law("개인정보보호법", "제17조")]),
    ]
    assert len(synth.dedupe_citations(results)) == 2


def test_dedupe_citations_ignores_failed_results():
    results = [
        AgentResult(agent="lex", ok=False, error="다운", citations=[_law("개인정보보호법", "제15조")]),
    ]
    assert synth.dedupe_citations(results) == []


def test_synthesize_all_failed_lists_reasons_and_does_not_call_llm():
    calls = []
    results = [
        AgentResult(agent="lex", ok=False, error="ConnectError: 연결 거부"),
        AgentResult(agent="policy", ok=False, error="HTTP 500"),
    ]
    out = synth.synthesize("질문", results, labels=LABELS,
                           call_text=_fake_call_text("불려선 안 됨", capture=calls))
    assert out["mode"] == "all_failed"
    assert calls == []
    assert "렉스" in out["answer"]
    assert "ConnectError: 연결 거부" in out["answer"]
    assert "HTTP 500" in out["answer"]
    assert out["citations"] == []


def test_synthesize_single_result_passes_through_without_llm():
    calls = []
    results = [AgentResult(agent="lex", ok=True, answer="렉스의 원본 답변",
                           citations=[_law("개인정보보호법", "제15조")])]
    out = synth.synthesize("질문", results, labels=LABELS,
                           call_text=_fake_call_text("합성하면 안 됨", capture=calls))
    assert out["mode"] == "single"
    assert calls == []
    assert out["answer"] == "렉스의 원본 답변"
    assert len(out["citations"]) == 1


def test_synthesize_two_results_calls_llm_and_returns_its_text():
    results = [
        AgentResult(agent="lex", ok=True, answer="렉스 답변"),
        AgentResult(agent="policy", ok=True, answer="폴리 답변"),
    ]
    out = synth.synthesize("질문", results, labels=LABELS,
                           call_text=_fake_call_text("합성된 답변"))
    assert out["mode"] == "synth"
    assert out["answer"] == "합성된 답변"


def test_synthesize_prompt_labels_each_answer_with_agent_name():
    calls = []
    results = [
        AgentResult(agent="lex", ok=True, answer="렉스 답변"),
        AgentResult(agent="policy", ok=True, answer="폴리 답변"),
    ]
    synth.synthesize("질문", results, labels=LABELS,
                     call_text=_fake_call_text("합성", capture=calls))
    user = calls[0]["user"]
    assert "렉스" in user and "렉스 답변" in user
    assert "폴리" in user and "폴리 답변" in user


def test_synthesize_prompt_marks_insufficient_grounding():
    calls = []
    results = [
        AgentResult(agent="lex", ok=True, answer="근거 있음", sufficient=True),
        AgentResult(agent="policy", ok=True, answer="근거 없음", sufficient=False),
    ]
    synth.synthesize("질문", results, labels=LABELS,
                     call_text=_fake_call_text("합성", capture=calls))
    assert "근거 부족" in calls[0]["user"]


def test_synthesize_system_prompt_forbids_merging_conflicts():
    calls = []
    results = [
        AgentResult(agent="lex", ok=True, answer="A라고 본다"),
        AgentResult(agent="policy", ok=True, answer="B라고 본다"),
    ]
    synth.synthesize("질문", results, labels=LABELS,
                     call_text=_fake_call_text("합성", capture=calls))
    assert "병기" in calls[0]["system"]


def test_synthesize_reports_partial_failures_alongside_synthesis():
    results = [
        AgentResult(agent="lex", ok=True, answer="렉스 답변"),
        AgentResult(agent="policy", ok=True, answer="폴리 답변"),
    ]
    results.append(AgentResult(agent="radar", ok=False, error="HTTP 502"))
    out = synth.synthesize("질문", results, labels=LABELS,
                           call_text=_fake_call_text("합성된 답변"))
    assert out["mode"] == "synth"
    assert out["failed"] == [{"agent": "radar", "error": "HTTP 502"}]


def test_synthesize_empty_results_is_all_failed():
    out = synth.synthesize("질문", [], labels=LABELS, call_text=_fake_call_text("x"))
    assert out["mode"] == "all_failed"


def test_synthesize_falls_back_to_agent_key_when_label_missing():
    calls = []
    results = [
        AgentResult(agent="lex", ok=True, answer="렉스 답변"),
        AgentResult(agent="unknown", ok=True, answer="미등록 답변"),
    ]
    synth.synthesize("질문", results, labels=LABELS,
                     call_text=_fake_call_text("합성", capture=calls))
    assert "unknown" in calls[0]["user"]
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `pytest tests/test_orchestrator_synth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator_synth'`

- [ ] **Step 3: 최소 구현을 작성한다**

```python
# orchestrator_synth.py
"""여러 에이전트 답변을 하나로 합친다.

성공 결과가 1개일 때는 LLM을 태우지 않고 원문을 그대로 통과시킨다. 토큰
절약이 아니라 왜곡 방지다 — 답변 하나를 다시 LLM에 넣으면 원문이 바뀐다.

전부 실패했을 때 일반 지식으로 답하지 않는다. 근거 없는 답변이 근거 있는
답변처럼 보이게 된다."""
import orchestrator_llm

SYSTEM = """너는 사내 AI 에이전트 오케스트레이터의 합성기다.
여러 전문 에이전트가 같은 질문에 각각 답했다. 그것들을 하나의 답변으로 합쳐라.

규칙:
- 각 주장이 어느 에이전트에서 나왔는지 밝혀라. 출처 없는 문장을 만들지 마라.
- 에이전트들이 서로 다르게 말하면 하나로 뭉개지 말고 양쪽을 병기하고, 다르다는 사실을 명시하라.
- "근거 부족"으로 표시된 답변은 근거를 제대로 찾지 못한 것이다. 조문·자료를 짚은 답변과 같은 무게로 섞지 말고, 참고 수준으로만 쓰고 그렇다고 밝혀라.
- 주어진 답변에 없는 내용을 네 지식으로 채우지 마라.
- 한국어로, 질문에 바로 답하는 것으로 시작하라."""


def citation_key(citation: dict) -> tuple:
    return (
        citation.get("type", ""),
        citation.get("law_name", ""),
        citation.get("article", ""),
    )


def dedupe_citations(results: list) -> list:
    """법령명+조번호가 같은 인용을 하나로 합친다.

    폴리의 법령 코퍼스는 렉스에서 옮겨온 것(poly_vectordb.migrate_from_lexagent)
    이므로 두 에이전트가 같은 조항을 인용해 돌려주는 것이 정상이다."""
    seen, merged = set(), []
    for result in results:
        if not result.ok:
            continue
        for citation in result.citations:
            key = citation_key(citation)
            if key in seen:
                continue
            seen.add(key)
            merged.append(citation)
    return merged


def _label(agent: str, labels: dict) -> str:
    return (labels or {}).get(agent) or agent


def synthesize(question: str, results: list, labels: dict = None,
               call_text=orchestrator_llm.call_text) -> dict:
    ok_results = [r for r in results if r.ok]
    failed = [{"agent": r.agent, "error": r.error} for r in results if not r.ok]

    if not ok_results:
        lines = ["모든 에이전트가 응답하지 못했습니다.", ""]
        for item in failed:
            lines.append(f"- {_label(item['agent'], labels)}: {item['error']}")
        return {"answer": "\n".join(lines), "citations": [], "mode": "all_failed",
                "failed": failed}

    if len(ok_results) == 1:
        only = ok_results[0]
        return {"answer": only.answer, "citations": dedupe_citations(ok_results),
                "mode": "single", "failed": failed}

    blocks = []
    for result in ok_results:
        mark = "" if result.sufficient else " (근거 부족)"
        blocks.append(f"[{_label(result.agent, labels)}{mark}]\n{result.answer}")

    user = f"[사용자 질문]\n{question}\n\n[에이전트 답변들]\n" + "\n\n".join(blocks)
    return {"answer": call_text(SYSTEM, user), "citations": dedupe_citations(ok_results),
            "mode": "synth", "failed": failed}
```

- [ ] **Step 4: 테스트가 통과하는 것을 확인한다**

Run: `pytest tests/test_orchestrator_synth.py -v`
Expected: PASS (13 passed)

- [ ] **Step 5: 전체 테스트를 돌린다**

Run: `pytest`
Expected: PASS — 기존 `test_visibility_config.py` 10개를 포함해 전부 통과

- [ ] **Step 6: 커밋한다**

```bash
git add orchestrator_synth.py tests/test_orchestrator_synth.py
git commit -m "오케스트레이터 합성기 추가 — 인용 중복 제거 및 단일 결과 통과"
```

---

### Task 7: UI 페이지와 네비게이션 게이팅

**Files:**
- Create: `pages/오케스트레이터.py`
- Modify: `app.py:70-76`
- Test: 수동 확인 (Streamlit 페이지는 자동 테스트 범위 밖 — 로직은 Task 2-6에서 이미 덮였다)

**Interfaces:**
- Consumes: `agent_host.agent_host()`, `orchestrator_registry.load_registry/enabled_agents`, `orchestrator_router.route`, `orchestrator_executor.ask_agents/check_health`, `orchestrator_synth.synthesize`, `access_control.is_admin`
- Produces: 없음 (최종 소비자)

- [ ] **Step 1: 페이지를 작성한다**

```python
# pages/오케스트레이터.py
import streamlit as st

from access_control import is_admin
from agent_host import agent_host
from agents_data import AGENTS
from orchestrator_registry import load_registry, enabled_agents
from orchestrator_router import route
from orchestrator_executor import ask_agents, check_health
from orchestrator_synth import synthesize

_client_ip = st.session_state.get("_client_ip", "")
if not is_admin(_client_ip):
    st.error("이 페이지는 관리자만 사용할 수 있습니다.")
    st.stop()

st.title("🎛️ 오케스트레이터")
st.caption("질문 하나로 관련 에이전트들을 골라 부르고, 답변을 하나로 합칩니다.")

_registry = load_registry()
_agents = enabled_agents(_registry)
_host = agent_host()

# 카드 아이콘·닉네임 재사용 — agents_data.py의 name과 레지스트리의 agent_name을 연결한다.
_meta = {a["name"]: a for a in AGENTS}
_labels = {
    key: f"{_meta.get(e['agent_name'], {}).get('icon', '')} "
         f"{_meta.get(e['agent_name'], {}).get('nickname', e['agent_name'])}".strip()
    for key, e in _agents.items()
}

if not _agents:
    st.warning(
        "연결된 에이전트가 없습니다. `data/orchestrator_registry.json`에서 "
        "어댑터가 준비된 에이전트의 `enabled`를 true로 바꿔주세요."
    )
    st.stop()

with st.expander(f"연결된 에이전트 {len(_agents)}개 · 상태 확인", expanded=False):
    st.write(", ".join(_labels.values()))
    if st.button("헬스체크 실행"):
        for key, entry in _agents.items():
            health = check_health(entry, _host)
            if health["ok"]:
                counts = ", ".join(f"{k} {v}" for k, v in health["corpus_counts"].items())
                st.success(f"{_labels[key]} · 정상 {'· ' + counts if counts else ''}")
            else:
                st.error(f"{_labels[key]} · 실패 — {health['error']}")

if "orch_messages" not in st.session_state:
    st.session_state["orch_messages"] = []

for msg in st.session_state["orch_messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

_question = st.chat_input("질문을 입력하세요")

if _question:
    st.session_state["orch_messages"].append({"role": "user", "content": _question})
    with st.chat_message("user"):
        st.markdown(_question)

    history = st.session_state["orch_messages"][:-1]

    with st.chat_message("assistant"):
        with st.spinner("어느 에이전트가 담당인지 판단하는 중..."):
            decision = route(_question, _agents)

        if not decision["picks"]:
            st.info(decision["none_reason"])
            st.caption("연결된 에이전트: " + ", ".join(_labels.values()))
            st.session_state["orch_messages"].append(
                {"role": "assistant", "content": decision["none_reason"]}
            )
            st.stop()

        picked = ", ".join(_labels.get(p["agent"], p["agent"]) for p in decision["picks"])
        with st.spinner(f"{picked} 호출 중..."):
            results = ask_agents(decision["picks"], _agents, _question, history, _host)

        with st.spinner("답변을 합치는 중..."):
            out = synthesize(_question, results, labels=_labels)

        st.markdown(out["answer"])

        # 라우팅을 블랙박스로 두지 않는다 — 왜 그 에이전트를 불렀는지 항상 보여준다.
        with st.expander("이 답변이 만들어진 경로", expanded=False):
            st.markdown("**호출한 에이전트와 이유**")
            for pick in decision["picks"]:
                st.markdown(f"- {_labels.get(pick['agent'], pick['agent'])}: {pick['reason']}")

            if out["failed"]:
                st.markdown("**응답하지 못한 에이전트**")
                for item in out["failed"]:
                    st.markdown(f"- {_labels.get(item['agent'], item['agent'])}: {item['error']}")

            st.markdown("**각 에이전트의 원본 답변**")
            for result in results:
                if not result.ok:
                    continue
                label = _labels.get(result.agent, result.agent)
                mark = "" if result.sufficient else " · 근거 부족"
                st.markdown(f"**{label}**{mark} · {result.elapsed_ms}ms")
                st.markdown(result.answer)
                if result.grounding:
                    st.caption(f"근거: {result.grounding}")

        if out["citations"]:
            with st.expander(f"인용 {len(out['citations'])}건", expanded=False):
                for citation in out["citations"]:
                    label = " ".join(
                        str(citation.get(f, "")) for f in ("law_name", "article")
                    ).strip()
                    st.markdown(f"- **{label or citation.get('type', '')}** {citation.get('text', '')}")

    st.session_state["orch_messages"].append({"role": "assistant", "content": out["answer"]})
```

- [ ] **Step 2: `app.py`에 네비게이션 항목을 추가한다**

`app.py`에서 이 블록을 찾는다:

```python
_pages = [st.Page("pages/포털.py", title="포털", icon="🏢")]
if is_admin(_client_ip):
    _pages.append(st.Page("pages/설정.py", title="설정", icon="⚙️"))
    _pages.append(st.Page("pages/로그.py", title="로그", icon="🧾"))
```

이것으로 교체한다:

```python
_pages = [st.Page("pages/포털.py", title="포털", icon="🏢")]
if is_admin(_client_ip):
    _pages.append(st.Page("pages/오케스트레이터.py", title="오케스트레이터", icon="🎛️"))
    _pages.append(st.Page("pages/설정.py", title="설정", icon="⚙️"))
    _pages.append(st.Page("pages/로그.py", title="로그", icon="🧾"))
```

- [ ] **Step 3: 에이전트 0개 상태에서 페이지가 뜨는지 확인한다**

Task 2에서 만든 레지스트리는 4개 모두 `enabled: false`이므로, 이 시점에는 안내 문구가 나오는 것이 정상 동작이다.

Run: `python -m streamlit run app.py --server.address 192.168.14.222 --server.port 9000`
Expected: 사이드바에 "🎛️ 오케스트레이터"가 보이고, 페이지를 열면 "연결된 에이전트가 없습니다" 경고가 나온다. `st.stop()` 아래 코드는 실행되지 않는다.

- [ ] **Step 4: 페이크 어댑터로 종단 동작을 확인한다**

임시 스텁 어댑터를 띄워 라우터→실행기→합성기 경로를 실제로 통과시킨다. 이 파일은 커밋하지 않는다.

스크래치 디렉터리에 `stub_adapter.py`를 만든다:

```python
# 임시 검증용 — 커밋하지 않는다.
import sys
from fastapi import FastAPI
import uvicorn

NAME = sys.argv[1]
PORT = int(sys.argv[2])
app = FastAPI()


@app.post("/ask")
def ask(body: dict):
    return {
        "answer": f"{NAME} 스텁 답변: {body.get('question', '')}",
        "sufficient": True,
        "citations": [{"type": "law", "law_name": "개인정보보호법",
                       "article": "제15조", "text": "스텁 조문"}],
        "grounding": {"stub": True},
        "agent": NAME,
        "elapsed_ms": 10,
    }


@app.get("/health")
def health():
    return {"ok": True, "corpus_counts": {"laws": 1}}


uvicorn.run(app, host="192.168.14.222", port=PORT)
```

Run: `pip install fastapi uvicorn`
두 개의 별도 터미널에서:
Run: `python stub_adapter.py LexAgent 9501`
Run: `python stub_adapter.py PolicyAgent 9502`

`data/orchestrator_registry.json`에서 `lex`와 `policy`의 `enabled`를 `true`로 바꾼다.

앱을 띄우고 오케스트레이터 페이지에서 "개인정보 처리방침 개정할 때 반영할 법령이 있나?"를 입력한다.
Expected:
- 라우터가 lex·policy 둘 다 고른다 (하나만 골라도 정상 — 그 경우 `mode`가 `single`이 되어 원문이 그대로 나온다)
- 두 개가 선택됐다면 합성된 답변이 상단에 나오고, "이 답변이 만들어진 경로"에 호출 이유와 각 원본 답변이 보인다
- "인용 1건" — 두 스텁이 같은 조항을 돌려주므로 dedupe가 동작해 2건이 아니라 1건이어야 한다

`enabled`를 다시 `false`로 되돌리고, 스텁 프로세스를 종료하고, `stub_adapter.py`를 삭제한다.

- [ ] **Step 5: 커밋한다**

```bash
git add pages/오케스트레이터.py app.py
git commit -m "오케스트레이터 UI 페이지 추가 (admin 전용)"
```

---

### Task 8: 런처와 배포 화이트리스트

**Files:**
- Create: `scripts/start_adapters.ps1`
- Create: `scripts/start_adapters.sh`
- Modify: `pages/설정.py:149-153`
- Test: 수동 확인

**Interfaces:**
- Consumes: `data/orchestrator_registry.json`
- Produces: 없음

- [ ] **Step 1: 배포 업로드에 레지스트리 파일을 추가한다**

현재 배포는 `data/` 전체를 올리지 않고 `visibility_config.json`만 개별 업로드한다. 레지스트리 파일을 추가하지 않으면 배포 서버에서 조용히 빈 상태가 된다.

`pages/설정.py`에서 이 블록을 찾는다:

```python
        _vis_local = ROOT / "data" / "visibility_config.json"
        if _vis_local.exists():
            _sftp_mkdir_p(sftp, f"{_DEPLOY_REMOTE}/data")
            sftp.put(str(_vis_local), f"{_DEPLOY_REMOTE}/data/visibility_config.json")
            log("↑ data/visibility_config.json")
```

이것으로 교체한다:

```python
        # data/ 전체는 올리지 않는다 — 배포 서버의 access_config.json을 로컬 IP로
        # 덮어써 실제 사용자를 잠가버린다. 로컬이 원본인 파일만 개별 업로드한다.
        for _name in ("visibility_config.json", "orchestrator_registry.json"):
            _local = ROOT / "data" / _name
            if _local.exists():
                _sftp_mkdir_p(sftp, f"{_DEPLOY_REMOTE}/data")
                sftp.put(str(_local), f"{_DEPLOY_REMOTE}/data/{_name}")
                log(f"↑ data/{_name}")
```

- [ ] **Step 2: 로컬 런처를 작성한다**

`scripts/start_adapters.ps1`. 레지스트리를 읽어 `enabled` 항목의 어댑터를 각 리포의 venv 파이썬으로 띄운다. 리포 경로와 venv 경로는 리포마다 다르므로 스크립트 상단 매핑에 둔다.

```powershell
# 하위 에이전트 어댑터 일괄 실행 (로컬)
# 사용법: powershell -ExecutionPolicy Bypass -File scripts\start_adapters.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$registryPath = Join-Path $root "data\orchestrator_registry.json"

if (-not (Test-Path $registryPath)) {
    Write-Error "레지스트리가 없습니다: $registryPath"
}

# 레지스트리 키 -> (리포 경로, venv 파이썬 상대경로 또는 $null)
# 조사 결과 venv를 가진 리포는 렉스(lex-env)뿐이고, 폴리·프니·에리는 시스템
# 파이썬으로 돌고 있다. venv 경로가 $null이거나 실제로 없으면 시스템 python으로
# 폴백한다 — venv를 전제하면 3개가 전부 건너뛰어진다.
$repos = @{
    "lex"    = @("C:\Users\USER\Desktop\Project Agent\LexAgent",   "lex-env\Scripts\python.exe")
    "policy" = @("C:\Users\USER\Desktop\Project Agent\PolicyAgent", $null)
    "hana"   = @("C:\Users\USER\Desktop\Project Agent\hana_p",      $null)
    "radar"  = @("C:\Users\USER\Desktop\Project Agent\AiAxRadar",   $null)
}

$registry = Get-Content $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json

foreach ($key in $repos.Keys) {
    $entry = $registry.$key
    if ($null -eq $entry) { Write-Host "- $key : 레지스트리에 없음, 건너뜀"; continue }
    if (-not $entry.enabled) { Write-Host "- $key : enabled=false, 건너뜀"; continue }

    $repoPath = $repos[$key][0]
    $venvRel = $repos[$key][1]
    $apiPath = Join-Path $repoPath "api.py"

    if ($null -ne $venvRel -and (Test-Path (Join-Path $repoPath $venvRel))) {
        $python = Join-Path $repoPath $venvRel
    } else {
        $python = "python"
        Write-Host "  ($key : venv 없음 -> 시스템 python 사용)"
    }

    if (-not (Test-Path $apiPath)) { Write-Host "! $key : api.py 없음 ($apiPath)"; continue }

    Write-Host "+ $key : 포트 $($entry.api_port) 로 시작"
    Start-Process -FilePath $python `
        -ArgumentList @($apiPath, "--host", "192.168.14.222", "--port", "$($entry.api_port)") `
        -WorkingDirectory $repoPath
}

Write-Host ""
Write-Host "어댑터 상태는 오케스트레이터 페이지의 '헬스체크 실행'으로 확인하세요."
```

venv 현황은 확인해서 위 매핑에 이미 반영했다 — 렉스만 `lex-env`를 갖고 있고 나머지 셋은 시스템 파이썬으로 돈다. 나중에 어느 리포에 venv가 생기면 `$null`을 그 상대경로로 바꾸면 된다.

- [ ] **Step 3: 배포 런처를 작성한다**

`scripts/start_adapters.sh`. 어댑터는 AgentPortal 배포 플로우가 손대지 않는 다른 리포에 있으므로, 이 스크립트는 배포 서버에 각 리포가 이미 배치돼 있다는 전제로 동작한다. 리포 배치 자체는 이 계획 범위 밖이다.

```bash
#!/usr/bin/env bash
# 하위 에이전트 어댑터 일괄 실행 (배포 서버)
# 사용법: bash scripts/start_adapters.sh
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGISTRY="$ROOT/data/orchestrator_registry.json"
HOST="192.168.10.169"
BASE="${ADAPTER_REPO_BASE:-$HOME}"

if [ ! -f "$REGISTRY" ]; then
    echo "레지스트리가 없습니다: $REGISTRY" >&2
    exit 1
fi

# 레지스트리 키:리포 디렉터리명
for pair in "lex:LexAgent" "policy:PolicyAgent" "hana:hana_p" "radar:AiAxRadar"; do
    key="${pair%%:*}"
    repo="${pair##*:}"

    enabled=$(python3 -c "import json,sys;r=json.load(open('$REGISTRY',encoding='utf-8'));print(r.get('$key',{}).get('enabled',False))")
    if [ "$enabled" != "True" ]; then
        echo "- $key : enabled=false, 건너뜀"
        continue
    fi

    port=$(python3 -c "import json;r=json.load(open('$REGISTRY',encoding='utf-8'));print(r['$key']['api_port'])")
    repo_path="$BASE/$repo"

    # venv가 있으면 그것을, 없으면 시스템 python3을 쓴다 — 로컬에서도 venv를
    # 가진 리포는 렉스뿐이었고, 배포 서버도 리포마다 다를 수 있다.
    if [ -x "$repo_path/venv/bin/python" ]; then
        python_bin="$repo_path/venv/bin/python"
    else
        python_bin="python3"
        echo "  ($key : venv 없음 -> 시스템 python3 사용)"
    fi

    if [ ! -f "$repo_path/api.py" ]; then echo "! $key : api.py 없음"; continue; fi

    echo "+ $key : 포트 $port 로 시작"
    (cd "$repo_path" && nohup "$python_bin" api.py --host "$HOST" --port "$port" \
        > "$repo_path/adapter.log" 2>&1 &)
done

echo ""
echo "어댑터 상태는 오케스트레이터 페이지의 '헬스체크 실행'으로 확인하세요."
```

- [ ] **Step 4: 런처가 enabled=false를 건너뛰는지 확인한다**

이 시점에는 어댑터 `api.py`가 아직 없으므로, 레지스트리가 전부 `enabled: false`인 상태에서 전부 건너뛰는 것이 정상 동작이다.

Run: `powershell -ExecutionPolicy Bypass -File scripts/start_adapters.ps1`
Expected: 4개 모두 "enabled=false, 건너뜀"이 출력되고 프로세스가 하나도 뜨지 않는다.

- [ ] **Step 5: 전체 테스트를 돌린다**

Run: `pytest`
Expected: PASS — 전부 통과 (Task 8은 테스트 대상 로직을 추가하지 않는다)

- [ ] **Step 6: 커밋한다**

```bash
git add scripts/start_adapters.ps1 scripts/start_adapters.sh pages/설정.py
git commit -m "어댑터 런처 스크립트 및 레지스트리 배포 업로드 추가"
```

---

## 이 계획이 끝난 뒤의 상태

- 오케스트레이터 코어 4개 모듈 + UI가 동작하고, 페이크/스텁 어댑터로 종단 검증됨
- 레지스트리 4개 항목이 `enabled: false`로 대기 — 어댑터가 준비되는 대로 하나씩 `true`
- 실제 어댑터는 아직 없음. 다음 계획(`어댑터 4개`)에서 리포별로 만든다
- 삼일(`tax`)은 레지스트리에 아직 없음. `chat_answer` 신규 구현 계획에서 항목까지 함께 추가한다

## 후속 계획 (별도 문서)

1. **어댑터 4개** — 렉스·폴리(껍데기), 프니·에리(뷰 로직 추출). 리포별 독립, 병렬 진행 가능
2. **삼일 `chat_answer`** — ProptierAI에 없던 단독 질의 기능 신규 구현 후 어댑터 + 레지스트리 항목 추가
