#!/usr/bin/env bash
# 하위 에이전트 어댑터 일괄 실행 (배포 서버)
# 사용법: bash scripts/start_adapters.sh
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REGISTRY="$ROOT/data/orchestrator_registry.json"
HOST="192.168.10.169"
BASE="${ADAPTER_REPO_BASE:-$HOME}"

if [ ! -f "$REGISTRY" ]; then
    echo "레지스트리가 없습니다: $REGISTRY" >&2
    exit 1
fi

# 레지스트리 키:리포 디렉터리명
for pair in "lex:LexAgent" "policy:PolicyAgent" "hana:hana_p" "radar:AiAxRadar"; do
    key="${pair%%:*}"
    repo="${pair##*:}"

    enabled=$(python3 -c "import json,sys;r=json.load(open('$REGISTRY',encoding='utf-8'));print(r.get('$key',{}).get('enabled',False))")
    if [ "$enabled" != "True" ]; then
        echo "- $key : enabled=false, 건너뜀"
        continue
    fi

    port=$(python3 -c "import json;r=json.load(open('$REGISTRY',encoding='utf-8'));print(r['$key']['api_port'])")
    repo_path="$BASE/$repo"

    # venv가 있으면 그것을, 없으면 시스템 python3을 쓴다 — 로컬에서도 venv를
    # 가진 리포는 렉스뿐이었고, 배포 서버도 리포마다 다를 수 있다.
    if [ -x "$repo_path/venv/bin/python" ]; then
        python_bin="$repo_path/venv/bin/python"
    else
        python_bin="python3"
        echo "  ($key : venv 없음 -> 시스템 python3 사용)"
    fi

    if [ ! -f "$repo_path/api.py" ]; then echo "! $key : api.py 없음"; continue; fi

    echo "+ $key : 포트 $port 로 시작"
    (cd "$repo_path" && nohup "$python_bin" api.py --host "$HOST" --port "$port" \
        > "$repo_path/adapter.log" 2>&1 &)
done

echo ""
echo "어댑터 상태는 오케스트레이터 페이지의 '헬스체크 실행'으로 확인하세요."
