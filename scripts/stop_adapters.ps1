# 하위 에이전트 어댑터 중지 (로컬)
#
# 사용법:
#   powershell -ExecutionPolicy Bypass -File scripts\stop_adapters.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\stop_adapters.ps1 -Only lex,policy
#
# 켜는 것만큼 끄는 것도 필요하다. 이 PC에서는 4개를 동시에 못 올려서, 다른 조합을
# 쓰려면 쓰던 것을 내려야 한다.
#
# 포트를 점유한 프로세스를 종료하는 방식이라, 어댑터가 Streamlit 앱 안의 스레드로
# 떠 있는 경우(렉스를 앱과 함께 띄웠을 때)에는 앱 자체가 함께 종료된다 — 같은
# 프로세스이기 때문이다. 그것이 의도가 아니면 -Only로 대상을 골라라.
param(
    [string[]]$Only
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$registryPath = Join-Path $root "data\orchestrator_registry.json"

if (-not (Test-Path $registryPath)) {
    Write-Error "레지스트리가 없습니다: $registryPath"
}

$registry = Get-Content $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$keys = @("lex", "policy", "hana", "radar")
$targets = if ($Only) { $Only } else { $keys }
$stopped = 0

foreach ($key in $targets) {
    if ($keys -notcontains $key) { Write-Host "! $key : 알 수 없는 키 (lex/policy/hana/radar)"; continue }
    $entry = $registry.$key
    if ($null -eq $entry) { Write-Host "- $key : 레지스트리에 없음"; continue }

    $port = [int]$entry.api_port
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { Write-Host "- $key : 포트 $port 실행 중 아님"; continue }

    foreach ($pid in ($conns.OwningProcess | Select-Object -Unique)) {
        try {
            Stop-Process -Id $pid -Force -ErrorAction Stop
            Write-Host "x $key : 포트 $port (PID $pid) 종료"
            $stopped++
        } catch {
            # 한 개를 못 끄더라도 나머지는 계속 시도한다.
            Write-Host "! $key : 종료 실패 PID $pid ($($_.Exception.Message))"
        }
    }
}

$os = Get-CimInstance Win32_OperatingSystem
Write-Host ""
Write-Host ("$stopped 개 종료. 메모리 여유: {0:N1} GB" -f ($os.FreePhysicalMemory / 1MB))
