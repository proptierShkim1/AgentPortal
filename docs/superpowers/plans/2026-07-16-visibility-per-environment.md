# 에이전트별 로컬/배포 노출 설정 분리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 각 에이전트 카드가 로컬 화면과 배포(가상화 서버) 화면에서 서로 독립적으로 노출/숨김을 설정할 수 있게 만든다.

**Architecture:** `AGENTS` 데이터를 `pages/포털.py`에서 루트의 `agents_data.py`로 분리하고, 노출 여부는 새 `data/visibility_config.json`(에이전트별 `visible_local`/`visible_deploy`)에 저장한다. 실행 중인 인스턴스가 로컬인지 배포 서버인지는 `PORTAL_ENV` 환경변수로 판별해서 같은 JSON에서 다른 키를 읽는다. 소스 코드 자체는 로컬/배포 양쪽에 동일하게 올라가며, 배포 시 이 JSON 파일 하나만 별도로 업로드된다. `pages/설정.py`에 체크박스 UI를 추가해 이 JSON을 수정한다.

**Tech Stack:** Python, Streamlit, pytest(신규 — 테스트 전용, 배포 서버에는 설치 안 함)

## Global Constraints

- 이 저장소는 git 저장소가 아니다 (`Is a git repository: false`). 스킬 템플릿의 "Commit" 스텝은 생략하고, 대신 각 태스크 끝에 수동 확인 스텝으로 대체한다.
- 기존 파일 인코딩은 UTF-8, 한글 키/문자열 다수 포함 — 모든 파일은 `encoding="utf-8"`로 읽고 쓸 것.
- `data/access_config.json`(IP 접근 제어)은 이번 작업과 무관 — 절대 건드리거나 배포 업로드 대상에 포함시키지 않는다.
- 참조 스펙: `docs/superpowers/specs/2026-07-16-visibility-per-environment-design.md`

---

### Task 1: `agents_data.py`로 AGENTS 리스트 분리 (리팩터링, 동작 변경 없음)

**Files:**
- Create: `C:\Users\USER\Desktop\Project Agent\AgentPortal\agents_data.py`
- Modify: `C:\Users\USER\Desktop\Project Agent\AgentPortal\pages\포털.py`

**Interfaces:**
- Produces: `agents_data.AGENTS` — 각 dict가 `name, nickname, desc, detail, host, port, path, icon, color` 키를 가짐 (`visible` 키는 제거됨). `pages/포털.py`와 향후 `pages/설정.py`가 이 리스트를 import해서 쓴다.

- [ ] **Step 1: `agents_data.py` 생성**

`pages/포털.py`의 현재 `AGENTS` 리스트(1~86번 줄)를 그대로 옮기되, 각 dict의 `"visible": False` 줄은 전부 삭제한다 (노출 여부는 Task 3에서 별도 JSON으로 관리).

```python
# agents_data.py
AGENTS = [
    {
        "name": "LexAgent",
        "nickname": "렉스",
        "desc": "개인정보 법령 RAG 분석",
        "detail": "법령 데이터 기반 질의응답 및 조항 분석",
        "host": "192.168.10.169",
        "port": 9001,
        "path": r"C:\Users\USER\Desktop\Project Agent\LexAgent",
        "icon": "⚖️",
        "color": "#4F8EF7",
    },
    {
        "name": "PolicyAgent",
        "nickname": "폴리",
        "desc": "개인정보 처리방침 분석",
        "detail": "처리방침 문서 검토 및 체크리스트 자동화",
        "host": "192.168.10.169",
        "port": 8502,
        "path": r"C:\Users\USER\Desktop\Project Agent\PolicyAgent",
        "icon": "🔐",
        "color": "#43C59E",
    },
    {
        "name": "GosiAgent",
        "nickname": "고시",
        "desc": "고시 수집 및 알림",
        "detail": "행정 고시 자동 수집 및 실시간 알림",
        "host": "192.168.10.169",
        "port": 9003,
        "path": r"C:\Users\USER\Desktop\Project Agent\GosiAgent",
        "icon": "🏛️",
        "color": "#F7934F",
    },
    {
        "name": "ModelTLab",
        "nickname": "모델랩",
        "desc": "AI 모델 파인튜닝·채팅 테스트",
        "detail": "파인튜닝 모델 실험 및 채팅 인터페이스",
        "host": "192.168.14.222",
        "port": 3010,
        "path": r"C:\Users\USER\Desktop\Project Agent\ModelTLab",
        "icon": "🧫",
        "color": "#D4956A",
    },
    {
        "name": "gov_kr",
        "nickname": "고브",
        "desc": "건축물대장 조회",
        "detail": "건축물대장 자동 조회 및 정보 확인",
        "host": "192.168.14.222",
        "port": 1001,
        "path": r"C:\Users\USER\Desktop\Project Agent\gov_kr",
        "icon": "🏢",
        "color": "#6C63FF",
    },
    {
        "name": "SonarGuard",
        "nickname": "소나",
        "desc": "코드 취약점 스캐너",
        "detail": "정적 분석 기반 코드 보안 취약점 스캐닝",
        "host": "192.168.14.222",
        "port": 2001,
        "path": r"C:\Users\USER\Desktop\Project Agent\local_sonar_test",
        "icon": "🛡️",
        "color": "#E05C4A",
    },
    {
        "name": "AIpartner(세무)",
        "nickname": "삼일PWC",
        "desc": "세무 관련 법안 분석",
        "detail": "세무법안 관련 수집 및 분석",
        "host": "192.168.14.222",
        "port": 9101,
        "path": r"C:\Users\USER\Desktop\Project Agent\pwc_poc",
        "icon": "🤝",
        "color": "#8B5CF6",
    },
]
```

