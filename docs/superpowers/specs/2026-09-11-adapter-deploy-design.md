# 어댑터 배포·운영 설계 (가상화 서버)

작성일: 2026-09-11
관련: [2026-09-09 오케스트레이터 설계](2026-09-09-orchestrator-design.md)

## 배경

오케스트레이터 코어와 어댑터 4개(렉스·폴리·프니·에리)는 2026-09-10에 로컬
(192.168.14.222)에서 종단 동작까지 끝났다. 그러나 어댑터가 전부 개발 PC에만 살아 있어
**배포 서버(192.168.10.169)의 포털에서는 오케스트레이터가 답을 하지 못한다.**

9/9 설계 문서는 "배포 서버에서 어댑터를 어떻게 띄울지는 이 설계 범위 밖의 별도 결정"
이라고 미뤄두었다. 이 문서가 그 결정이다.

## 범위

- 어댑터 4개를 배포 서버에 올리고 상주시키는 방식
- AgentPortal 설정 페이지에서 그 배포를 수행하는 UI와 절차
- 레지스트리에 배포 정보를 선언하는 스키마

범위 밖: 삼일(tax) `chat_answer` 신규 구현, 마인 추가, `feature/orchestrator-core`의
master 병합.

## 조사로 확인된 서버 현황 (2026-09-11, 읽기 전용 점검)

Rocky Linux 9.8, 4코어, 메모리 15Gi(available 8.4Gi, swap 8Gi 중 2.5Gi 사용),
디스크 141G 중 73G 여유, uptime 101일, Python 3.11.13, SELinux Disabled.

| 포트 | 리포 | RSS |
|---|---|---|
| 9000 | AgentPortal | 74M |
| 9001 | LexAgent | 2.3Gi |
| 9002 | PolicyAgent | 1.9Gi |
| 9003 | GosiAgent | 372M |
| 7000 | hana_p | 654M |
| 4001 | ai_news_radar | 701M |
| 9101 | ProptierAI | 460M |
| 3100 | MarketInsight | 269M |
| 8501 / 7001 | 수집_웹허브 / day_work_system_6 | 407M / 149M |

재조사 불필요한 사실:

- **어댑터 포트 9501·9502·7500·4501과 삼일용 9601이 전부 비어 있다.** 로컬과 같은 포트를
  쓸 수 있어 레지스트리에 환경별 포트 분기가 필요 없다.
- **서버 리포는 전부 git이 아닌 수동 복사본이다**(AgentPortal 포함). `git pull`은
  선택지가 아니며, 기존 AgentPortal 배포와 같은 SFTP 방식이 유일한 경로다.
- **서버 진입점과 로컬 진입점의 차이는 어댑터 훅뿐이다.** `hana_p/app.py`와
  `ai_news_radar/app/Home.py`는 md5가 같고, `LexAgent/app.py`(96→103줄)와
  `PolicyAgent/app.py`(98→106줄)의 차이는 `from api import start_api_thread` +
  `start_api_thread()` + 주석이 전부다. 서버 쪽에 갈라진 수정은 없어 덮어쓰기가 안전하다.
- **sudo는 비밀번호를 요구한다.** 시스템 서비스는 만들 수 없다. 대신 `linger=yes`이고
  `proptierai.service`가 user systemd 서비스로 이미 동작 중이다.
- 자동 기동 수단이 없다. crontab 없음, 에이전트 관련 시스템 서비스 없음. 9개 앱 중
  ProptierAI만 서비스이고 나머지는 `nohup` 수동 기동이라 101일 uptime에 의존하고 있다.
- 각 리포에 venv가 있고 앱은 그 venv로 돌고 있다(`VIRTUAL_ENV` 확인). PolicyAgent만
  `VIRTUAL_ENV` 없이 venv의 절대경로로 기동돼 있다.
- 서버 `PolicyAgent`에는 `.env`가 없다. 나머지 리포에는 있다.

## 결정

### 1. 포트와 상주 방식

