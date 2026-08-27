# AgentPortal

Proptier의 AI 에이전트들을 한 화면에서 확인하고 이동할 수 있는 중앙 대시보드입니다.

## 개요

개인정보보호·세무·시장분석 등 여러 목적의 AI 에이전트를 각각 따로 접속하지 않고, 포털 한 곳에서 실행 상태를 확인하고 바로 이동할 수 있도록 만들었습니다. 로컬 PC와 가상화 배포 서버 양쪽에서 동일한 코드로 동작하며, 환경에 따라 접속 대상 host만 자동으로 전환됩니다.

## 도입 효과

- **기존 방식**: 에이전트별로 개별 주소/포트를 따로 기억·접속해야 했고, 실행 여부도 직접 접속해봐야 확인 가능했음
- **개선 후**: 포털 한 화면에서 카드로 모아 상태 확인·이동, 원클릭 서버 배포로 전환 → 접속 혼선과 수작업 배포 부담 절감
- **현재 상태**: 가상화 서버 배포 완료, 현업 담당자 공유 및 권한 등록 전 단계

## 관리 중인 에이전트

| 에이전트 | 닉네임 | 역할 | 포트 |
|---------|--------|------|------|
| LexAgent | 렉스 | 개인정보 법령 RAG 분석 | 9001 |
| PolicyAgent | 폴리 | 개인정보 처리방침 분석 | 9002 |
| GosiAgent | 고시 | 고시 수집 및 알림 | 9003 |
| ModelTLab | 모델랩 | AI 모델 파인튜닝·채팅 테스트 | 3010 |
| gov_kr | 고브 | 건축물대장 조회 | 1001 |
| SonarGuard | 소나 | 코드 취약점 스캐너 | 2001 |
| AIpartner(세무) | 삼일PWC | 세무 관련 법안 분석 | 9101 |
| MarketInsight | 마인 | 시장 트렌드 분석 | 3100 |
| Proptier AI News | 프니 | 부동산 AI 뉴스 | 7000 |
| DailyBot(6F) | 데일리봇 | 6층 일일 업무 봇 | 7001 |
| AI RADAR | 에리 | 키워드 기반 AI 정보 활용 에이전트 | 4001 |

포트는 로컬/배포 환경 공통이며, host만 환경에 따라 바뀝니다(아래 "로컬 vs 배포" 참고). 카드별 노출 여부(로컬/배포 독립)와 화면상 순서는 ⚙️ 설정 페이지에서 관리합니다.

## 기술 스택

