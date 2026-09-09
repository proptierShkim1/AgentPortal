# 상위 오케스트레이터 — 설계

## 배경 및 목적

현재 포털은 에이전트 카드 11개를 나열하고, 사용자가 직접 하나를 골라 들어간다. 사용자가 자기 질문이 어느 에이전트 담당인지 미리 알고 있어야 하고, 두 에이전트에 걸치는 질문은 사람이 양쪽을 각각 들어가서 머리로 합쳐야 한다.

성환님 요구사항: 상위에 오케스트레이터를 두고, 역할을 구분해서 하위 에이전트들의 답변을 상황에 맞게 받고 싶다. 결과물은 라우팅 안내가 아니라 **통합 답변(합성)** 이다 — 오케스트레이터가 관련 에이전트를 골라 호출하고, 받은 답변들을 하나로 합성해서 내놓는다.

전형적인 목표 질문: *"처리방침 개정할 때 최근 법령 중 반영해야 할 게 있나?"* → 폴리가 처리방침 관점을, 렉스가 근거 법령을 대고, 하나로 합성된다.

## 조사 결과 — 하위 에이전트 현황

하위 에이전트에는 **호출 가능한 API가 하나도 없다.** 11개 전부 순수 Streamlit UI다 (FastAPI/Flask grep 결과는 전부 `site-packages` 내부 라이브러리였다). 따라서 창구를 새로 만들어야 한다.

대상 5개의 단독 질의 진입점 현황:

| 에이전트 | 진입점 | 반환 | 인용 | LLM | 저장소 |
|---|---|---|---|---|---|
| 렉스 (LexAgent) | `analyze.chat_answer(question, chat_history)` | 3-튜플 | O | anthropic (+gemini fallback) | Qdrant |
| 폴리 (PolicyAgent) | `poly_lawcase.chat_answer(question, chat_history)` | 3-튜플 | O | anthropic | Qdrant |
| 프니 (hana_p) | `agent_chat.ask(history, message, context="")` | str | X | google-genai | SQLite + 벡터 |
| 에리 (AiAxRadar) | `pipeline/agent_chat.ask(history, message, context, stats, tools, ...)` | str | X | google-genai | SQLite |
| 삼일 (ProptierAI) | **라이브 경로 없음** | — | — | anthropic | Qdrant |

### 어댑터가 균일하게 얇지 않다 — 3개 티어

| 티어 | 에이전트 | 작업 |
|---|---|---|
| 1 · 껍데기 | 렉스, 폴리 | `chat_answer`를 그대로 호출. 계약이 글자까지 동일 |
| 2 · 뷰 로직 추출 | 프니(약 5줄), 에리(약 45줄) | 답변 조립이 Streamlit 뷰 안에 있음 → 리포 안에서 서비스 함수로 추출 후 호출 |
| 3 · 신규 구현 | 삼일 | 라이브 단독 질의 경로가 없음. `chat_answer` 신규 작성 |

프니는 `views/agent.py:102-113`에서 UI가 그라운딩을 조립한다 (`vectorizer.search_similar_mentions` → `search_similar_policy_events` → `build_grounding_context` → `ask`). 에리는 `app/views/agent.py:495-541`에서 더 무겁게 조립한다 (`agent_router.classify` → `plan_for` → `rerank_hits` → `build_grounding_context` → `_today_stats_note` → `conn` 바인딩 도구 클로저 → `ask`).

삼일의 `rag/query.py:56 analyze(query, top_k)`는 단독 질의 함수처럼 보이지만 **아무도 import하지 않는 죽은 코드**다 (`from rag`/`import rag` grep 0건). 모델을 `claude-sonnet-4-6`으로 박아두고 라이브 앱과 다른 자체 SYSTEM_PROMPT를 갖고 있어, 여기에 붙이면 오케스트레이터만 아무도 유지·테스트하지 않는 프롬프트로 답하게 된다. 사용하지 않는다.

### 계약을 어려운 쪽에서 뽑는다

단계를 나눠 쉬운 에이전트부터 붙이지 않는다. 어댑터는 리포별 독립 작업이라 순서로 싸지는 것이 없고, 단계론이 지키려던 유일한 실익("계약이 틀렸을 때 5개를 다시 안 고치기")은 **가장 어려운 에이전트(에리)로 계약을 설계하면** 얻어진다. 에리에 맞는 계약이면 렉스는 자동으로 맞고, 반대는 성립하지 않는다.