| 키 | 로컬 리포 | 서버 리포 | 어댑터 포트 | 상주 방식 | 재시작 영향 |
|---|---|---|---|---|---|
| `lex` | LexAgent | LexAgent | 9501 | 앱 안 스레드 → `lexagent.service` | 렉스 사용자 끊김 |
| `policy` | PolicyAgent | PolicyAgent | 9502 | 앱 안 스레드 → `policyagent.service` | 폴리 사용자 끊김 |
| `hana` | hana_p | hana_p | 7500 | 별도 프로세스 → `hana-adapter.service` | 없음 |
| `radar` | AiAxRadar | **ai_news_radar** | 4501 | 별도 프로세스 → `radar-adapter.service` | 없음 |

렉스·폴리가 스레드인 이유는 Qdrant 로컬 파일 모드가 저장소 폴더를 한 프로세스만 열게
하기 때문이다(서버 기준 `LexAgent/qdrant_data` 164M, `PolicyAgent/qdrant_data` 297M).
별도 프로세스로 띄우면 검색 자체가 되지 않는다.

메모리 증가분은 프니·에리 어댑터 2개뿐이다. 렉스·폴리는 기존 프로세스 안에서 스레드로
뜨므로 프로세스가 늘지 않는다.

### 2. 상주 관리는 user systemd

sudo 없이 `~/.config/systemd/user/`에 유닛을 두고 `linger=yes`로 재부팅 자동 기동을
얻는다. 기존 `proptierai.service`의 형식을 그대로 따른다.

```ini
[Unit]
Description=LexAgent Streamlit App (오케스트레이터 어댑터 포함)
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/shkim1/LexAgent
ExecStart=/home/shkim1/LexAgent/venv/bin/python -m streamlit run app.py \
  --server.address 0.0.0.0 --server.port 9001 --server.headless true
Restart=on-failure
RestartSec=5
StandardOutput=append:/home/shkim1/LexAgent/streamlit.log
StandardError=append:/home/shkim1/LexAgent/streamlit.log

[Install]
WantedBy=default.target
```

`ExecStart`는 현재 돌고 있는 커맨드라인을 그대로 옮긴 것이다. 프니·에리 어댑터 유닛은
같은 형식에 `ExecStart=<repo>/venv/bin/python api.py`를 쓴다.

렉스·폴리 앱은 지금 `nohup`으로 떠 있다. 전환 시 기존 프로세스를 종료하고 서비스로
다시 띄운다. 실패하면 원래 `nohup` 명령으로 즉시 되돌린다(명령을 기록해 둔다).
프니·에리 **앱**은 건드리지 않는다 — 어댑터만 서비스로 추가된다.

### 3. AgentPortal 배포 버튼과는 분리

설정 페이지에 `🔌 어댑터 배포` 섹션을 새로 만든다. 기존 `🚀 서버 배포`(포털 배포)와
독립이다. 한 버튼에 묶지 않는 이유는, 포털을 한 줄 고쳐 배포할 때마다 사내에서 쓰는
렉스·폴리가 재시작되기 때문이다.

업로드와 재시작도 분리한다. 버튼이 파일을 올리고 유닛을 등록(`daemon-reload` +
`enable`)까지만 하고, 기동은 하지 않는다. 재시작은 별도 버튼이다. 올려둔 채로 두었다가
퇴근 후에 재시작하는 운영이 가능해진다.

UI는 에이전트별 한 줄로 구성한다: 체크박스 · 상태(`/health`의 코퍼스 건수 포함) ·
마지막 업로드 시각 · `[업로드]` · `[재시작]`. 상단에 선택분 일괄 버튼. 렉스·폴리 줄에는
"재시작 = 사용자 끊김" 경고를 단다.

상태 열이 보는 대상은 **항상 배포 서버(`DEPLOY_HOST`)의 어댑터**다. 오케스트레이터
페이지의 "에이전트 확인" 버튼이 현재 환경(`PORTAL_ENV`)의 어댑터를 보는 것과 다르다.
이 섹션은 "서버에 무엇이 올라가 있고 살아 있는가"를 답하는 자리이므로, 로컬에서 열든
배포본에서 열든 같은 대상을 가리켜야 혼동이 없다.