- [ ] **Step 2: `pages/포털.py`에서 AGENTS 리스트 제거하고 import로 교체**

`pages/포털.py`의 맨 위, `import streamlit as st` / `import socket` 다음 줄부터 기존 `AGENTS = [...]` 전체 블록(옛 4~86번 줄)을 지우고 아래로 교체:

```python
import streamlit as st
import socket

from agents_data import AGENTS
```

- [ ] **Step 3: 수동 확인 — 로컬 실행으로 기존과 동일하게 보이는지 확인**

Run: `python -m streamlit run app.py --server.address 192.168.14.222 --server.port 9000`
Expected: 브라우저에서 LexAgent, PolicyAgent 카드만 보임 (기존과 동일 — 아직 `visible` 필터링 로직은 지우지 않았으니 `pages/포털.py` 하단의 `VISIBLE_AGENTS = [a for a in AGENTS if a.get("visible", True)]`는 지금 모든 에이전트가 `visible` 키가 없으므로 전부 노출됨을 확인할 것 → 이 단계에서는 **7개 카드 전부** 보이는 게 정상). 서버 종료: 터미널에서 Ctrl+C.

---

### Task 2: `visibility_config.py` 모듈 작성 (TDD)

**Files:**
- Create: `C:\Users\USER\Desktop\Project Agent\AgentPortal\visibility_config.py`
- Test: `C:\Users\USER\Desktop\Project Agent\AgentPortal\tests\test_visibility_config.py`
- Modify: `C:\Users\USER\Desktop\Project Agent\AgentPortal\requirements-dev.txt` (신규 생성)

**Interfaces:**
- Consumes: 없음 (독립 모듈)
- Produces:
  - `visibility_config.CONFIG_PATH: Path` — `data/visibility_config.json` 경로
  - `visibility_config.load_visibility() -> dict` — 파일 없거나 파싱 실패 시 `{}`
  - `visibility_config.save_visibility(cfg: dict) -> None` — `data/` 디렉터리 없으면 생성 후 저장
  - `visibility_config.visible_agents(agents: list, visibility: dict, is_deployed: bool) -> list` — `is_deployed`에 따라 `visible_local`/`visible_deploy` 키로 필터링, 설정에 없는 에이전트는 기본 `True`(노출)

- [ ] **Step 1: dev 의존성 파일 생성**

```text
# requirements-dev.txt
pytest
```

- [ ] **Step 2: 실패하는 테스트 작성**