- Python + [Streamlit](https://streamlit.io/) (멀티페이지 앱, 별도 프론트엔드 빌드 없음)
- `paramiko` — SSH/SFTP로 가상화 서버에 코드 업로드 및 원격 기동
- `python-dotenv` — 배포 설정(`.env`) 로드

## 폴더 구조

```
AgentPortal/
├── app.py                   # 진입점 — 관리자/이력열람 권한에 따라 페이지 네비게이션 구성 + 접속 로그 기록
├── agents_data.py           # 관리 대상 에이전트 목록(AGENTS)
├── access_control.py        # IP 등록 목록 기반 관리자/이력열람 권한 판별
├── access_log.py            # 접속(페이지 이동) 로그 기록/조회 로직
├── visibility_config.py     # 카드 노출(로컬/배포)·순서 설정 로직
├── pages/
│   ├── 포털.py               # 메인 대시보드 (에이전트 카드 그리드) — 누구나 접근 가능
│   ├── 설정.py               # 카드 노출/순서 편집 + 서버 배포(관리자 전용)
│   ├── 로그.py               # 접속 IP/행위 로그 뷰어 (검색·필터·페이지네이션, 관리자 전용)
│   └── 버전이력.py            # git 커밋 로그 뷰어(이력 열람 권한자 전용)
├── data/
│   ├── access_config.json   # IP 등록 목록 (git에 커밋됨, 실제 운영값)
│   ├── access_log.jsonl     # 접속 로그 (gitignore 대상, 로컬 전용)
│   └── visibility_config.json
├── scripts/start_server.sh  # 배포 서버에서 Streamlit을 기동하는 스크립트
├── .streamlit/config.toml   # 배포 서버 전용 실행 설정
├── .env                     # 배포 접속 정보 (gitignore 대상, 직접 생성 필요)
└── tests/                   # pytest 테스트
```

## 실행 방법

```bash
pip install -r requirements.txt
python -m streamlit run app.py --server.address 192.168.14.222 --server.port 9000
```

`.streamlit/config.toml`은 배포 서버 전용 설정(`address = "192.168.10.169"`)이라, 로컬 PC에는 그 IP가 없어 그냥 실행하면 바로 `OSError`로 죽습니다. 로컬 확인/개발 시에는 항상 위 명령처럼 `--server.address`/`--server.port`를 직접 지정하세요.

## 로컬 vs 배포 환경

| 구분 | host | 판별 방법 |
|------|------|-----------|
| 로컬 실행 | `192.168.14.222` | `PORTAL_ENV` 환경변수가 `deploy`가 아닐 때(기본값) |
| 가상화 배포 서버 | `192.168.10.169` | `PORTAL_ENV=deploy`로 실행될 때 |

카드의 "실행 중"/"중지됨" 배지와 "이동" 버튼은 이 host 기준으로 소켓 연결을 테스트해 판단합니다.

## 환경 변수 (`.env`)

배포 기능(⚙️ 설정 페이지의 "🚀 서버 배포")을 쓰려면 `.env.example`을 참고해 `.env`를 직접 만들어야 합니다(git에 포함되지 않음).

| 변수 | 설명 |
|------|------|
| `DEPLOY_HOST` | 가상화 배포 서버 IP |
| `DEPLOY_SSH_PORT` | SSH 접속 포트 |
| `DEPLOY_USER` | SSH 접속 계정 |
| `DEPLOY_PASS` | SSH 접속 비밀번호 |
| `DEPLOY_REMOTE_PATH` | 배포 서버 내 코드 경로 |
| `DEPLOY_APP_PORT` | 배포 서버에서 Streamlit이 열릴 포트 |

## 접근 권한

🏢 포털(에이전트 카드) 화면은 누구나 접속·사용할 수 있습니다. `data/access_config.json`에 등록된 IP에는 아래 두 권한을 독립적으로 부여할 수 있고, 이 권한이 있어야만 보이는 화면이 따로 있습니다.

- `is_admin` — ⚙️ 설정 페이지(카드 노출/순서 편집, 서버 배포), 🧾 로그 페이지(접속 IP/행위 조회) 접근 가능
- `can_view_history` — 📜 버전 이력 페이지(git 커밋 로그) 접근 가능

등록된 IP가 하나도 없는 초기 상태에서는 전체 허용되는 부트스트랩 모드로 동작해, 최초 1명이 설정 페이지에서 자기 자신에게 권한을 부여할 수 있습니다.

🧾 로그 페이지는 포털에 접속할 때마다 IP·(등록돼 있다면) 이름·이동한 화면을 `data/access_log.jsonl`에 기록하고, IP/이름 검색·화면 필터·페이지네이션이 있는 목록으로 보여줍니다.

## 배포 방법

⚙️ 설정 페이지(관리자 전용)의 "🚀 서버에 배포" 버튼을 누르면:

1. SSH로 가상화 서버에 접속
2. 코드 파일(`.py`/`.toml`/`.txt`/`.md`/`.sh`)과 `.streamlit`/`scripts`/`pages` 디렉터리, `data/visibility_config.json`만 업로드 (IP 허용 목록이 담긴 `data/access_config.json`은 로컬 값으로 덮어써지지 않도록 배포 대상에서 제외됨)
3. 최초 배포라면 가상환경 생성 및 `requirements.txt` 설치
4. `PORTAL_ENV=deploy`로 Streamlit 재기동

배포 후 서버만 재시작하고 싶을 땐 옆의 "🔄 Streamlit 재시작" 버튼을 사용합니다.

## 테스트

```bash
pip install -r requirements-dev.txt
pytest
```

## 개발 가이드

Claude Code로 이 저장소에서 작업할 때 참고할 아키텍처/명령어 문서는 [`CLAUDE.md`](./CLAUDE.md)를 참고하세요.