### 4. 배포 정보는 레지스트리에 선언한다

오케스트레이터가 연결을 코드에 박지 않는다는 기존 원칙을 배포에도 적용한다.
`data/orchestrator_registry.json`의 각 항목에 `deploy` 블록을 추가한다.

```json
"hana": {
  "agent_name": "Proptier AI News",
  "api_port": 7500,
  "enabled": true,
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
}
```

- `mode`는 `service`(별도 프로세스) 또는 `thread`(앱 안 스레드)다. `thread`면 `files`에
  진입점(`app.py`)이 포함되고 `unit`은 앱 서비스명이 된다.
- `exec`는 유닛의 `ExecStart`가 될 명령을 `remote_dir` 기준 상대경로로 적는다.
  `service`면 `venv/bin/python api.py`, `thread`면 그 앱을 지금 띄우고 있는 명령
  전체(`venv/bin/python -m streamlit run app.py --server.port 9001 ...`)다. 유닛 내용을
  코드에 박지 않기 위해 레지스트리에 둔다.
- `log`는 `remote_dir` 기준 로그 파일명이며 유닛의 stdout/stderr가 여기 append된다.
- `local_dir`은 AgentPortal 저장소 기준 상대경로, `remote_dir`은 서버 절대/홈 경로다.
  에리처럼 로컬과 서버의 리포 이름이 다른 경우를 이 두 필드가 흡수한다.
- **`deploy` 블록이 없는 항목은 배포 대상에서 조용히 제외한다.** 로컬에서만 쓰는
  에이전트를 허용하기 위해서다. 기존 레지스트리 로더가 불완전한 항목을 조용히 빼는
  방식과 같다.
- 에이전트 추가는 여전히 "레지스트리 1줄 + `api.py`"로 끝난다. 배포 코드는 고치지 않는다.

레지스트리는 포털 배포 시 로컬 것으로 서버를 덮어쓴다. `deploy` 블록도 함께 실리지만
경로가 서버 기준이라 문제가 없다.

## 의존성 — 핀이 틀려 있다

서버 4개 venv에 **fastapi가 하나도 설치돼 있지 않다.** 어댑터는 전부
`from fastapi import FastAPI`를 쓰므로 설치가 필요하다.

그런데 4개 리포의 `requirements.txt`에 적힌 `fastapi==0.121.2`는 **로컬에서 실제로
검증된 버전이 아니다.** 로컬 실환경은 `fastapi 0.138.0` + `starlette 1.3.1` +
`uvicorn 0.42.0`이다. 서버에서 `0.121.2`로 설치하면 그 버전이 `starlette<0.50`을
요구해 **starlette이 1.3.1 → 0.49.3으로 내려간다.** 서버의 starlette은
`Required-by: streamlit`이므로, 이는 렉스·폴리의 Streamlit 앱을 깨뜨릴 수 있다.

dry-run으로 확인한 안전한 조합은 `fastapi==0.138.0` + `uvicorn==0.42.0`이다.

| 리포 | 설치 결과 (dry-run) |
|---|---|
| LexAgent | fastapi, uvicorn만 추가. starlette 1.3.1 그대로 |
| PolicyAgent | fastapi, uvicorn만 추가. starlette 1.3.1 그대로 |
| hana_p | fastapi, uvicorn, starlette 1.6.0, annotated-doc 추가(기존 변경 없음) |
| ai_news_radar | 동일 |

따라서:

1. 4개 리포의 `requirements.txt` 핀을 `fastapi==0.138.0` / `uvicorn==0.42.0`으로 고친다.
2. 서버 설치는 **`pip install -r requirements.txt`를 쓰지 않는다.** 그 파일에는
   `streamlit==1.58.0` 같은 다른 핀이 함께 들어 있어 돌고 있는 앱의 버전을 움직일 수
   있다. 레지스트리 `deploy.pip`에 적힌 패키지만 개별 설치한다.
3. 설치 전 `--dry-run`을 먼저 돌려 "Would install" 목록에 기존 패키지의 다운그레이드가
   없는지 확인하고, 있으면 중단하고 로그에 보여준다.

