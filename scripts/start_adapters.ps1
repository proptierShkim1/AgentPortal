# 하위 에이전트 어댑터 일괄 실행 (로컬)
# 사용법: powershell -ExecutionPolicy Bypass -File scripts\start_adapters.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$registryPath = Join-Path $root "data\orchestrator_registry.json"

if (-not (Test-Path $registryPath)) {
    Write-Error "레지스트리가 없습니다: $registryPath"
}

# 레지스트리 키 -> (리포 경로, venv 파이썬 상대경로 또는 $null)
# 조사 결과 venv를 가진 리포는 렉스(lex-env)뿐이고, 폴리·프니·에리는 시스템
# 파이썬으로 돌고 있다. venv 경로가 $null이거나 실제로 없으면 시스템 python으로
# 폴백한다 — venv를 전제하면 3개가 전부 건너뛰어진다.
$repos = @{
    "lex"    = @("C:\Users\USER\Desktop\Project Agent\LexAgent",   "lex-env\Scripts\python.exe")
    "policy" = @("C:\Users\USER\Desktop\Project Agent\PolicyAgent", $null)
    "hana"   = @("C:\Users\USER\Desktop\Project Agent\hana_p",      $null)
    "radar"  = @("C:\Users\USER\Desktop\Project Agent\AiAxRadar",   $null)
}

$registry = Get-Content $registryPath -Raw -Encoding UTF8 | ConvertFrom-Json

foreach ($key in $repos.Keys) {
    $entry = $registry.$key
    if ($null -eq $entry) { Write-Host "- $key : 레지스트리에 없음, 건너뜀"; continue }
    if (-not $entry.enabled) { Write-Host "- $key : enabled=false, 건너뜀"; continue }

    $repoPath = $repos[$key][0]
    $venvRel = $repos[$key][1]
    $apiPath = Join-Path $repoPath "api.py"

    if ($null -ne $venvRel -and (Test-Path (Join-Path $repoPath $venvRel))) {
        $python = Join-Path $repoPath $venvRel
    } else {
        $python = "python"
        Write-Host "  ($key : venv 없음 -> 시스템 python 사용)"
    }

    if (-not (Test-Path $apiPath)) { Write-Host "! $key : api.py 없음 ($apiPath)"; continue }

    Write-Host "+ $key : 포트 $($entry.api_port) 로 시작"
    Start-Process -FilePath $python `
        -ArgumentList @($apiPath, "--host", "192.168.14.222", "--port", "$($entry.api_port)") `
        -WorkingDirectory $repoPath
}

Write-Host ""
Write-Host "어댑터 상태는 오케스트레이터 페이지의 '헬스체크 실행'으로 확인하세요."
