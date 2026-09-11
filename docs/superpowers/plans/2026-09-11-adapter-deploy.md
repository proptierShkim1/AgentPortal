# 어댑터 배포·운영 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 어댑터 4개(렉스·폴리·프니·에리)를 가상화 서버에 올리고 user systemd로 상주시키며, 그 배포를 AgentPortal 설정 페이지에서 레지스트리 선언만으로 수행할 수 있게 한다.

**Architecture:** 배포 정보는 `data/orchestrator_registry.json`의 `deploy` 블록에 선언한다. 경로 계산·유닛 파일 생성 같은 순수 로직과 SSH 실행 로직은 새 모듈 `adapter_deploy.py`에 두고, `pages/설정.py`는 화면만 그린다. SSH 실행 함수는 `run` 콜러블을 주입받아 가짜 객체로 테스트한다.

**Tech Stack:** Python 3.11, Streamlit, paramiko(SFTP/SSH), pytest, systemd --user(원격)

**Spec:** `docs/superpowers/specs/2026-09-11-adapter-deploy-design.md`

## Global Constraints

- 서버 설치 패키지는 **`fastapi==0.138.0`, `uvicorn==0.42.0`** 고정. `fastapi==0.121.2`는 starlette을 1.3.1→0.49.3으로 내려 streamlit(렉스·폴리)을 깨뜨린다.
- 서버에서 **`pip install -r requirements.txt`를 실행하지 않는다.** `deploy.pip`에 적힌 패키지만 개별 설치한다.
- 설치 전 **항상 `--dry-run`을 먼저 돌려** 기존 패키지의 다운그레이드가 없는지 확인한다. 있으면 중단한다.
- 원격에서 **`sudo`를 쓰지 않는다.** 모든 서비스는 `systemctl --user`, 유닛은 `~/.config/systemd/user/`.
- 어댑터 포트 고정: lex 9501, policy 9502, hana 7500, radar 4501.
- 업로드 버튼은 **기동하지 않는다.** `daemon-reload` + `enable`까지만. 기동/재시작은 별도 버튼.
- 덮어쓰는 원격 파일은 **반드시 `<이름>.bak-YYYYMMDD-HHMM`으로 백업**한 뒤 올린다.
- 상태 조회 대상은 **항상 `DEPLOY_HOST`**(현재 환경이 아니라 배포 서버).
- 서버 사용자 홈은 `/home/shkim1`이며 `DEPLOY_USER`에서 유도한다. 경로를 코드에 박지 않는다.

## File Structure

| 파일 | 책임 |
|---|---|
| `orchestrator_registry.py` (수정) | `deploy_targets()` — `deploy` 블록이 온전한 항목만 골라낸다 |
| `data/orchestrator_registry.json` (수정) | 4개 항목에 `deploy` 블록 선언 |
| `adapter_deploy.py` (신규) | 경로·유닛 텍스트 생성(순수) + 업로드·설치·등록·재시작(SSH) |
| `tests/test_adapter_deploy.py` (신규) | 위 모듈의 단위 테스트. SSH는 가짜 `run`으로 대체 |
| `tests/test_orchestrator_registry.py` (수정) | `deploy_targets()` 테스트 추가 |
| `pages/설정.py` (수정) | `🔌 어댑터 배포` 섹션 렌더링만. 로직은 `adapter_deploy` 호출 |
| 어댑터 4개 리포의 `requirements.txt` (수정) | 잘못된 fastapi 핀 교정 |

---

### Task 1: 레지스트리 `deploy_targets()`

**Files:**
- Modify: `orchestrator_registry.py`
- Test: `tests/test_orchestrator_registry.py`

**Interfaces:**
- Consumes: 기존 `load_registry()`
- Produces: `DEPLOY_REQUIRED_FIELDS: tuple[str, ...]`, `deploy_targets(registry: dict) -> dict` — 키→항목(전체 entry). `enabled` 여부와 무관하게 배포 대상으로 본다(켜기 전에 먼저 올려두는 운영을 허용).

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/test_orchestrator_registry.py` 맨 아래에 추가한다. 기존 `_entry()` 헬퍼를 재사용한다.

```python
def _deploy(**over):
    base = {
        "local_dir": "../hana_p",
        "remote_dir": "~/hana_p",
        "files": ["api.py"],
        "mode": "service",
        "unit": "hana-adapter.service",
        "description": "프니 어댑터",
        "exec": "venv/bin/python api.py",
        "log": "adapter.log",
        "pip": ["fastapi==0.138.0", "uvicorn==0.42.0"],
    }
    base.update(over)
    return base


def test_deploy_targets_keeps_entry_with_complete_deploy_block():
    registry = {"hana": _entry(deploy=_deploy())}
    assert list(reg.deploy_targets(registry)) == ["hana"]


def test_deploy_targets_drops_entry_without_deploy_block():
    # deploy 블록이 없는 항목은 '로컬 전용 에이전트'다. 오류가 아니라 조용히 제외한다.
    registry = {"lex": _entry()}
    assert reg.deploy_targets(registry) == {}


def test_deploy_targets_drops_entry_missing_required_deploy_field():
    registry = {"hana": _entry(deploy=_deploy(unit=""))}
    assert reg.deploy_targets(registry) == {}


def test_deploy_targets_drops_entry_with_unknown_mode():
    # mode 오타를 그냥 통과시키면 유닛 생성 단계에서 엉뚱한 파일이 만들어진다.
    registry = {"hana": _entry(deploy=_deploy(mode="daemon"))}
    assert reg.deploy_targets(registry) == {}


def test_deploy_targets_includes_disabled_entry():
    # 어댑터를 먼저 올려두고 나중에 enabled를 켜는 운영을 허용한다.
    registry = {"hana": _entry(enabled=False, deploy=_deploy())}
    assert list(reg.deploy_targets(registry)) == ["hana"]
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `pytest tests/test_orchestrator_registry.py -k deploy_targets -v`
Expected: FAIL — `AttributeError: module 'orchestrator_registry' has no attribute 'deploy_targets'`

- [ ] **Step 3: 최소 구현을 작성한다**

`orchestrator_registry.py`의 `REQUIRED_FIELDS` 아래에 상수를, `enabled_agents()` 아래에 함수를 추가한다.

```python
# 배포에 필요한 선언. 하나라도 비면 어디에 무엇을 올릴지 알 수 없으므로 제외한다.
DEPLOY_REQUIRED_FIELDS = ("local_dir", "remote_dir", "files", "mode", "unit", "exec")
DEPLOY_MODES = ("service", "thread")
```

