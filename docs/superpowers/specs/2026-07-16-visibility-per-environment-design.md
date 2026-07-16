# 에이전트별 로컬/배포 노출 설정 분리 — 설계

## 배경 및 목적

현재 `pages/포털.py`의 `AGENTS` 리스트는 각 에이전트 dict에 `visible: bool` 플래그 하나만 가지고 있다. 배포는 로컬 파일을 그대로(수정 없이) SFTP로 가상화 서버(`192.168.10.169`)에 올리는 방식이라, `visible` 값 하나가 로컬 화면과 배포 화면 모두에 동시에 적용된다.

성환님 요구사항: 로컬에서는 작업 중인 에이전트를 전부 등록해서 보고 싶지만, 가상화 서버에 배포할 때는 그중 일부만 노출되게 하고 싶다. 즉 "로컬 노출 여부"와 "배포(가상화 서버) 노출 여부"를 에이전트별로 완전히 독립적으로 설정할 수 있어야 한다.

## 데이터 저장 — `data/visibility_config.json` (신규)

에이전트 이름을 키로, `visible_local`/`visible_deploy` 두 불리언을 값으로 갖는 JSON.

```json
{
  "LexAgent": {"visible_local": true, "visible_deploy": true},
  "PolicyAgent": {"visible_local": true, "visible_deploy": true},
  "GosiAgent": {"visible_local": true, "visible_deploy": true},
  "ModelTLab": {"visible_local": false, "visible_deploy": false},
  "gov_kr": {"visible_local": false, "visible_deploy": false},
  "SonarGuard": {"visible_local": false, "visible_deploy": false},
  "AIpartner(세무)": {"visible_local": false, "visible_deploy": false}
}
```

**마이그레이션 기본값:** 기존 `AGENTS` dict의 `visible` 키 값을 그대로 `visible_local`·`visible_deploy` 양쪽에 복사해서 초기 파일을 만든다 (동작 변경 없이 시작). 이후 `설정.py`의 체크박스로 자유롭게 조정.

**신규 에이전트(설정 파일에 이름이 없는 경우) 기본값:** `visible_local=True`, `visible_deploy=True` (현재 `a.get("visible", True)` 관례와 동일하게 "명시적으로 끄기 전엔 보임"을 유지).

## AGENTS 데이터 위치 리팩터링

`AGENTS` 리스트를 `pages/포털.py`에서 루트의 `agents_data.py`로 이동. `포털.py`와 `설정.py`가 동일한 `AGENTS`를 import해서 쓸 수 있어야 하는데(설정 페이지에서 에이전트별 체크박스를 그리려면 이름 목록이 필요), 현재처럼 `pages/포털.py` 안에 갇혀 있으면 재사용이 안 됨. 각 dict에서 `visible` 키는 제거(대체됨).

## 로컬 / 배포 환경 판별

`scripts/start_server.sh`는 이미 `PORTAL_ROOT`, `PORTAL_PORT` 환경변수를 받는다. 동일한 방식으로 배포 시 `PORTAL_ENV=deploy`를 추가로 넘긴다:

- `pages/설정.py`의 `_start_streamlit()`에서 원격 실행 커맨드에 `PORTAL_ENV=deploy` 추가.
- `포털.py`는 `os.environ.get("PORTAL_ENV") == "deploy"` 로 배포 여부를 판별.
- 로컬 배치 파일(`AgentPortal.bat`, `통합Agent.bat`)은 이 값을 설정하지 않으므로 자동으로 "로컬"로 처리됨.

## 렌더링 로직 (`pages/포털.py`)

```python
IS_DEPLOYED = os.environ.get("PORTAL_ENV") == "deploy"
VIS_KEY = "visible_deploy" if IS_DEPLOYED else "visible_local"

def load_visibility():
    # data/visibility_config.json 로드, 파일 없으면 {}
    ...

visibility = load_visibility()
VISIBLE_AGENTS = [
    a for a in AGENTS
    if visibility.get(a["name"], {}).get(VIS_KEY, True)
]
```

## 배포 흐름 — 소스 주석처리 없음, 런타임 필터링만

같은 코드 파일이 로컬/배포 서버 양쪽에 그대로 올라간다(소스 코드를 배포 시점에 가공하지 않음). 대신:

1. `data/visibility_config.json`이 배포 시 함께 업로드되어야 한다. 단, `data` 디렉터리를 통째로 `_UPLOAD_DIRS`에 추가하면 같은 폴더의 `data/access_config.json`(IP 접근 제어, 현재 로컬 값은 `192.168.14.222`만 허용)까지 덮어써서 배포 서버의 접근 제어 설정이 로컬 값으로 바뀌는 부작용이 있다 — 이번 작업 범위 밖이므로 건드리지 않는다. 따라서 `_deploy()`에서 `data/visibility_config.json` 파일 **하나만** 타겟팅해서 개별 업로드한다(디렉터리 전체 업로드 아님). (`agents_data.py`는 루트 `.py` 파일이라 기존 `_UPLOAD_SUFFIXES` 규칙으로 이미 업로드 대상에 포함됨.)
2. 실행 환경(env var)에 따라 같은 JSON에서 다른 키(`visible_local` vs `visible_deploy`)를 읽어 카드 노출 여부가 갈린다.

## 설정 페이지 UI (`pages/설정.py`)

"🖥️ 카드 노출 설정" 섹션 신규 추가. `AGENTS`의 각 에이전트마다 체크박스 2개(로컬 노출 / 배포 노출)를 나열. 체크박스 상태가 바뀌면 그 rerun에서 전체 상태를 다시 JSON으로 저장(자동 저장, 별도 저장 버튼 없음).

## 에러 처리

- `visibility_config.json`이 없는 경우(최초 실행 등): 빈 dict로 취급, 모든 에이전트 기본 노출(`True`)로 처리.
- JSON 파싱 실패(손상된 파일): 마찬가지로 빈 dict로 폴백하고 조용히 무시(별도 에러 UI 없음 — 내부 설정 파일이라 사용자 대면 에러 불필요).

## 범위 밖 (Out of scope)

- 기존 `visible` 단일 플래그를 완전히 대체하는 것 외에 다른 노출 로직 변경 없음.
- `data/access_config.json`(IP 접근 제어)은 이번 변경과 무관, 손대지 않음.
