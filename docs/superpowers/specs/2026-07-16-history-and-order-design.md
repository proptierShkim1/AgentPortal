# 버전이력 페이지 + 카드 순서 변경 — 설계

## 배경

두 가지 요청을 함께 처리한다:
1. `ProptierAI` 프로젝트의 `pages/버전이력.py`(git 커밋 로그 뷰어)를 AgentPortal에도 도입.
2. `pages/설정.py`에서 포털 카드의 노출 순서를 번호로 지정할 수 있게 함.

AgentPortal은 이번 세션에서 처음 git 저장소가 되었으므로, `버전이력` 페이지가 읽을 실제 커밋 로그가 존재한다.

## 1. IP별 권한 확장 (`access_control.py`)

`data/access_config.json`의 `allowed_ips` 엔트리를 `{ip, name}`에서 `{ip, name, is_admin, can_view_history}`로 확장. 기존 유일한 엔트리(성환님, `192.168.14.222`)는 `is_admin: true, can_view_history: true`로 마이그레이션.

`access_control.py`에 ProptierAI와 동일한 시그니처로 추가:
- `is_admin(ip) -> bool` — admin으로 등록된 IP가 하나도 없으면 전체 허용(부트스트랩 모드), 있으면 등록된 IP만 허용.
- `can_view_history(ip) -> bool` — `is_admin`이거나 `can_view_history` 플래그가 있는 IP만 허용, 등록된 사람이 하나도 없으면 전체 허용(부트스트랩 모드).
- `ip_name_map()` / `name_for_ip(ip)` — ProptierAI에 있지만 이번 작업에서 실제로 쓰이는 곳은 없음. **가져오지 않음** (YAGNI — 안 쓰는 함수는 추가하지 않는다).

`is_allowed()`는 이미 dict/string 엔트리를 모두 처리하므로 변경 없음.

## 2. 페이지 접근 권한 (`app.py`)

- `pages/포털.py`: 지금처럼 `is_allowed()` 통과자 전원 접근 가능 (변경 없음).
- `pages/설정.py`: **관리자(`is_admin`) 전용**으로 변경 (사용자 확정: "설정 페이지도 is_admin으로 제한").
- `pages/버전이력.py` (신규): `can_view_history()` 통과자만 사이드바에 노출.

```python
_pages = [st.Page("pages/포털.py", title="포털", icon="🏢")]
if is_admin(_client_ip):
    _pages.append(st.Page("pages/설정.py", title="설정", icon="⚙️"))
if can_view_history(_client_ip):
    _pages.append(st.Page("pages/버전이력.py", title="버전 이력", icon="📜"))
pg = st.navigation(_pages)
```

## 3. `pages/버전이력.py` (신규)

ProptierAI의 구현을 그대로 가져오되 두 가지만 다르게:
- `layout.render_page_header()` 대신 AgentPortal 기존 스타일(`설정.py`처럼 `st.title()`/`st.caption()`/`st.divider()`)로 인라인 처리 — AgentPortal에는 `layout.py`가 없고, 헤더 카드 하나 때문에 새 모듈을 들이는 건 과함.
- 페이지 최상단에서 `can_view_history(st.session_state.get("_client_ip", ""))` 재확인 후 통과 못하면 차단 — `app.py`의 네비게이션 필터링과 별개로, URL 직접 접근에 대한 방어선(ProptierAI와 동일한 이중 체크 패턴).

git 로그는 AgentPortal 저장소 자체(`ROOT = 이 파일의 부모의 부모, 즉 AgentPortal 루트`)를 대상으로 `git log`를 실행 — 이 저장소가 이번에 처음 git이 되었으므로 실제 커밋들이 그대로 보임.

기능(ProptierAI와 동일): 작성자 필터, 커밋 메시지 검색, 페이지네이션, 커밋 클릭 시 `git show --stat` 상세 다이얼로그.

## 4. 카드 순서 변경

`data/visibility_config.json`의 각 에이전트 엔트리에 `"order": int` 키 추가. 마이그레이션 시 현재 `agents_data.AGENTS` 리스트 순서 그대로 0부터 순번 부여(Lex=0 ... MarketInsight=7) — 시각적으로 아무것도 안 바뀐 채로 시작.

`visibility_config.py`에 함수 추가:
```python
def sort_by_order(agents: list, visibility: dict) -> list:
    return sorted(
        enumerate(agents),
        key=lambda pair: visibility.get(pair[1]["name"], {}).get("order", pair[0]),
    )
```
반환값에서 인덱스를 벗겨 에이전트 dict 리스트로 정리해서 씀. `order` 값이 없는 에이전트는 원래 리스트 위치를 기본값으로 사용 — 새 에이전트를 `agents_data.py`에 추가만 하고 아직 순서를 안 정했다면 지금처럼 리스트 끝에 자연스럽게 붙는다. 두 에이전트가 같은 순서 번호를 가지면(사용자가 실수로 중복 입력) `sorted()`가 안정 정렬이라 원래 순서를 기준으로 조용히 정렬됨 — 별도의 중복 검증 UI는 넣지 않음(과한 엔지니어링).

`pages/포털.py`: `visible_agents()`로 필터링한 다음 `sort_by_order()`로 정렬해서 렌더링.

`pages/설정.py`: 기존 "로컬 노출"/"배포 노출" 체크박스 옆에 "순서" `st.number_input`(정수, 최소 0) 한 칸 추가. 값이 바뀌면 기존 자동저장 로직(`_new_visibility[name]`)에 `order` 필드도 같이 담아 저장 — 별도 저장 버튼 없음, 기존 체크박스와 동일한 자동저장 방식.

## 에러 처리 / 엣지 케이스

- `버전이력` 페이지에서 git 로그를 못 읽으면(저장소 아님 등) "커밋 이력을 불러올 수 없습니다" 안내 후 조용히 종료 — ProptierAI와 동일.
- `access_config.json`에 `is_admin`/`can_view_history` 필드가 없는 과거 형식 엔트리가 남아있어도 `.get(key, False)`로 안전하게 처리(크래시 없음).
- 순서 번호 중복/음수 입력에 대한 별도 검증 없음(위 참고).

## 범위 밖

- `ip_name_map()`/`name_for_ip()` — 안 씀.
- 드래그 앤 드롭 정렬 — 사용자가 번호 입력 방식으로 확정.
- `data/access_config.json`을 통해 새 IP를 등록/편집하는 UI — 이번 요청에 없었음, 손 안 댐(JSON 직접 편집으로 계속 관리).