```python
def deploy_targets(registry: dict) -> dict:
    """배포 정보가 온전히 선언된 항목만 돌려준다.

    deploy 블록이 없는 항목은 오류가 아니라 '로컬 전용 에이전트'로 보고 조용히
    제외한다. enabled는 보지 않는다 — 어댑터를 먼저 올려두고 나중에 켜는 운영이
    가능해야 한다."""
    result = {}
    for key, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        dep = entry.get("deploy")
        if not isinstance(dep, dict):
            continue
        if any(not dep.get(field) for field in DEPLOY_REQUIRED_FIELDS):
            continue
        if dep.get("mode") not in DEPLOY_MODES:
            continue
        result[key] = entry
    return result
```

- [ ] **Step 4: 테스트가 통과하는 것을 확인한다**

Run: `pytest tests/test_orchestrator_registry.py -v`
Expected: PASS — 기존 테스트 포함 전부 통과

- [ ] **Step 5: 커밋한다**

```bash
git add orchestrator_registry.py tests/test_orchestrator_registry.py
git commit -m "레지스트리에 배포 대상 선언(deploy 블록) 추가"
```

---

### Task 2: 레지스트리에 실제 `deploy` 블록 4개 선언

**Files:**
- Modify: `data/orchestrator_registry.json`
- Test: `tests/test_orchestrator_registry.py`

**Interfaces:**
- Consumes: Task 1의 `deploy_targets()`
- Produces: 실제 레지스트리 파일이 4개 배포 대상을 돌려준다

`exec` 값은 **지금 서버에서 돌고 있는 커맨드라인 그대로**다(2026-09-11 `ps` 확인). 바꾸면 서비스 전환 시 동작이 달라진다.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

```python
def test_real_registry_declares_four_deploy_targets():
    # 실제 파일이 계획대로 선언돼 있는지 — 오타로 조용히 빠지는 것을 잡는다.
    registry = reg.load_registry()
    targets = reg.deploy_targets(registry)
    assert sorted(targets) == ["hana", "lex", "policy", "radar"]


def test_real_registry_deploy_pins_verified_fastapi_version():
    # fastapi 0.121.2는 starlette을 내려 streamlit을 깨뜨린다. 핀을 되돌리지 못하게 막는다.
    for key, entry in reg.deploy_targets(reg.load_registry()).items():
        pins = entry["deploy"].get("pip", [])
        assert "fastapi==0.138.0" in pins, key
        assert "uvicorn==0.42.0" in pins, key
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `pytest tests/test_orchestrator_registry.py -k real_registry -v`
Expected: FAIL — `assert [] == ['hana', 'lex', 'policy', 'radar']`

- [ ] **Step 3: 레지스트리에 deploy 블록을 넣는다**

`data/orchestrator_registry.json`의 각 항목에 아래를 추가한다(기존 필드는 건드리지 않는다).

`lex`:
```json
"deploy": {
  "local_dir": "../LexAgent",
  "remote_dir": "~/LexAgent",
  "files": ["api.py", "app.py"],
  "mode": "thread",
  "unit": "lexagent.service",
  "description": "LexAgent Streamlit App (오케스트레이터 어댑터 포함)",
  "exec": "venv/bin/python -m streamlit run app.py --server.address 0.0.0.0 --server.port 9001 --server.headless true",
  "log": "streamlit.log",
  "pip": ["fastapi==0.138.0", "uvicorn==0.42.0"]
}
```

`policy`:
```json
"deploy": {
  "local_dir": "../PolicyAgent",
  "remote_dir": "~/PolicyAgent",
  "files": ["api.py", "app.py"],
  "mode": "thread",
  "unit": "policyagent.service",
  "description": "PolicyAgent Streamlit App (오케스트레이터 어댑터 포함)",
  "exec": "venv/bin/python -m streamlit run app.py --server.address 0.0.0.0 --server.port 9002 --server.headless true",
  "log": "streamlit.log",
  "pip": ["fastapi==0.138.0", "uvicorn==0.42.0"]
}
```

`hana`:
```json
"deploy": {
  "local_dir": "../hana_p",
  "remote_dir": "~/hana_p",
  "files": ["api.py"],
  "mode": "service",
  "unit": "hana-adapter.service",
  "description": "Proptier AI News 오케스트레이터 어댑터",
  "exec": "venv/bin/python api.py",
  "log": "adapter.log",
  "pip": ["fastapi==0.138.0", "uvicorn==0.42.0"]
}
```

`radar` — 로컬 리포명(`AiAxRadar`)과 서버 리포명(`ai_news_radar`)이 다르다:
```json
"deploy": {
  "local_dir": "../AiAxRadar",
  "remote_dir": "~/ai_news_radar",
  "files": ["api.py"],
  "mode": "service",
  "unit": "radar-adapter.service",
  "description": "AI RADAR 오케스트레이터 어댑터",
  "exec": "venv/bin/python api.py",
  "log": "adapter.log",
  "pip": ["fastapi==0.138.0", "uvicorn==0.42.0"]
}
```

- [ ] **Step 4: 테스트가 통과하는 것을 확인한다**

Run: `pytest tests/test_orchestrator_registry.py -v`
Expected: PASS

- [ ] **Step 5: 커밋한다**

```bash
git add data/orchestrator_registry.json tests/test_orchestrator_registry.py
git commit -m "레지스트리에 어댑터 4개 배포 선언 추가"
```

---

### Task 3: `adapter_deploy.py` — 경로와 유닛 텍스트 (순수 함수)

**Files:**
- Create: `adapter_deploy.py`
- Test: `tests/test_adapter_deploy.py`

**Interfaces:**
- Consumes: 없음(순수)
- Produces:
  - `expand_home(path: str, home: str) -> str`
  - `remote_dir(entry: dict, home: str) -> str`
  - `local_dir(entry: dict, root: Path) -> Path`
  - `upload_pairs(entry: dict, root: Path, home: str) -> list[tuple[Path, str]]`
  - `unit_path(entry: dict, home: str) -> str`
  - `unit_text(entry: dict, home: str) -> str`
  - `backup_name(remote_path: str, now: datetime = None) -> str`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/test_adapter_deploy.py`를 새로 만든다.