## 업로드 절차와 안전장치

1. **사전 대조** — 서버 파일과 로컬 파일의 md5를 비교한다. 같으면 건너뛰고, 다르면 몇
   줄 다른지 보여준다.
2. **백업** — 덮어쓸 기존 파일이 있으면 서버에 `app.py.bak-YYYYMMDD-HHMM`으로 남긴다.
3. **업로드** — `deploy.files`의 파일과 유닛 파일을 SFTP로 올린다.
4. **의존성** — `deploy.pip`을 dry-run 후 설치한다.
5. **유닛 등록** — `systemctl --user daemon-reload`, `enable`까지만. 기동하지 않는다.
6. **재시작(별도 버튼)** — `systemctl --user restart` → 3초 후 `/health` 확인 →
   실패 시 백업 파일명과 롤백 명령을 로그에 찍는다.

## Streamlit 스레드 어댑터의 함정

Streamlit은 누군가 페이지를 열어야 `app.py`를 실행한다. 따라서 렉스·폴리는 서비스를
재시작해도 **첫 접속 전까지 어댑터 스레드가 뜨지 않는다.** 재시작 버튼은 이 사실을
안내하고 `/health` 재확인 버튼을 함께 보여준다. 이걸 모르면 "재시작했는데 죽어 있다"로
오진하게 된다.

## 키와 환경변수

서버 `PolicyAgent`에 `.env`가 없다. **확인 결과 문제가 되지 않는다** —
`PolicyAgent/app.py:8`이 `load_dotenv(../LexAgent/.env)`로 렉스의 `.env`를 읽고,
`api.py` 자체는 환경변수를 직접 읽지 않는다. 서버 `LexAgent/.env`는 존재한다.
폴리 리포에 `.env`를 따로 올릴 필요가 없다.

포털 자신의 `ANTHROPIC_API_KEY`(라우터·합성기용)는 기존 배포 플로우가 `.env`를 올리므로
해결된다. 같은 파일에 `DEPLOY_PASS`가 함께 실리는 현재 구조는 이 작업에서 바꾸지 않는다.

## 테스트

- 레지스트리 `deploy` 블록 파싱과 "불완전하면 제외" 규칙 — 기존
  `tests/test_orchestrator_registry.py` 패턴으로 pytest를 추가한다.
- 업로드 대상 목록과 경로 계산은 SSH와 분리된 순수 함수로 만들어 단위 테스트한다.
  SFTP/SSH 실행부는 기존 `_ssh_run`/`_sftp_upload_dir`를 재사용한다.
- 서버 검증은 `/health`의 코퍼스 건수로 한다. 프로세스 생존만으로는 빈 저장소를 붙들고
  정상이라 답하는 상태를 잡지 못한다.

## 적용 순서와 롤백

1. **프니·에리** — 앱 무중단. 새 파일 `api.py` + 유닛만 추가된다. 롤백은 서비스 중지와
   파일 삭제.
2. **포털 배포** — 9000이 수 초 재시작된다. 오케스트레이터 페이지가 서버에 생긴다.
   이 시점에 렉스·폴리는 레지스트리상 `enabled: true`지만 어댑터가 없어 "응답 없음"으로
   보인다(관리자 전용 페이지라 일반 사용자에게는 영향 없음).
3. **렉스·폴리** — 업무 시간 외. `app.py` 덮어쓰기 + nohup → systemd 전환 + 재시작 +
   페이지 1회 접속. 롤백은 백업 파일 복구와 기존 nohup 명령.
4. **삼일** — 별도 계획(`chat_answer` 신규 구현).

## 범위에서 제외한 것

- **서버 리포의 git 전환** — 6개 리포가 전부 수동 복사본이라 git으로 바꾸면 배포 방식
  자체가 달라진다. 이번 작업의 목적이 아니다.
- **프니·에리 앱의 서비스 전환** — 지금 멀쩡히 돌고 있는 앱을 이번 일 때문에 건드릴
  이유가 없다. 어댑터만 서비스로 둔다.
- **`.env`에서 `DEPLOY_PASS` 분리** — 별도 논의.