```python
# tests/test_visibility_config.py
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import visibility_config as vc


def test_load_visibility_missing_file_returns_empty_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(vc, "CONFIG_PATH", tmp_path / "visibility_config.json")
    assert vc.load_visibility() == {}


def test_load_visibility_corrupted_file_returns_empty_dict(tmp_path, monkeypatch):
    path = tmp_path / "visibility_config.json"
    path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(vc, "CONFIG_PATH", path)
    assert vc.load_visibility() == {}


def test_load_visibility_valid_file_returns_parsed_dict(tmp_path, monkeypatch):
    path = tmp_path / "visibility_config.json"
    data = {"LexAgent": {"visible_local": True, "visible_deploy": False}}
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(vc, "CONFIG_PATH", path)
    assert vc.load_visibility() == data


def test_save_visibility_creates_data_dir_and_writes_json(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "visibility_config.json"
    monkeypatch.setattr(vc, "CONFIG_PATH", path)
    cfg = {"GosiAgent": {"visible_local": True, "visible_deploy": True}}
    vc.save_visibility(cfg)
    assert json.loads(path.read_text(encoding="utf-8")) == cfg


def test_visible_agents_filters_by_local_key_when_not_deployed():
    agents = [{"name": "A"}, {"name": "B"}]
    visibility = {"A": {"visible_local": True, "visible_deploy": False},
                  "B": {"visible_local": False, "visible_deploy": True}}
    result = vc.visible_agents(agents, visibility, is_deployed=False)
    assert [a["name"] for a in result] == ["A"]


def test_visible_agents_filters_by_deploy_key_when_deployed():
    agents = [{"name": "A"}, {"name": "B"}]
    visibility = {"A": {"visible_local": True, "visible_deploy": False},
                  "B": {"visible_local": False, "visible_deploy": True}}
    result = vc.visible_agents(agents, visibility, is_deployed=True)
    assert [a["name"] for a in result] == ["B"]


def test_visible_agents_defaults_to_visible_when_missing_from_config():
    agents = [{"name": "NewAgent"}]
    result = vc.visible_agents(agents, {}, is_deployed=False)
    assert [a["name"] for a in result] == ["NewAgent"]
```

- [ ] **Step 3: 테스트가 실패하는지 확인 (모듈이 아직 없음)**

Run:
```
pip install -r requirements-dev.txt
python -m pytest tests/test_visibility_config.py -v
```
Expected: `ModuleNotFoundError: No module named 'visibility_config'` (전체 실패)

- [ ] **Step 4: `visibility_config.py` 구현**

```python
# visibility_config.py
import json
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "data" / "visibility_config.json"


def load_visibility() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_visibility(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def visible_agents(agents: list, visibility: dict, is_deployed: bool) -> list:
    key = "visible_deploy" if is_deployed else "visible_local"
    return [a for a in agents if visibility.get(a["name"], {}).get(key, True)]
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest tests/test_visibility_config.py -v`
Expected: 7개 테스트 전부 PASS

- [ ] **Step 6: 수동 확인 — 완료 표시**

이 태스크는 순수 로직이라 브라우저 확인 불필요. pytest 전부 PASS면 완료.

---

### Task 3: 초기 `data/visibility_config.json` 생성 (마이그레이션)

**Files:**
- Create: `C:\Users\USER\Desktop\Project Agent\AgentPortal\data\visibility_config.json`

**Interfaces:**
- Consumes: 없음 (정적 데이터 파일)
- Produces: Task 4의 `pages/포털.py`와 Task 5의 `pages/설정.py`가 `visibility_config.load_visibility()`를 통해 읽는 초기 데이터.

- [ ] **Step 1: 기존 `visible` 값 기준으로 마이그레이션 파일 작성**

기존 `pages/포털.py`에서 LexAgent/PolicyAgent/GosiAgent는 `visible` 키가 없었으므로 기본 `True`, ModelTLab/gov_kr/SonarGuard/AIpartner(세무)는 `visible: False`였다. 이 값을 그대로 `visible_local`/`visible_deploy` 양쪽에 복사한다(동작 변경 없이 시작).

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

- [ ] **Step 2: 수동 확인 — JSON 유효성**

Run: `python -c "import json; print(json.load(open('data/visibility_config.json', encoding='utf-8')))"`
Expected: 에러 없이 dict 출력됨

---

### Task 4: `pages/포털.py`에 환경별 필터링 적용

**Files:**
- Modify: `C:\Users\USER\Desktop\Project Agent\AgentPortal\pages\포털.py`

**Interfaces:**
- Consumes: `agents_data.AGENTS` (Task 1), `visibility_config.load_visibility()` / `visibility_config.visible_agents()` (Task 2), `data/visibility_config.json` (Task 3)
- Produces: `PORTAL_ENV` 환경변수를 읽어 로컬/배포를 구분하는 필터링된 카드 목록 (`VISIBLE_AGENTS`)