이 판단의 근거: 프니와 에리는 둘 다 `is_grounding_sufficient(...)`를 계산한다 — "근거를 제대로 못 찾았다"는 자기 신고다. 렉스·폴리에는 이 개념이 아예 없다. 쉬운 쌍에서 계약을 뽑았다면 이 필드가 계약에 없었을 것이고, 합성기는 근거 없이 일반 지식으로 답한 것과 조문을 짚어 답한 것을 같은 무게로 섞었을 것이다.

## 어댑터 계약

각 에이전트 리포에 `api.py` 하나 (FastAPI + uvicorn, 포트는 인자/환경변수). 노출하는 것은 두 개뿐이다.

```
POST /ask     {question, chat_history?}
           →  {answer, sufficient, citations[]?, grounding{}, agent, elapsed_ms}

GET  /health  →  {ok, corpus_counts{}}
```

- `answer` — 답변 본문
- `sufficient` — 에이전트가 근거를 충분히 찾았는지 자기 신고. 프니·에리는 `is_grounding_sufficient` 값 그대로, 렉스·폴리는 인용 유무로 채운다
- `citations[]` — 구조화된 근거. 렉스·폴리만 채우고 나머지는 생략(옵셔널)
- `grounding{}` — 무엇으로 답을 뒷받침했는지. 에리는 `tool_call_log` + 카테고리, 프니는 벡터 히트 수, 렉스·폴리는 조문·심결례 건수. 자유 형식이라 에이전트마다 다른 것을 담아도 계약이 깨지지 않는다

`/health`가 `corpus_counts`를 함께 주는 이유: 헬스체크가 프로세스 생존만 보면 **빈 Qdrant를 붙들고 정상이라 답하는 상태**를 잡지 못한다.

에리 내부 파라미터(`tools`, `stats`, `tool_grounded`)는 계약에 올리지 않는다. 어댑터가 리포 안에서 감춰야 하는 것이고, 밖으로 새면 오케스트레이터가 에리 내부를 알게 된다.

`/capability`(에이전트가 자기 역할을 스스로 설명)는 검토 후 제외했다. 라우팅 기준이 두 곳에 생겨 갈라진다. 역할 정의는 레지스트리 한 곳에만 둔다.

### 프니·에리 추출의 필수 조건

추출 후 **기존 뷰가 같은 서비스 함수를 호출하도록 바꾼다.** 로직을 어댑터에 베껴 쓰면 같은 로직이 두 곳에 살고, 뷰를 고칠 때 어댑터가 조용히 뒤처진다. 따라서 이것은 순수 리팩터링이며, 기존 UI 동작이 바뀌지 않았다는 특성화 테스트가 함께 필요하다.

각 리포 `requirements.txt`에 `fastapi`, `uvicorn` 추가.

## 레지스트리 — `data/orchestrator_registry.json` (신규)

`visibility_config.py` 패턴을 그대로 따른다 — JSON 로드/저장 + 순수 변환 함수.

```json
{
  "lex": {
    "agent_name": "LexAgent",
    "role": "개인정보 법령 해석",
    "domain": ["개인정보보호법", "시행령", "고시", "심결례"],
    "when_to_use": "법 조항의 의미·요건·위반 여부를 물을 때",
    "when_not_to_use": "특정 회사의 처리방침 문서 검토 → policy로",
    "api_port": 9501,
    "timeout_sec": 60,
    "enabled": true
  }
}
```

`agent_name`은 `agents_data.py`의 `name`과 연결된다 (카드 아이콘·색상 재사용).

이 스키마의 핵심은 `when_to_use` / `when_not_to_use`다. **LLM 라우터가 읽는 것은 코드가 아니라 이 두 필드**이고, "역할을 구분해서"가 실제로 사는 곳이 여기다. 에이전트 추가가 항목 1줄인 이유도 이것이다.

레지스트리 키와 포트. 포트 규칙은 `에이전트 포트 + 500`:

| 레지스트리 키 | 에이전트 | `agent_name` | 앱 포트 | 어댑터 포트 |
|---|---|---|---|---|
| `lex` | 렉스 | `LexAgent` | 9001 | 9501 |
| `policy` | 폴리 | `PolicyAgent` | 9002 | 9502 |
| `hana` | 프니 | `Proptier AI News` | 7000 | 7500 |
| `radar` | 에리 | `AI RADAR` | 4001 | 4501 |
| `tax` | 삼일 | `AIpartner(세무)` | 9101 | 9601 |

기존 사용 포트(9001·9002·9003·3010·1001·2001·9101·3100·7000·7001·4001)와 충돌하지 않음을 확인했다. 규칙으로 유도되지만 레지스트리에 명시도 해둔다 — 운영 중에는 유도보다 명시가 낫다.

## 모듈 배치

