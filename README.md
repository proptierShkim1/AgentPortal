# AgentPortal

Proptier의 AI 에이전트들을 한 화면에서 확인하고 이동할 수 있는 중앙 대시보드입니다.

## 개요

개인정보보호·세무·시장분석 등 여러 목적의 AI 에이전트를 각각 따로 접속하지 않고, 포털 한 곳에서 실행 상태를 확인하고 바로 이동할 수 있도록 만들었습니다.

## 관리 중인 에이전트

| 에이전트 | 닉네임 | 역할 |
|---------|--------|------|
| LexAgent | 렉스 | 개인정보 법령 RAG 분석 |
| PolicyAgent | 폴리 | 개인정보 처리방침 분석 |
| GosiAgent | 고시 | 고시 수집 및 알림 |
| ModelTLab | 모델랩 | AI 모델 파인튜닝·채팅 테스트 |
| gov_kr | 고브 | 건축물대장 조회 |
| SonarGuard | 소나 | 코드 취약점 스캐너 |
| AIpartner(세무) | 삼일PWC | 세무 관련 법안 분석 |
| MarketInsight | 마인 | 시장 트렌드 분석 |

카드별 노출 여부(로컬/배포)와 순서는 ⚙️ 설정 페이지에서 관리합니다.

## 기술 스택

- Python + [Streamlit](https://streamlit.io/)
- 배포: paramiko(SSH/SFTP)로 가상화 서버에 코드 업로드 후 원격 기동

## 실행 방법

```bash
pip install -r requirements.txt
python -m streamlit run app.py --server.address 192.168.14.222 --server.port 9000
```

`.streamlit/config.toml`은 배포 서버 전용 설정이라, 로컬에서는 항상 `--server.address`/`--server.port`를 위 명령처럼 직접 지정해야 합니다.

## 접근 권한

`data/access_config.json`에 등록된 IP만 접속할 수 있으며, IP별로 관리자(⚙️ 설정 접근)/이력 열람(📜 버전 이력 접근) 권한을 따로 부여합니다. 등록된 IP가 하나도 없는 초기 상태에서는 전체 허용(부트스트랩 모드)됩니다.

## 테스트

```bash
pip install -r requirements-dev.txt
pytest
```

## 개발 가이드

Claude Code로 이 저장소에서 작업할 때 참고할 아키텍처/명령어 문서는 [`CLAUDE.md`](./CLAUDE.md)를 참고하세요.
