#!/usr/bin/env bash
set -eu
ROOT="${PORTAL_ROOT:-$HOME/AgentPortal}"
PORT="${PORTAL_PORT:-9000}"
cd "$ROOT"

# 기존 프로세스 종료
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PORT}/tcp" 2>/dev/null || true
else
  for pid in $(ss -tlnp 2>/dev/null | grep ":${PORT}" | sed -n 's/.*pid=\([0-9]*\).*/\1/p'); do
    kill "$pid" 2>/dev/null || true
  done
fi
sleep 1

source "$ROOT/venv/bin/activate"

echo "START app.py (port $PORT)"
nohup python -m streamlit run app.py \
  --server.address 0.0.0.0 \
  --server.port "$PORT" \
  --server.headless true \
  >>"$ROOT/streamlit.log" 2>&1 &

sleep 4
ss -tlnp 2>/dev/null | grep ":${PORT}" || { echo NOT_LISTENING; exit 1; }
echo "OK"