이 프로젝트는 루트 평면 모듈 관례다 (`access_control.py`, `visibility_config.py`, `access_log.py`, `agents_data.py`). `orchestrator/` 패키지를 만들지 않고 루트에 놓는다.

```
orchestrator_registry.py    ← 레지스트리 로드/검증
orchestrator_router.py      ← 어느 에이전트를 부를지 결정
orchestrator_executor.py    ← 병렬 호출 + 실패 격리
orchestrator_synth.py       ← 답변 합성
pages/오케스트레이터.py       ← UI (admin 전용)
data/orchestrator_registry.json
```

관례를 따르는 것은 취향 문제가 아니다 — **`설정.py`의 배포 플로우가 루트 파일과 `.streamlit`/`scripts`/`pages`만 올린다.** 새 패키지 디렉터리를 만들면 배포 때 조용히 빠진다.

## 라우터 — `orchestrator_router.py`

입력은 질문 + 레지스트리, 출력은 호출할 에이전트 목록(0개 이상)과 각각의 선택 이유.

```python
{"picks": [{"agent": "lex", "reason": "..."}], "none_reason": None}
```

LLM 툴 정의 방식이 아니라 **JSON 한 번 반환**으로 간다. 결정적이고, 페이크로 테스트하기 쉽고, 0개·1개·N개를 같은 자료구조로 표현한다. 라우터가 읽는 것은 레지스트리의 `role`/`when_to_use`/`when_not_to_use`뿐이다.

**0개를 반드시 표현할 수 있어야 한다.** "회의실 예약 어떻게 해?"에 4개를 다 부르면 노이즈와 토큰만 쓴다. `none_reason`을 채워 "이 질문에 맞는 에이전트가 없습니다 + 현재 붙은 에이전트 목록"으로 답한다.

에리는 `agent_router.classify`로 이미 내부 라우팅을 한다. 오케스트레이터 라우터는 **그 위에서 에이전트 선택만 하고, 에리 내부 라우팅은 그대로 통과시킨다** — 밖에서 무력화하면 에리가 쌓아둔 카테고리별 계획을 버리게 된다.

규칙 기반 사전 분류(에리의 `classify_by_rules` 같은 것)는 의도적으로 제외한다. 지연이 실제로 문제가 된 뒤에 붙일 것이고, 지금 넣으면 규칙과 LLM 판단이 어긋날 때 디버깅 지점이 두 개가 된다.

## 실행기 — `orchestrator_executor.py`

`ThreadPoolExecutor` + 동기 `httpx`로 간다. `asyncio`가 아닌 이유는 Streamlit이 동기 런타임이고, `asyncio.run`을 페이지 안에서 돌리면 이벤트 루프 충돌이 실제로 발생한다.

- 타임아웃은 레지스트리의 `timeout_sec` (에이전트별)
- **실패 격리** — 하나가 죽어도 나머지 답변은 살아서 온다. 죽은 슬롯은 결과 목록에 에러 레코드로 남는다
- 반환: `AgentResult{agent, ok, answer, sufficient, citations, grounding, elapsed_ms, error}`

전부 실패하면 합성으로 넘기지 않고 "모든 에이전트 응답 실패 + 각각의 사유"를 그대로 보여준다. 이때 조용히 LLM 일반 지식으로 답해서는 안 된다 — 근거 없는 답변이 근거 있는 답변처럼 보이게 된다.

## 합성기 — `orchestrator_synth.py`

성공한 결과 수에 따라 경로가 갈린다.

| 결과 | 처리 |
|---|---|
| 0개 | 라우터의 `none_reason` + 붙은 에이전트 목록 |
| 1개 | **그대로 통과 + 출처 표기.** LLM 합성 안 함 |
| 2개 이상 | LLM 합성, 발화 주체 명시 |

1개일 때 합성을 건너뛰는 것은 토큰 절약이 아니라 **왜곡 방지**다. 답변 하나를 LLM에 다시 통과시키면 원문이 바뀐다.

2개 이상일 때 지켜야 할 세 가지:

1. **인용 dedupe** — `법령명+조번호` 기준. `poly_vectordb.py:150`의 `migrate_from_lexagent` 때문에 폴리 코퍼스는 렉스에서 옮겨온 것이고, 두 에이전트가 같은 조항을 인용해 돌려줄 것이 확실하다
2. **`sufficient=False`는 강등·표시** — 근거를 못 찾은 답변을 조문 짚은 답변과 같은 무게로 섞지 않는다
3. **불일치는 감추지 않고 드러낸다** — 렉스와 폴리가 다르게 말하면 하나로 뭉개지 말고 양쪽을 병기한다. 법령 도메인에서 조용한 봉합은 위험하다