- [ ] **Step 1: import 및 환경 판별 코드 추가**

`pages/포털.py` 상단 (Task 1에서 넣은 `from agents_data import AGENTS` 바로 아래)에 추가:

```python
import os
from visibility_config import load_visibility, visible_agents

IS_DEPLOYED = os.environ.get("PORTAL_ENV") == "deploy"
```

- [ ] **Step 2: 기존 `visible` 기반 필터링 줄을 새 로직으로 교체**

`pages/포털.py`에서 기존 줄:
```python
VISIBLE_AGENTS = [a for a in AGENTS if a.get("visible", True)]
```
를 아래로 교체:
```python
VISIBLE_AGENTS = visible_agents(AGENTS, load_visibility(), IS_DEPLOYED)
```

- [ ] **Step 3: 수동 확인 — 로컬 환경(PORTAL_ENV 미설정)**

Run: `python -m streamlit run app.py --server.address 192.168.14.222 --server.port 9000`
Expected: LexAgent, PolicyAgent, GosiAgent 카드만 보임 (Task 3의 `visible_local: true`인 3개). 확인 후 Ctrl+C로 종료.

- [ ] **Step 4: 수동 확인 — 배포 환경 시뮬레이션(PORTAL_ENV=deploy)**

PowerShell:
```
$env:PORTAL_ENV="deploy"; python -m streamlit run app.py --server.address 192.168.14.222 --server.port 9000
```
Expected: 위와 동일하게 LexAgent, PolicyAgent, GosiAgent 카드만 보임 (Task 3에서 `visible_deploy`도 동일 값으로 마이그레이션했으므로). 확인 후 Ctrl+C, `Remove-Item Env:PORTAL_ENV`로 환경변수 해제.

---

### Task 5: `pages/설정.py`에 카드 노출 설정 UI 추가

**Files:**
- Modify: `C:\Users\USER\Desktop\Project Agent\AgentPortal\pages\설정.py`

**Interfaces:**
- Consumes: `agents_data.AGENTS` (Task 1), `visibility_config.load_visibility()` / `visibility_config.save_visibility()` (Task 2)
- Produces: 없음 (UI 종단 — 사용자가 직접 조작)

- [ ] **Step 1: 파일 상단 import 추가**

`pages/설정.py`의 기존 import 블록(`import streamlit as st` 등) 바로 아래에 추가:

```python
from agents_data import AGENTS
from visibility_config import load_visibility, save_visibility
```

- [ ] **Step 2: "🖥️ 카드 노출 설정" 섹션 추가**

`pages/설정.py`에서 `st.title("⚙️ 설정")` 바로 다음, `# ── 서버 배포 ──` 섹션 이전에 추가:

```python
# ── 카드 노출 설정 ──────────────────────────────────────────
st.subheader("🖥️ 카드 노출 설정")
st.caption("로컬 화면과 배포(가상화 서버) 화면에 각각 독립적으로 노출 여부를 설정합니다.")

_visibility = load_visibility()
_new_visibility = {}

for _agent in AGENTS:
    _name = _agent["name"]
    _current = _visibility.get(_name, {"visible_local": True, "visible_deploy": True})
    col_label, col_local, col_deploy = st.columns([2, 1, 1])
    with col_label:
        st.markdown(f"**{_agent['icon']} {_name}** ({_agent['nickname']})")
    with col_local:
        _vl = st.checkbox("로컬 노출", value=_current.get("visible_local", True), key=f"vis_local_{_name}")
    with col_deploy:
        _vd = st.checkbox("배포 노출", value=_current.get("visible_deploy", True), key=f"vis_deploy_{_name}")
    _new_visibility[_name] = {"visible_local": _vl, "visible_deploy": _vd}

if _new_visibility != _visibility:
    save_visibility(_new_visibility)

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
```

- [ ] **Step 3: 수동 확인 — 체크박스 토글이 JSON에 저장되는지 확인**