```python
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import adapter_deploy as ad

HOME = "/home/shkim1"
ROOT = Path("C:/repo/AgentPortal")


def _entry(**over):
    dep = {
        "local_dir": "../hana_p",
        "remote_dir": "~/hana_p",
        "files": ["api.py"],
        "mode": "service",
        "unit": "hana-adapter.service",
        "description": "프니 어댑터",
        "exec": "venv/bin/python api.py",
        "log": "adapter.log",
        "pip": ["fastapi==0.138.0", "uvicorn==0.42.0"],
    }
    dep.update(over)
    return {"agent_name": "Proptier AI News", "api_port": 7500, "deploy": dep}


def test_expand_home_replaces_tilde():
    assert ad.expand_home("~/hana_p", HOME) == "/home/shkim1/hana_p"


def test_expand_home_leaves_absolute_path():
    assert ad.expand_home("/srv/hana_p", HOME) == "/srv/hana_p"


def test_upload_pairs_maps_local_file_to_remote_path():
    pairs = ad.upload_pairs(_entry(), ROOT, HOME)
    assert pairs == [(ROOT / ".." / "hana_p" / "api.py", "/home/shkim1/hana_p/api.py")]


def test_upload_pairs_includes_entrypoint_for_thread_mode():
    entry = _entry(mode="thread", files=["api.py", "app.py"])
    remotes = [r for _, r in ad.upload_pairs(entry, ROOT, HOME)]
    assert remotes == ["/home/shkim1/hana_p/api.py", "/home/shkim1/hana_p/app.py"]


def test_unit_path_points_at_user_systemd_dir():
    # sudo가 없으므로 시스템 경로(/etc/systemd/system)를 쓰면 안 된다.
    assert ad.unit_path(_entry(), HOME) == "/home/shkim1/.config/systemd/user/hana-adapter.service"


def test_unit_text_uses_absolute_exec_and_workdir():
    text = ad.unit_text(_entry(), HOME)
    assert "WorkingDirectory=/home/shkim1/hana_p" in text
    assert "ExecStart=/home/shkim1/hana_p/venv/bin/python api.py" in text
    assert "Description=프니 어댑터" in text


def test_unit_text_appends_both_streams_to_one_log():
    text = ad.unit_text(_entry(), HOME)
    assert "StandardOutput=append:/home/shkim1/hana_p/adapter.log" in text
    assert "StandardError=append:/home/shkim1/hana_p/adapter.log" in text


def test_unit_text_restarts_on_failure_and_installs_to_default_target():
    text = ad.unit_text(_entry(), HOME)
    assert "Restart=on-failure" in text
    assert "WantedBy=default.target" in text


def test_backup_name_appends_timestamp():
    now = datetime(2026, 9, 11, 14, 30)
    assert ad.backup_name("/home/shkim1/LexAgent/app.py", now) == \
        "/home/shkim1/LexAgent/app.py.bak-20260911-1430"
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `pytest tests/test_adapter_deploy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'adapter_deploy'`

- [ ] **Step 3: 최소 구현을 작성한다**

`adapter_deploy.py`를 새로 만든다.

```python
"""어댑터를 배포 서버에 올리고 user systemd로 상주시킨다.

경로 계산과 유닛 파일 생성은 순수 함수로 두고, SSH가 필요한 동작은 run 콜러블을
주입받는다. 그래야 서버 없이 테스트할 수 있다.

sudo를 쓰지 않는다 — 배포 사용자는 비밀번호 없는 sudo가 없다. 모든 서비스는
systemctl --user이고 유닛은 ~/.config/systemd/user/에 둔다."""
from datetime import datetime
from pathlib import Path

UNIT_TEMPLATE = """[Unit]
Description={description}
After=network.target

[Service]
Type=simple
WorkingDirectory={workdir}
ExecStart={exec_start}
Restart=on-failure
RestartSec=5
StandardOutput=append:{logfile}
StandardError=append:{logfile}

[Install]
WantedBy=default.target
"""


def expand_home(path: str, home: str) -> str:
    if path.startswith("~/"):
        return f"{home}/{path[2:]}"
    return path


def remote_dir(entry: dict, home: str) -> str:
    return expand_home(entry["deploy"]["remote_dir"], home).rstrip("/")


def local_dir(entry: dict, root: Path) -> Path:
    return root / entry["deploy"]["local_dir"]


def upload_pairs(entry: dict, root: Path, home: str) -> list:
    """(로컬 경로, 원격 경로) 목록. 선언된 순서를 유지한다."""
    base_local = local_dir(entry, root)
    base_remote = remote_dir(entry, home)
    return [(base_local / name, f"{base_remote}/{name}") for name in entry["deploy"]["files"]]


def unit_path(entry: dict, home: str) -> str:
    return f"{home}/.config/systemd/user/{entry['deploy']['unit']}"


def unit_text(entry: dict, home: str) -> str:
    dep = entry["deploy"]
    workdir = remote_dir(entry, home)
    return UNIT_TEMPLATE.format(
        description=dep.get("description") or dep["unit"],
        workdir=workdir,
        exec_start=f"{workdir}/{dep['exec']}",
        logfile=f"{workdir}/{dep.get('log') or 'adapter.log'}",
    )


