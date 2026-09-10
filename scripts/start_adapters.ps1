# 하위 에이전트 어댑터 실행 (로컬)
#
# 사용법:
#   powershell -ExecutionPolicy Bypass -File scripts\start_adapters.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start_adapters.ps1 -Only lex,policy
#   powershell -ExecutionPolicy Bypass -File scripts\start_adapters.ps1 -List
#
# 이 PC(16GB)에서는 4개를 동시에 띄우면 OS가 메모리 부족으로 전부 강제 종료한다
# (2026-09-10에 두 번 발생). 그래서 -Only로 골라 켜는 것을 기본 사용법으로 둔다.
# 대략적인 무게: lex > policy > hana > radar.
param(
    [string[]]$Only,
    [switch]$List,
    [string]$BindHost = "192.168.14.222"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$registryPath = Join-Path $root "data\orchestrator_registry.json"

if (-not (Test-Path $registryPath)) {
    Write-Error "레지스트리가 없습니다: $registryPath"
}

# 레지스트리 키 -> (리포 경로, venv 파이썬 상대경로 또는 $null)
# venv 경로가 $null이거나 실제로 없으면 시스템 python으로 폴백한다.
# 확인 결과 시스템 python에도 4개 리포의 의존성이 모두 설치되어 있다.
$repos = @{
    "lex"    = @("C:\Users\USER\Desktop\Project Agent\LexAgent",   "lex-env\Scripts\python.exe")
    "policy" = @("C:\Users\USER\Desktop\Project Agent\PolicyAgent", $null)
    "hana"   = @("C:\Users\USER\Desktop\Project Agent\hana_p",      $null)
    "radar"  = @("C:\Users\USER\Desktop\Project Agent\AiAxRadar",   $null)
}

$registry = Get-Content $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json

function Test-PortListening([int]$Port) {
    $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

if ($List) {
    Write-Host "레지스트리에 등록된 어댑터:"
    foreach ($key in $repos.Keys | Sort-Object) {
        $entry = $registry.$key
        if ($null -eq $entry) { continue }
        $state = if (Test-PortListening ([int]$entry.api_port)) { "실행 중" } else { "정지" }
        $en = if ($entry.enabled) { "enabled" } else { "disabled" }
        Write-Host ("  {0,-8} 포트 {1,-6} {2,-9} {3}" -f $key, $entry.api_port, $en, $state)
    }
    exit 0
}

$os = Get-CimInstance Win32_OperatingSystem
$freeGb = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
Write-Host "메모리 여유: $freeGb GB"
if ($freeGb -lt 3) {
    # 경고만 하고 진행한다 — 무엇을 띄울지는 사용자가 정한다.
    Write-Host "  경고: 여유가 3GB 미만입니다. 무거운 어댑터(lex/policy)는 기동 중 강제 종료될 수 있습니다." -ForegroundColor Yellow
}
Write-Host ""

$targets = if ($Only) { $Only } else { $repos.Keys }
$started = 0

foreach ($key in $targets) {
    if (-not $repos.ContainsKey($key)) { Write-Host "! $key : 알 수 없는 키 (lex/policy/hana/radar)"; continue }

    $entry = $registry.$key
    if ($null -eq $entry) { Write-Host "- $key : 레지스트리에 없음, 건너뜀"; continue }
    if (-not $entry.enabled) { Write-Host "- $key : enabled=false, 건너뜀"; continue }

    $port = [int]$entry.api_port
    # 이미 떠 있는데 또 띄우면 두 번째 프로세스가 포트 충돌로 죽고, 그 실패가
    # 로그에만 남아 "왜 안 되지"로 이어진다.
    if (Test-PortListening $port) { Write-Host "= $key : 포트 $port 이미 실행 중, 건너뜀"; continue }

    $repoPath = $repos[$key][0]
    $venvRel = $repos[$key][1]
    $apiPath = Join-Path $repoPath "api.py"

    if ($null -ne $venvRel -and (Test-Path (Join-Path $repoPath $venvRel))) {
        $python = Join-Path $repoPath $venvRel
    } else {
        $python = "python"
    }

    if (-not (Test-Path $apiPath)) { Write-Host "! $key : api.py 없음 ($apiPath)"; continue }

    try {
        Start-Process -FilePath $python `
            -ArgumentList @($apiPath, "--host", $BindHost, "--port", "$port") `
            -WorkingDirectory $repoPath
        Write-Host "+ $key : 포트 $port 로 시작"
        $started++
    } catch {
        # 한 개가 실패해도 나머지는 계속 띄운다 — 조용히 건너뛰면 런처의 목적을 배반한다.
        Write-Host "! $key : 실행 실패 ($($_.Exception.Message))"
    }
}

Write-Host ""
if ($started -gt 0) {
    Write-Host "$started 개 기동 요청. 첫 응답까지 30~60초 걸릴 수 있습니다(모델·DB 로딩)."
}
Write-Host "상태는 오케스트레이터 페이지 우측 상단 '에이전트 확인' 버튼으로 보세요."
Write-Host "끄려면: powershell -ExecutionPolicy Bypass -File scripts\stop_adapters.ps1"