Run: `python -m streamlit run app.py --server.address 192.168.14.222 --server.port 9000`
브라우저에서 "⚙️ 설정" 페이지로 이동 → SonarGuard의 "로컬 노출" 체크박스를 켠다.
Expected: 체크박스가 켜진 채로 유지되고, `data/visibility_config.json`을 열어보면 `"SonarGuard": {"visible_local": true, ...}`로 바뀌어 있음. 이어서 "포털" 페이지로 이동하면 SonarGuard 카드가 보임.
확인 후 다시 체크 해제해서 원상복구(SonarGuard `visible_local: false`), Ctrl+C로 서버 종료.

---

### Task 6: 배포 스크립트에 `PORTAL_ENV` 및 `visibility_config.json` 업로드 반영

**Files:**
- Modify: `C:\Users\USER\Desktop\Project Agent\AgentPortal\pages\설정.py`

**Interfaces:**
- Consumes: 기존 `_deploy()`, `_start_streamlit()` 함수 (파일 내 이미 정의됨)
- Produces: 배포 시 `data/visibility_config.json`이 원격 서버에 업로드되고, 원격 Streamlit 프로세스가 `PORTAL_ENV=deploy`를 갖고 실행됨

- [ ] **Step 1: `_start_streamlit()`에 `PORTAL_ENV=deploy` 추가**

`pages/설정.py`의 `_start_streamlit()` 함수 안, 기존 줄:
```python
        f"PORTAL_ROOT={_DEPLOY_REMOTE} PORTAL_PORT={_DEPLOY_APP_PORT} bash {script}"
```
를 아래로 교체:
```python
        f"PORTAL_ROOT={_DEPLOY_REMOTE} PORTAL_PORT={_DEPLOY_APP_PORT} PORTAL_ENV=deploy bash {script}"
```

- [ ] **Step 2: `_deploy()`에서 `data/visibility_config.json` 개별 업로드 추가**

`pages/설정.py`의 `_deploy()` 함수 안, 기존 줄:
```python
        for dir_name in _UPLOAD_DIRS:
            local_sub = ROOT / dir_name
            if local_sub.exists():
                _sftp_upload_dir(sftp, local_sub, f"{_DEPLOY_REMOTE}/{dir_name}", log)
        log("✅ 코드 업로드 완료")
```
바로 다음 줄(같은 `try` 블록, `log("✅ 코드 업로드 완료")` 뒤)에 추가:

```python
        _vis_local = ROOT / "data" / "visibility_config.json"
        if _vis_local.exists():
            _sftp_mkdir_p(sftp, f"{_DEPLOY_REMOTE}/data")
            sftp.put(str(_vis_local), f"{_DEPLOY_REMOTE}/data/visibility_config.json")
            log("↑ data/visibility_config.json")
```

주의: `data` 디렉터리 전체가 아니라 이 파일 하나만 업로드한다 — `data/access_config.json`(IP 접근 제어)은 절대 건드리지 않는다. `_UPLOAD_DIRS` 세트에는 `"data"`를 추가하지 않는다.

- [ ] **Step 3: 수동 확인 — 코드 리뷰만 (실제 원격 배포는 이번 작업 범위 밖)**

`pages/설정.py`를 열어 두 수정이 정확히 반영됐는지 확인:
1. `_start_streamlit()`의 명령 문자열에 `PORTAL_ENV=deploy`가 포함되어 있는지
2. `_deploy()`가 `sftp.put`으로 `data/visibility_config.json`을 개별 전송하는지, `_UPLOAD_DIRS`는 그대로 `{".streamlit", "scripts", "pages"}`인지(변경 안 됨)

실제 "🚀 서버에 배포" 버튼 클릭(가상화 서버로의 실제 SSH 배포)은 성환님이 준비되었을 때 직접 실행 — 이 계획에는 포함하지 않는다.

---

## 완료 후 최종 확인 체크리스트

- [ ] `python -m pytest tests/ -v` 전체 PASS
- [ ] 로컬 실행 시 LexAgent/PolicyAgent/GosiAgent만 보임 (`PORTAL_ENV` 미설정)
- [ ] `$env:PORTAL_ENV="deploy"` 상태에서도 동일하게 보임 (마이그레이션 기본값이 같으므로)
- [ ] 설정 페이지에서 체크박스 토글 시 `data/visibility_config.json`이 즉시 갱신되고, 포털 페이지에 반영됨
- [ ] `data/access_config.json`은 이번 변경 전후로 내용 동일(건드리지 않았음)
