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

    # 여기부터는 200 응답을 받은 뒤 계약대로 정리하는 것뿐이지만, 어댑터가
    # 계약을 어긴 필드를 보낼 수 있다 (예: elapsed_ms에 "12ms"). 하나라도
    # 실패해서 예외가 새 나가면 ThreadPoolExecutor의 f.result()가 그것을
    # 재발생시켜 이 결과 하나 때문에 나머지 정상 에이전트들의 결과까지
    # 전부 날아간다 — 그래서 이 아래는 예외를 던지지 않는다.
    try:
        answer = body.get("answer")
        answer = answer if isinstance(answer, str) else ""

        sufficient = bool(body.get("sufficient"))

        raw_citations = body.get("citations")
        citations = ([c for c in raw_citations if isinstance(c, dict)]
                     if isinstance(raw_citations, list) else [])

        raw_grounding = body.get("grounding")
        grounding = raw_grounding if isinstance(raw_grounding, dict) else {}

        raw_elapsed = body.get("elapsed_ms")
        try:
            elapsed_ms = int(raw_elapsed) if raw_elapsed is not None else _ms_since(started)
        except (TypeError, ValueError):
            elapsed_ms = _ms_since(started)

        return AgentResult(
            agent=key,
            ok=True,
            answer=answer,
            sufficient=sufficient,
            citations=citations,
            grounding=grounding,
            elapsed_ms=elapsed_ms,
        )
    except Exception as e:
        return AgentResult(agent=key, ok=False, error=f"응답 형식 오류: {type(e).__name__}: {e}",
                           elapsed_ms=_ms_since(started))


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
