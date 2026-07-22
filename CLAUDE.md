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
- **`.streamlit/config.toml`** is deploy-only (`address = "192.168.10.169"`) — running `streamlit run app.py` locally without overriding `--server.address`/`--server.port` fails immediately with `OSError [WinError 10049]` because that IP doesn't exist on the local machine.