def backup_name(remote_path: str, now: datetime = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M")
    return f"{remote_path}.bak-{stamp}"
```

- [ ] **Step 4: 테스트가 통과하는 것을 확인한다**

Run: `pytest tests/test_adapter_deploy.py -v`
Expected: PASS — 10개 통과

- [ ] **Step 5: 커밋한다**

```bash
git add adapter_deploy.py tests/test_adapter_deploy.py
git commit -m "어댑터 배포: 경로 계산과 systemd 유닛 생성"
```

---

### Task 4: 원격 상태 확인과 업로드 (SSH)

**Files:**
- Modify: `adapter_deploy.py`
- Test: `tests/test_adapter_deploy.py`

**Interfaces:**
- Consumes: Task 3의 `upload_pairs()`, `backup_name()`
- Produces:
  - `file_state(run, local: Path, remote: str) -> str` — `"동일"` / `"다름"` / `"없음"`
  - `upload_files(sftp, run, entry, root, home, log) -> int` — 올린 파일 수. 기존 파일은 백업 후 덮어쓴다
- `run`은 `run(cmd: str, timeout: int = 120) -> tuple[str, str, int]`(stdout, stderr, rc) 규약이다. `pages/설정.py`의 기존 `_ssh_run`을 감싸 넘긴다.

- [ ] **Step 1: 실패하는 테스트를 작성한다**

기존 `tests/test_adapter_deploy.py`에 이어 붙인다. 맨 위 import에 `import hashlib`을 추가한다.

```python
class FakeRun:
    """run(cmd) -> (out, err, rc). 명령별 응답을 미리 지정하고 호출을 기록한다."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def __call__(self, cmd, timeout=None):
        self.calls.append(cmd)
        for needle, resp in self.responses.items():
            if needle in cmd:
                return resp
        return ("", "", 0)


class FakeSftp:
    def __init__(self):
        self.puts = []
        self.putfos = []

    def put(self, local, remote):
        self.puts.append((local, remote))

    def putfo(self, fileobj, remote):
        self.putfos.append((fileobj.read().decode("utf-8"), remote))


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_file_state_missing_when_remote_absent(tmp_path):
    local = _write(tmp_path, "api.py", "print(1)")
    run = FakeRun({"md5sum": ("", "No such file", 1)})
    assert ad.file_state(run, local, "/home/shkim1/hana_p/api.py") == "없음"


def test_file_state_same_when_md5_matches(tmp_path):
    local = _write(tmp_path, "api.py", "print(1)")
    digest = hashlib.md5(b"print(1)").hexdigest()
    run = FakeRun({"md5sum": (f"{digest}\n", "", 0)})
    assert ad.file_state(run, local, "/home/shkim1/hana_p/api.py") == "동일"


def test_file_state_differs_when_md5_differs(tmp_path):
    local = _write(tmp_path, "api.py", "print(1)")
    run = FakeRun({"md5sum": ("0" * 32 + "\n", "", 0)})
    assert ad.file_state(run, local, "/home/shkim1/hana_p/api.py") == "다름"


def test_file_state_normalizes_crlf_before_hashing(tmp_path):
    # 로컬은 Windows다. CRLF 때문에 매번 '다름'으로 보이면 대조가 무의미해진다.
    local = tmp_path / "api.py"
    local.write_bytes(b"print(1)\r\nprint(2)\r\n")
    digest = hashlib.md5(b"print(1)\nprint(2)\n").hexdigest()
    run = FakeRun({"md5sum": (f"{digest}\n", "", 0)})
    assert ad.file_state(run, local, "/x/api.py") == "동일"


def test_upload_files_backs_up_existing_remote_file_before_overwrite(tmp_path):
    local = _write(tmp_path, "api.py", "print(1)")
    entry = _entry(local_dir=".", files=["api.py"])
    run = FakeRun({"md5sum": ("0" * 32 + "\n", "", 0)})
    sftp = FakeSftp()
    ad.upload_files(sftp, run, entry, tmp_path, HOME, log=lambda m: None)
    assert any("cp -p /home/shkim1/hana_p/api.py /home/shkim1/hana_p/api.py.bak-" in c
               for c in run.calls)
    assert sftp.puts == [(str(local), "/home/shkim1/hana_p/api.py")]


def test_upload_files_skips_backup_when_remote_missing(tmp_path):
    _write(tmp_path, "api.py", "print(1)")
    entry = _entry(local_dir=".", files=["api.py"])
    run = FakeRun({"md5sum": ("", "No such file", 1)})
    ad.upload_files(FakeSftp(), run, entry, tmp_path, HOME, log=lambda m: None)
    assert not any("cp -p" in c for c in run.calls)


def test_upload_files_skips_identical_file(tmp_path):
    # 같은 파일을 매번 올리면 백업만 쌓인다.
    _write(tmp_path, "api.py", "print(1)")
    digest = hashlib.md5(b"print(1)").hexdigest()
    entry = _entry(local_dir=".", files=["api.py"])
    sftp = FakeSftp()
    count = ad.upload_files(sftp, FakeRun({"md5sum": (f"{digest}\n", "", 0)}),
                            entry, tmp_path, HOME, log=lambda m: None)
    assert count == 0
    assert sftp.puts == []


def test_upload_files_raises_when_local_file_missing(tmp_path):
    # 선언만 하고 api.py를 안 만든 경우 조용히 넘어가면 '배포됐다'고 착각한다.
    entry = _entry(local_dir=".", files=["api.py"])
    with pytest.raises(FileNotFoundError):
        ad.upload_files(FakeSftp(), FakeRun(), entry, tmp_path, HOME, log=lambda m: None)
```

`pytest.raises`를 쓰므로 파일 상단에 `import pytest`를 추가한다.

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `pytest tests/test_adapter_deploy.py -k "file_state or upload_files" -v`
Expected: FAIL — `AttributeError: module 'adapter_deploy' has no attribute 'file_state'`

- [ ] **Step 3: 최소 구현을 작성한다**

`adapter_deploy.py`에 추가한다. 상단 import에 `import hashlib`을 더한다.

```python
def _local_md5(path: Path) -> str:
    # 로컬은 Windows라 CRLF가 섞인다. 서버 파일은 LF이므로 정규화하고 비교한다.
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.md5(data).hexdigest()


def file_state(run, local: Path, remote: str) -> str:
    out, _, rc = run(f"md5sum {remote} 2>/dev/null | cut -d' ' -f1")
    digest = out.strip()
    if rc != 0 or not digest:
        return "없음"
    return "동일" if digest == _local_md5(local) else "다름"


def upload_files(sftp, run, entry: dict, root: Path, home: str, log) -> int:
    """변경된 파일만 올린다. 덮어쓰기 전에 원격 백업을 남긴다."""
    uploaded = 0
    for local, remote in upload_pairs(entry, root, home):
        if not local.exists():
            raise FileNotFoundError(f"로컬 파일이 없습니다: {local}")
        state = file_state(run, local, remote)
        if state == "동일":
            log(f"= {remote} (동일, 건너뜀)")
            continue
        if state == "다름":
            backup = backup_name(remote)
            run(f"cp -p {remote} {backup}")
            log(f"↩ 백업: {backup}")
        sftp.put(str(local), remote)
        log(f"↑ {remote}")
        uploaded += 1
    return uploaded
```

- [ ] **Step 4: 테스트가 통과하는 것을 확인한다**

Run: `pytest tests/test_adapter_deploy.py -v`
Expected: PASS

- [ ] **Step 5: 커밋한다**

```bash
git add adapter_deploy.py tests/test_adapter_deploy.py
git commit -m "어댑터 배포: 원격 대조와 백업 후 업로드"
```

---

### Task 5: 의존성 설치 가드와 유닛 등록

**Files:**
- Modify: `adapter_deploy.py`
- Test: `tests/test_adapter_deploy.py`

**Interfaces:**
- Consumes: Task 3의 `remote_dir()`, `unit_path()`, `unit_text()`
- Produces:
  - `pip_dry_run(run, entry, home) -> tuple[bool, str]` — (안전한가, 사람이 읽을 요약). `Would uninstall`이 하나라도 있으면 False
  - `install_pip(sftp, run, entry, home, log) -> bool`
  - `register_unit(sftp, run, entry, home, log) -> bool` — 유닛 업로드 + `daemon-reload` + `enable`. **기동하지 않는다**

- [ ] **Step 1: 실패하는 테스트를 작성한다**

```python
def test_pip_dry_run_allows_pure_additions():
    run = FakeRun({"--dry-run": ("Would install fastapi-0.138.0 uvicorn-0.42.0\n", "", 0)})
    ok, msg = ad.pip_dry_run(run, _entry(), HOME)
    assert ok is True
    assert "fastapi-0.138.0" in msg


def test_pip_dry_run_blocks_when_existing_package_would_be_removed():
    # starlette 다운그레이드가 streamlit을 깨뜨린 사례가 있다. 설치 전에 막는다.
    run = FakeRun({"--dry-run": ("Would uninstall starlette-1.3.1\nWould install starlette-0.49.3\n", "", 0)})
    ok, msg = ad.pip_dry_run(run, _entry(), HOME)
    assert ok is False
    assert "starlette" in msg


def test_pip_dry_run_uses_repo_venv_pip():
    run = FakeRun()
    ad.pip_dry_run(run, _entry(), HOME)
    assert any("/home/shkim1/hana_p/venv/bin/pip install --dry-run" in c for c in run.calls)


def test_pip_dry_run_never_uses_requirements_file():
    # -r requirements.txt는 streamlit 등 돌고 있는 앱의 핀까지 움직인다.
    run = FakeRun()
    ad.pip_dry_run(run, _entry(), HOME)
    assert not any("-r " in c for c in run.calls)


def test_install_pip_aborts_when_dry_run_blocks():
    run = FakeRun({"--dry-run": ("Would uninstall starlette-1.3.1\n", "", 0)})
    assert ad.install_pip(FakeSftp(), run, _entry(), HOME, log=lambda m: None) is False
    assert not any("install fastapi" in c and "--dry-run" not in c for c in run.calls)


def test_register_unit_uploads_unit_and_enables_without_starting():
    run = FakeRun()
    sftp = FakeSftp()
    assert ad.register_unit(sftp, run, _entry(), HOME, log=lambda m: None) is True
    joined = " ".join(run.calls)
    assert "systemctl --user daemon-reload" in joined
    assert "systemctl --user enable hana-adapter.service" in joined
    assert "start" not in joined and "restart" not in joined
    assert sftp.putfos[0][1] == "/home/shkim1/.config/systemd/user/hana-adapter.service"


def test_register_unit_never_uses_sudo():
    run = FakeRun()
    ad.register_unit(FakeSftp(), run, _entry(), HOME, log=lambda m: None)
    assert not any("sudo" in c for c in run.calls)
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `pytest tests/test_adapter_deploy.py -k "pip or register_unit" -v`
Expected: FAIL — `AttributeError: module 'adapter_deploy' has no attribute 'pip_dry_run'`

- [ ] **Step 3: 최소 구현을 작성한다**

유닛 파일은 SFTP로 직접 올린다(heredoc으로 쉘에 넘기면 한글 `Description`이 인코딩 문제를 낸다). 로컬 임시 파일을 만들지 않도록 `io.BytesIO`를 쓴다. 상단 import에 `import io`를 더한다.

```python
def _pip(entry: dict, home: str) -> str:
    return f"{remote_dir(entry, home)}/venv/bin/pip"


def pip_dry_run(run, entry: dict, home: str) -> tuple:
    """설치가 기존 패키지를 건드리는지 미리 본다.

    'Would uninstall'이 하나라도 보이면 막는다 — fastapi 핀을 잘못 잡아 starlette이
    내려가면 그 venv로 돌고 있는 streamlit 앱이 깨진다."""
    pkgs = " ".join(entry["deploy"].get("pip", []))
    if not pkgs:
        return True, "설치할 패키지 없음"
    out, err, _ = run(f"{_pip(entry, home)} install --dry-run {pkgs} 2>&1", timeout=240)
    text = (out or "") + (err or "")
    lines = [ln.strip() for ln in text.splitlines()
             if "Would install" in ln or "Would uninstall" in ln]
    summary = "\n".join(lines) or text.strip()[-300:]
    if "Would uninstall" in text:
        return False, summary
    return True, summary


def install_pip(sftp, run, entry: dict, home: str, log) -> bool:
    pkgs = " ".join(entry["deploy"].get("pip", []))
    if not pkgs:
        return True
    ok, summary = pip_dry_run(run, entry, home)
    log(f"· dry-run: {summary}")
    if not ok:
        log("❌ 기존 패키지가 제거/다운그레이드됩니다. 설치를 중단합니다.")
        return False
    out, err, rc = run(f"{_pip(entry, home)} install {pkgs} 2>&1", timeout=600)
    if rc == 0:
        log("✅ 의존성 설치 완료")
        return True
    log(f"❌ 설치 실패:\n{((out or '') + (err or '')).strip()[-400:]}")
    return False


def register_unit(sftp, run, entry: dict, home: str, log) -> bool:
    """유닛을 올리고 등록만 한다. 기동은 재시작 버튼의 몫이다."""
    path = unit_path(entry, home)
    run(f"mkdir -p {home}/.config/systemd/user")
    sftp.putfo(io.BytesIO(unit_text(entry, home).encode("utf-8")), path)
    log(f"↑ {path}")
    _, err, rc = run("systemctl --user daemon-reload")
    if rc != 0:
        log(f"❌ daemon-reload 실패: {err.strip()}")
        return False
    _, err, rc = run(f"systemctl --user enable {entry['deploy']['unit']}")
    if rc != 0:
        log(f"❌ enable 실패: {err.strip()}")
        return False
    log("✅ 유닛 등록 완료 (기동은 재시작 버튼으로)")
    return True
```

- [ ] **Step 4: 테스트가 통과하는 것을 확인한다**

Run: `pytest tests/test_adapter_deploy.py -v`
Expected: PASS

- [ ] **Step 5: 커밋한다**

```bash
git add adapter_deploy.py tests/test_adapter_deploy.py
git commit -m "어댑터 배포: 설치 가드(dry-run)와 유닛 등록"
```

---

### Task 6: 재시작과 상태 확인

**Files:**
- Modify: `adapter_deploy.py`
- Test: `tests/test_adapter_deploy.py`

**Interfaces:**
- Consumes: Task 5의 `register_unit()`
- Produces:
  - `restart_unit(run, entry, home, log) -> bool`
  - `needs_first_visit(entry) -> bool` — `mode == "thread"`면 True
  - `service_state(run, entry) -> str`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

```python
def test_restart_unit_calls_systemctl_restart():
    run = FakeRun()
    assert ad.restart_unit(run, _entry(), HOME, log=lambda m: None) is True
    assert any("systemctl --user restart hana-adapter.service" in c for c in run.calls)


def test_restart_unit_reports_failure_with_journal_hint():
    run = FakeRun({"restart": ("", "Job failed", 1)})
    msgs = []
    assert ad.restart_unit(run, _entry(), HOME, log=msgs.append) is False
    assert any("journalctl --user -u hana-adapter.service" in m for m in msgs)


def test_service_state_returns_systemctl_output():
    run = FakeRun({"is-active": ("active\n", "", 0)})
    assert ad.service_state(run, _entry()) == "active"


def test_service_state_returns_inactive_on_nonzero_exit():
    run = FakeRun({"is-active": ("inactive\n", "", 3)})
    assert ad.service_state(run, _entry()) == "inactive"


def test_needs_first_visit_true_for_thread_mode():
    # Streamlit은 누가 페이지를 열어야 app.py를 실행한다. 재시작만으로는 어댑터가 안 뜬다.
    assert ad.needs_first_visit(_entry(mode="thread")) is True


def test_needs_first_visit_false_for_service_mode():
    assert ad.needs_first_visit(_entry(mode="service")) is False
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `pytest tests/test_adapter_deploy.py -k "restart or service_state or first_visit" -v`
Expected: FAIL — `AttributeError: module 'adapter_deploy' has no attribute 'restart_unit'`

- [ ] **Step 3: 최소 구현을 작성한다**

```python
def restart_unit(run, entry: dict, home: str, log) -> bool:
    unit = entry["deploy"]["unit"]
    _, err, rc = run(f"systemctl --user restart {unit}", timeout=60)
    if rc != 0:
        log(f"❌ 재시작 실패: {err.strip()}")
        log(f"   로그 확인: journalctl --user -u {unit} -n 50 --no-pager")
        return False
    log(f"🔄 {unit} 재시작")
    return True


def service_state(run, entry: dict) -> str:
    out, _, _ = run(f"systemctl --user is-active {entry['deploy']['unit']}")
    return out.strip() or "unknown"


def needs_first_visit(entry: dict) -> bool:
    """thread 모드는 Streamlit이 페이지를 열어야 app.py를 실행하므로, 서비스를
    재시작해도 첫 접속 전까지 어댑터 스레드가 뜨지 않는다."""
    return entry["deploy"]["mode"] == "thread"
```

- [ ] **Step 4: 테스트 전체를 돌린다**

Run: `pytest`
Expected: PASS — 기존 테스트 포함 전부 통과

- [ ] **Step 5: 커밋한다**

```bash
git add adapter_deploy.py tests/test_adapter_deploy.py
git commit -m "어댑터 배포: 재시작과 서비스 상태 조회"
```

---

### Task 7: 설정 페이지 `🔌 어댑터 배포` 섹션

**Files:**
- Modify: `pages/설정.py` (파일 끝에 추가)
- Test: `tests/test_settings_adapter_section.py` (신규)

**Interfaces:**
- Consumes: `orchestrator_registry.deploy_targets()`, `adapter_deploy.*`, `orchestrator_executor.check_health()`, 기존 `_ssh_connect()`/`_ssh_run()`
- Produces: 화면만. 다른 모듈이 의존하지 않는다

**주의:** 기존 `_ssh_run(ssh, cmd, timeout=120)`은 `ssh`를 첫 인자로 받는다. `adapter_deploy`는 `run(cmd, timeout)` 규약을 기대하므로 페이지에서 감싸 넘긴다.

- [ ] **Step 1: 페이지에 섹션을 추가한다**

상단 import에 세 줄을 더한다.

```python
from orchestrator_registry import load_registry, deploy_targets
from orchestrator_executor import check_health
import adapter_deploy as ad
```

파일 맨 끝에 추가한다.

```python
# ── 어댑터 배포 ─────────────────────────────────────────────
# 포털 배포와 분리한다. 한 버튼에 묶으면 포털을 한 줄 고쳐 배포할 때마다 사내에서
# 쓰는 렉스·폴리가 재시작된다.
st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
st.subheader("🔌 어댑터 배포")
st.caption(f"대상: 배포 서버 `{_DEPLOY_HOST}` · 업로드와 재시작은 분리돼 있습니다.")

_targets = deploy_targets(load_registry())
_HOME = f"/home/{_DEPLOY_USER}"


def _adapter_run_factory(ssh):
    def _run(cmd, timeout=120):
        return _ssh_run(ssh, cmd, timeout=timeout)
    return _run


def _adapter_action(keys, do_restart):
    box = st.empty()
    lines = []

    def log(msg):
        lines.append(msg)
        box.code("\n".join(lines[-60:]), language=None)

    try:
        ssh = _ssh_connect()
        run = _adapter_run_factory(ssh)
        sftp = ssh.open_sftp()
        for key in keys:
            entry = _targets[key]
            log(f"\n--- {key} ({entry['agent_name']}) ---")
            if do_restart:
                if ad.restart_unit(run, entry, _HOME, log) and ad.needs_first_visit(entry):
                    log("⚠️ Streamlit은 누군가 페이지를 열어야 app.py를 실행합니다.")
                    log("   해당 에이전트 화면을 한 번 열고 상태를 새로고침하세요.")
            else:
                ad.upload_files(sftp, run, entry, ROOT, _HOME, log)
                if ad.install_pip(sftp, run, entry, _HOME, log):
                    ad.register_unit(sftp, run, entry, _HOME, log)
        sftp.close()
        ssh.close()
        log("\n완료")
    except Exception as e:
        log(f"\n❌ 오류: {e}")


if not _DEPLOY_HOST:
    st.info(".env에 DEPLOY_HOST가 없어 어댑터 배포를 할 수 없습니다.")
elif not _targets:
    st.info("레지스트리에 deploy 블록이 선언된 항목이 없습니다.")
else:
    _selected = []
    for _key, _entry in _targets.items():
        c_sel, c_name, c_state, c_up, c_re = st.columns([0.6, 2, 2, 1, 1])
        with c_sel:
            if st.checkbox("선택", value=False, key=f"ad_sel_{_key}", label_visibility="collapsed"):
                _selected.append(_key)
        with c_name:
            _warn = " ⚠️재시작=사용자 끊김" if _entry["deploy"]["mode"] == "thread" else ""
            st.markdown(f"**{_entry['agent_name']}** `{_key}` · {_entry['api_port']}{_warn}")
        with c_state:
            st.caption(st.session_state.get(f"ad_state_{_key}", "상태 미확인"))
        with c_up:
            if st.button("업로드", key=f"ad_up_{_key}", use_container_width=True):
                _adapter_action([_key], do_restart=False)
        with c_re:
            if st.button("재시작", key=f"ad_re_{_key}", use_container_width=True):
                _adapter_action([_key], do_restart=True)

    c_a, c_b, c_c = st.columns(3)
    with c_a:
        if st.button("선택 업로드", use_container_width=True, disabled=not _selected):
            _adapter_action(_selected, do_restart=False)
    with c_b:
        if st.button("선택 재시작", use_container_width=True, disabled=not _selected):
            _adapter_action(_selected, do_restart=True)
    with c_c:
        if st.button("🔄 상태 새로고침", use_container_width=True):
            for _key, _entry in _targets.items():
                _h = check_health(_entry, _DEPLOY_HOST)
                if _h["ok"]:
                    _counts = ", ".join(f"{k} {v}" for k, v in _h["corpus_counts"].items())
                    st.session_state[f"ad_state_{_key}"] = f"🟢 {_counts or '정상'}"
                else:
                    st.session_state[f"ad_state_{_key}"] = f"🔴 {_h['error']}"
            st.rerun()
```

- [ ] **Step 2: 테스트를 작성한다**

먼저 `tests/test_orchestrator_page.py`를 열어 AppTest 구성과 admin 우회 방식을 확인하고 그대로 따른다.

```python
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).parent.parent))

PAGE = str(Path(__file__).parent.parent / "pages" / "설정.py")


def _run_page():
    at = AppTest.from_file(PAGE, default_timeout=30)
    at.session_state["_client_ip"] = "127.0.0.1"
    return at.run()


def test_settings_page_renders_adapter_section():
    at = _run_page()
    assert not at.exception
    assert "🔌 어댑터 배포" in [s.value for s in at.subheader]


def test_adapter_section_lists_every_deploy_target():
    at = _run_page()
    body = " ".join(m.value for m in at.markdown)
    for key in ("lex", "policy", "hana", "radar"):
        assert f"`{key}`" in body


def test_thread_mode_rows_carry_restart_warning():
    at = _run_page()
    body = " ".join(m.value for m in at.markdown)
    assert body.count("⚠️재시작=사용자 끊김") == 2  # 렉스·폴리만
```

- [ ] **Step 3: 테스트를 돌린다**

Run: `pytest tests/test_settings_adapter_section.py -v`
Expected: PASS. 접근 게이트에 막히면 `at.exception`을 출력해 원인을 보고, `test_orchestrator_page.py`가 쓰는 우회 방식을 그대로 적용한다.

- [ ] **Step 4: 앱을 띄워 눈으로 확인한다**

Run: `python -m streamlit run app.py --server.address 192.168.14.222 --server.port 9000`
Expected: 설정 페이지에 `🔌 어댑터 배포` 섹션과 4줄이 보인다. **아직 버튼을 누르지 않는다** — Task 9에서 순서대로 누른다.

- [ ] **Step 5: 커밋한다**

```bash
git add pages/설정.py tests/test_settings_adapter_section.py
git commit -m "설정 페이지에 어댑터 배포 섹션 추가"
```

---

### Task 8: 어댑터 리포 4개의 `requirements.txt` 핀 교정

**Files:**
- Modify: `../LexAgent/requirements.txt`, `../PolicyAgent/requirements.txt`, `../hana_p/requirements.txt`, `../AiAxRadar/requirements.txt`

**Interfaces:**
- Consumes: 없음
- Produces: 없음(문서성 수정). 레지스트리 `deploy.pip`과 값이 일치해야 한다

네 파일 모두 `fastapi==0.121.2` / `uvicorn==0.49.0`으로 적혀 있는데, 로컬에서 실제로 검증된 조합은 `fastapi 0.138.0` / `uvicorn 0.42.0`이다. 적힌 핀대로 설치하면 starlette이 내려가 streamlit이 깨진다.

- [ ] **Step 1: 현재 값을 확인한다**

```bash
cd "C:/Users/USER/Desktop/Project Agent"
grep -n "fastapi\|uvicorn" LexAgent/requirements.txt PolicyAgent/requirements.txt hana_p/requirements.txt AiAxRadar/requirements.txt
```

- [ ] **Step 2: 네 파일을 고친다**

각 파일에서 두 줄을 아래로 바꾼다. 다른 줄은 건드리지 않는다.

```
fastapi==0.138.0
uvicorn==0.42.0
```

- [ ] **Step 3: 로컬 설치 버전과 일치하는지 확인한다**

Run: `python -m pip list | grep -iE "^(fastapi|uvicorn|starlette) "`
Expected: `fastapi 0.138.0`, `uvicorn 0.42.0`, `starlette 1.3.1`

- [ ] **Step 4: 레지스트리와 일치하는지 확인한다**

Run: `cd "C:/Users/USER/Desktop/Project Agent/AgentPortal" && pytest tests/test_orchestrator_registry.py -k pins -v`
Expected: PASS

- [ ] **Step 5: 각 리포에서 커밋한다**

네 리포는 별도 git 저장소이고 전부 `feature/orchestrator-adapter` 브랜치에 있다. `hana_p`는 커밋되지 않은 변경이 3건 있으니 **`requirements.txt`만 지정해 커밋한다.**

```bash
for d in LexAgent PolicyAgent hana_p AiAxRadar; do
  git -C "C:/Users/USER/Desktop/Project Agent/$d" add requirements.txt
  git -C "C:/Users/USER/Desktop/Project Agent/$d" commit -m "fastapi 핀을 검증된 0.138.0으로 교정 — 0.121.2는 starlette을 내려 streamlit을 깨뜨린다"
done
```

---

### Task 9: 실제 적용 (런북)

**Files:** 없음 — 서버 작업이다. 각 단계 후 결과를 사람이 확인한다.

**Interfaces:**
- Consumes: Task 1~8 전부
- Produces: 서버에서 동작하는 어댑터 4개

**중단 조건:** 어느 단계든 `/health`가 실패하면 다음으로 넘어가지 않는다. 롤백 후 원인을 본다.

- [ ] **Step 1: 프니·에리를 업로드한다 (무중단)**

설정 페이지에서 `hana`, `radar`만 선택 → `선택 업로드`.
Expected: `↑ /home/shkim1/hana_p/api.py`, dry-run 요약, `✅ 의존성 설치 완료`, `✅ 유닛 등록 완료`. 기존 앱은 건드리지 않으므로 7000/4001은 그대로 살아 있어야 한다.

- [ ] **Step 2: 프니·에리를 기동한다**

`hana`, `radar` 선택 → `선택 재시작` → `🔄 상태 새로고침`.
Expected: 두 줄 다 🟢 + 코퍼스 건수. 실패하면 `journalctl --user -u hana-adapter.service -n 50 --no-pager`.

- [ ] **Step 3: 기존 앱이 멀쩡한지 확인한다**

브라우저로 `http://192.168.10.169:7000`, `:4001` 접속.
Expected: 평소대로 뜬다.

- [ ] **Step 4: 포털을 배포한다**

설정 페이지의 기존 `🚀 서버에 배포`.
Expected: 포털(9000) 재시작 후 배포본에 오케스트레이터 페이지가 생긴다. 프니·에리 🟢, 렉스·폴리 🔴(아직 어댑터 없음).

- [ ] **Step 5: 프니·에리만으로 실제 질문을 던져 본다**

배포본 오케스트레이터에서 "최근 부동산 정책 동향 알려줘".
Expected: 두 에이전트가 답하고 합성된다. 이 시점에 서버에서 오케스트레이터가 처음으로 실제 동작한다.

- [ ] **Step 6: 폴리가 환경변수를 요구하는지 확인한다**

서버 `PolicyAgent`에는 `.env`가 없다(다른 세 리포에는 있다). 로컬 `api.py`가 읽는
환경변수를 먼저 본다.

```bash
grep -n "getenv\|environ" "C:/Users/USER/Desktop/Project Agent/PolicyAgent/api.py"
```

읽는 변수가 있으면 그 키만 담은 `.env`를 서버 `~/PolicyAgent/`에 올린다. 없으면
아무 것도 하지 않는다. 이 확인 없이 재시작하면 폴리 어댑터가 기동 직후 죽는다.

- [ ] **Step 7: 렉스·폴리를 업로드한다 (업무 시간 외)**

`lex`, `policy` 선택 → `선택 업로드`.
Expected: `↩ 백업: /home/shkim1/LexAgent/app.py.bak-...` 후 `↑ app.py`, `↑ api.py`. dry-run에 `Would uninstall`이 없어야 한다. **아직 재시작하지 않는다** — 올려둔 상태에서는 기존 프로세스가 그대로 돌아 사용자 영향이 없다.

- [ ] **Step 8: 기존 nohup 프로세스를 정리하고 서비스로 전환한다**

서버에서 현재 명령을 기록해 두고(롤백용) 종료한다.

```bash
ps -eo pid,cmd | grep -E "port (9001|9002)" | grep -v grep   # 기록해 둘 것
kill <lex_pid> <policy_pid>
```

그다음 설정 페이지에서 `lex`, `policy` → `선택 재시작`.

- [ ] **Step 9: 페이지를 한 번 열어 어댑터 스레드를 띄운다**

브라우저로 `http://192.168.10.169:9001`, `:9002` 접속 → `🔄 상태 새로고침`.
Expected: 네 줄 모두 🟢. 페이지를 열기 전까지 🔴인 것이 정상이다.

- [ ] **Step 10: 재부팅 복구를 검증한다**

Run: `systemctl --user is-enabled lexagent.service policyagent.service hana-adapter.service radar-adapter.service`
Expected: 네 줄 다 `enabled`. (실제 재부팅은 하지 않는다.)

- [ ] **Step 11: 배포본에서 4개 합성을 확인한다**

오케스트레이터에서 "처리방침 개정할 때 최근 법령 중 반영해야 할 게 있나?".
Expected: 폴리·렉스가 함께 답하고 인용이 붙는다.

---

### Task 10: 문서 갱신

**Files:**
- Modify: `README.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: Task 9의 실제 결과
- Produces: 없음

`CLAUDE.md`에는 오케스트레이터 관련 내용이 아직 한 줄도 없다(포털/설정/버전이력/로그만 있다).

- [ ] **Step 1: `CLAUDE.md`의 Architecture에 항목을 추가한다**

```markdown
- **`orchestrator_*.py` + `data/orchestrator_registry.json`** — 질문 하나로 관련 에이전트를 골라 병렬 호출하고 답을 합성하는 서브시스템(`pages/오케스트레이터.py`, 관리자 전용). 라우터가 읽는 것은 코드가 아니라 레지스트리의 `role`/`when_to_use`/`when_not_to_use`이고, 에이전트 추가는 레지스트리 항목 1개 + 해당 리포의 `api.py`로 끝난다. 루트 모듈을 고치면 Streamlit이 이미 임포트한 모듈을 다시 읽지 않으므로 **포털을 재시작해야 한다**(`AttributeError`로 드러남).
- **`adapter_deploy.py`** — 어댑터를 배포 서버에 올리고 user systemd(`systemctl --user`, sudo 없음)로 상주시킨다. 레지스트리의 `deploy` 블록만 읽으므로 에이전트가 늘어도 이 코드는 안 바뀐다. 서버 설치는 `deploy.pip`에 적힌 패키지만 개별 설치하며 **`pip install -r requirements.txt`를 쓰지 않는다** — 돌고 있는 앱의 streamlit 핀까지 움직인다. 렉스·폴리는 Qdrant 로컬 파일 모드가 저장소를 한 프로세스만 열게 해서 어댑터가 앱 안 스레드로 뜨고, 그래서 **Streamlit 특성상 누군가 페이지를 한 번 열어야 어댑터가 살아난다**.
```

- [ ] **Step 2: `README.md`의 어댑터 절에 서버 운영 내용을 더한다**

```markdown
### 배포 서버에서의 어댑터

가상화 서버에서는 user systemd 서비스로 상주합니다(`sudo` 없이 `linger=yes`).

| 키 | 유닛 | 기동 대상 |
|---|---|---|
| `lex` | `lexagent.service` | 앱 자체(어댑터 스레드 포함) |
| `policy` | `policyagent.service` | 앱 자체(어댑터 스레드 포함) |
| `hana` | `hana-adapter.service` | 어댑터만 |
| `radar` | `radar-adapter.service` | 어댑터만 |

갱신은 설정 페이지의 `🔌 어댑터 배포`에서 합니다. 업로드와 재시작이 분리돼 있어,
올려두었다가 업무 시간이 끝난 뒤 재시작할 수 있습니다. 렉스·폴리는 재시작 후
페이지를 한 번 열어야 어댑터가 뜹니다.
```

- [ ] **Step 3: 커밋한다**

```bash
git add README.md CLAUDE.md
git commit -m "어댑터 서버 운영 내용을 README·CLAUDE.md에 반영"
```

---

## 이 계획이 끝난 뒤의 상태

- 배포 서버에서 오케스트레이터가 4개 에이전트로 실제 동작한다
- 어댑터 갱신이 설정 페이지 버튼 두 개(업로드/재시작)로 끝난다
- 재부팅해도 네 서비스가 자동으로 돌아온다
- 에이전트를 추가할 때 배포 코드는 고치지 않는다 — 레지스트리 `deploy` 블록 1개면 된다

## 후속 (별도 계획)

1. **삼일 `chat_answer`** — 없는 기능을 새로 만든 뒤 어댑터 + 레지스트리 항목 추가(포트 9601)
2. **마인 추가** — 레지스트리 1줄
3. **`feature/orchestrator-core` → master 병합**
