# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Run locally (config.toml is deploy-only, so local runs must always override address/port on the command line):

```
python -m streamlit run app.py --server.address 192.168.14.222 --server.port 9000
```

Run tests:

```
pytest
pytest tests/test_visibility_config.py::test_sort_by_order_reorders_by_explicit_order_value  # single test
```

Install dependencies: `pip install -r requirements.txt -r requirements-dev.txt`

## Architecture

Single Streamlit multi-page app (no build step). `app.py` is the entry point: it resolves the client's IP, then gates navigation via `access_control.py` — everyone gets 포털(portal), `is_admin(ip)` gates 설정(settings), `can_view_history(ip)` gates 버전 이력(version history).

- **`agents_data.py`** — static `AGENTS` list (name, nickname, desc, port, path, icon, color). Agents have no `host` field — host is resolved globally per environment, not per agent.
- **`pages/포털.py`** — main dashboard. `IS_DEPLOYED = os.environ.get("PORTAL_ENV") == "deploy"` selects `AGENT_HOST` between `LOCAL_HOST` (`192.168.14.222`) and `DEPLOY_HOST` (`192.168.10.169`); every agent uses the same port on both hosts, only the host changes. Cards are rendered as one CSS Grid block (`display:grid; grid-template-columns: repeat(auto-fill, 300px)`) built from a single joined HTML string rather than `st.columns()`, so the grid reflows to 3–5 columns based on window width while keeping card size fixed. That HTML must stay a single-line f-string per card — multi-line indented HTML gets misparsed as a Markdown code block by Streamlit's CommonMark renderer and renders as visible source instead of a card.
- **`visibility_config.py`** + `data/visibility_config.json` — per-agent `visible_local`/`visible_deploy`/`order` flags, independent per environment (an agent can be shown locally but hidden on the deployed server, or vice versa).
- **`access_control.py`** + `data/access_config.json` — IP allowlist with `is_admin`/`can_view_history` flags per entry. Bootstrap mode: if zero IPs are registered with a given permission, that permission is granted to everyone (lets the first user reach 설정 to register themselves before any allowlist exists).
- **`pages/설정.py`** — admin-only. Card visibility/order editor (auto-saves to JSON on any change, no separate save button) plus an SSH/SFTP deploy flow (`paramiko`) to the virtualization server, reading `DEPLOY_HOST`/`DEPLOY_SSH_PORT`/`DEPLOY_USER`/`DEPLOY_PASS`/`DEPLOY_REMOTE_PATH`/`DEPLOY_APP_PORT` from `.env`. Deploy uploads only specific root files (`.py`/`.toml`/`.txt`/`.md`/`.sh` + `.env`) and specific directories (`.streamlit`, `scripts`, `pages`) — it deliberately never uploads the whole `data/` directory, because that would overwrite the deploy server's own `access_config.json` with local IP values and lock out real users. Only `data/visibility_config.json` is uploaded individually (local is the source of truth for that file; deploy always overwrites it).
- **`pages/버전이력.py`** — git commit log viewer (author filter, search, pagination), gated by `can_view_history`.
- **`access_log.py`** + `data/access_log.jsonl` (gitignored, local-only) — appends one JSON line per navigation (timestamp, IP, matched name from `access_config.json`, page title) from `app.py`, deduped per session via `st.session_state["_last_logged_page"]` so reruns within the same page don't spam the log. **`pages/로그.py`** — board-style viewer (IP/name search, page filter, pagination), admin-only.
- **`orchestrator_*.py` + `data/orchestrator_registry.json`** — 질문 하나로 관련 에이전트를 골라 병렬 호출하고 답을 합성하는 서브시스템(`pages/오케스트레이터.py`, 관리자 전용). 라우터가 읽는 것은 코드가 아니라 레지스트리의 `role`/`when_to_use`/`when_not_to_use`이고, 에이전트 추가는 레지스트리 항목 1개 + 해당 리포의 `api.py`로 끝난다. 루트 모듈을 고치면 Streamlit이 이미 임포트한 모듈을 다시 읽지 않으므로 **포털을 재시작해야 한다**(`AttributeError`로 드러남).
- **`adapter_deploy.py`** — 어댑터를 배포 서버에 올리고 user systemd(`systemctl --user`, sudo 없음)로 상주시킨다. 레지스트리의 `deploy` 블록만 읽으므로 에이전트가 늘어도 이 코드는 안 바뀐다. 서버 설치는 `deploy.pip`에 적힌 패키지만 개별 설치하며 **`pip install -r requirements.txt`를 쓰지 않는다** — 돌고 있는 앱의 streamlit 핀까지 움직인다. 렉스·폴리는 Qdrant 로컬 파일 모드가 저장소를 한 프로세스만 열게 해서 어댑터가 앱 안 스레드로 뜨고, 그래서 **Streamlit 특성상 누군가 페이지를 한 번 열어야 어댑터가 살아난다**.
- **`.streamlit/config.toml`** is deploy-only (`address = "192.168.10.169"`) — running `streamlit run app.py` locally without overriding `--server.address`/`--server.port` fails immediately with `OSError [WinError 10049]` because that IP doesn't exist on the local machine.