## UI — `pages/오케스트레이터.py`

`access_control.is_admin(ip)`으로 잠근다. 초기에는 관리자만 사용한다.

화면 구성:

- 상단: 합성된 통합 답변
- 그 아래: **어느 에이전트를 왜 불렀는지** (라우터의 `reason`) — 라우팅이 블랙박스가 되지 않게 하는 장치
- 접이식: 각 에이전트의 원본 답변 + `grounding` + `sufficient`
- 실패한 에이전트는 사유와 함께 표시

`app.py`의 네비게이션 게이팅에 `is_admin` 조건으로 추가한다 (설정·로그 페이지와 동일한 방식). 접속 로그는 `app.py`가 이미 페이지 단위로 남기므로 별도 작업이 없다.

## 런처 · 헬스체크

- `scripts/start_adapters.ps1`(로컬) / `scripts/start_adapters.sh`(배포) — 레지스트리를 읽어 각 리포의 venv 파이썬으로 `api.py`를 띄운다
- 헬스 패널 — 레지스트리 기반으로 각 `/health`를 호출. `corpus_counts`를 함께 표시

상시 프로세스가 에이전트 수만큼 늘어나는 것은 어댑터 품질로 없어지는 문제가 아니라 "띄우고 살아있는지 보는" 문제다. 그래서 런처와 헬스체크를 처음부터 설계에 포함한다.

## 배포 시 반드시 처리할 것

1. **`data/orchestrator_registry.json`을 배포 화이트리스트에 추가**해야 한다. 현재 `설정.py` 배포는 `data/` 전체를 올리지 않고 `visibility_config.json`만 개별 업로드한다 — 새 JSON은 그냥 올라가지 않는다
2. **어댑터는 AgentPortal 배포 플로우가 손대지 않는 다른 리포에 있다.** 5개 리포의 배포는 각자의 이야기이며, 배포 서버에서 어댑터를 어떻게 띄울지는 이 설계 범위 밖의 별도 결정이다

## 테스트

TDD로 진행한다. 전부 페이크로 덮이는 구조다.

- **레지스트리** — 순수 함수. 기존 `tests/test_visibility_config.py` 패턴을 따른다
- **라우터** — 페이크 LLM이 정해진 JSON을 반환. 표 기반: 개인정보 질문 → lex/policy, 뉴스 질문 → hana/radar, 무관한 질문 → 빈 목록
- **실행기** — 스텁 트랜스포트. 타임아웃 / 1개 다운 격리 / 전부 다운
- **합성기** — 페이크 LLM. 인용 dedupe / 1개 통과 / `sufficient=False` 표시 / 불일치 병기
- **어댑터** — 리포별 계약 테스트(`/ask` 응답 모양). 프니·에리는 추출 전후 동일 결과 특성화 테스트

## 작업 순서 (단계가 아니라 의존 순서)

```
0. 계약 + 레지스트리 스키마 확정 (이 문서)      ← 나머지 전부를 막고 있음
1. 병렬 ─┬ 어댑터 4개 (렉스·폴리·프니·에리, 리포별 독립)
         └ 오케스트레이터 코어 (페이크 어댑터로 TDD)
2. 통합 — 실제 어댑터 연결, 종단 확인, 런처·헬스체크
3. UI 페이지 (admin 게이팅)
4. 삼일 chat_answer 신규 구현 → 어댑터 → 레지스트리 1줄 추가
```

계약을 0번에서 얼리는 것이 곧 1번의 병렬성을 사는 값이다. 오케스트레이터 코어를 페이크 어댑터로 먼저 완성할 수 있어서, 어댑터 4개와 코어가 서로를 기다리지 않는다.

4번(삼일)은 어댑터를 씌우는 일이 아니라 그 리포에 없던 기능을 짓는 일이라 성격이 다르다. 구현을 완료한 뒤 레지스트리에 추가한다.

## 범위에서 제외한 것

- **`/capability` 엔드포인트** — 라우팅 기준이 레지스트리와 갈라진다
- **규칙 기반 사전 라우팅** — 지연이 실제 문제가 된 뒤에
- **삼일의 `rag/query.py` 재사용** — 죽은 코드, 라이브와 프롬프트가 다르다
- **고시(GosiAgent)** — 질문을 받아 답하는 진입점이 없다. 수집·문서분석 파이프라인이지 에이전트가 아니다
- **도구성 에이전트(모델랩·고브·소나·데일리봇)** — 답변 생성체가 아니다
- **마인(MarketInsight)** — 뉴스·동향 계열이지만 1차 대상에서 제외. 레지스트리 1줄로 추후 추가 가능
