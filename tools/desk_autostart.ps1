<#
.SYNOPSIS
  데스크 PC 에서 로컬 프라이서와 중계를 띄운다.

.DESCRIPTION
  배포본이 실시간 호가를 받으려면 이 PC 에서 두 개가 돌아야 합니다.

    1. 로컬 프라이서  - LSEG Workspace 에 붙어 호가를 읽습니다
    2. 중계 에이전트  - 그 호가를 배포본으로 보냅니다

  둘 다 이 PC 에 Workspace 가 떠 있어야 의미가 있으므로, 부팅이 아니라 로그온
  시점에 돌립니다. Workspace 가 아직 안 떠 있어도 중계는 죽지 않고 "미연결 —
  보내지 않음" 을 찍으며 다음 주기를 기다립니다. 기준호가를 실시간인 것처럼
  중계하지 않기 위해서입니다.

  창은 최소화로 띄웁니다. 숨기면 무엇이 도는지 알 수 없어서, 실제로 "분명히
  껐는데 왜 돌지" 하는 혼란이 있었습니다. 로그도 logs\ 에 함께 남깁니다.

.PARAMETER Python
  쓸 파이썬 실행 파일. install_autostart.ps1 이 설치 시점의 경로를 넣어줍니다.

.PARAMETER Port
  로컬 프라이서 포트 (기본 8000).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\desk_autostart.ps1
#>
param(
    [string]$Python = "python",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$logs = Join-Path $root "logs"
if (-not (Test-Path $logs)) { New-Item -ItemType Directory -Path $logs | Out-Null }

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Output $line
    Add-Content -Path (Join-Path $logs "autostart.log") -Value $line -Encoding utf8
}

function Test-Port($p) {
    $c = New-Object Net.Sockets.TcpClient
    try { $c.Connect("127.0.0.1", $p); return $true }
    catch { return $false }
    finally { $c.Dispose() }
}

Write-Log "시작 — root=$root python=$Python"

# ---- 1. 로컬 프라이서 -------------------------------------------------------
# 이미 떠 있으면 두 번 띄우지 않습니다. 두 번째는 포트를 못 잡고 죽을 뿐이지만,
# 로그에 실패가 쌓여 진짜 문제를 가립니다.
if (Test-Port $Port) {
    Write-Log "로컬 프라이서: 이미 $Port 포트에서 실행 중 — 건너뜀"
} else {
    Start-Process -FilePath $Python `
        -ArgumentList @("-m", "uvicorn", "server.app:app",
                        "--host", "127.0.0.1", "--port", "$Port",
                        "--log-level", "warning") `
        -WorkingDirectory $root -WindowStyle Minimized `
        -RedirectStandardOutput (Join-Path $logs "pricer.out.log") `
        -RedirectStandardError  (Join-Path $logs "pricer.err.log")
    Write-Log "로컬 프라이서: 실행함 (포트 $Port)"
}

# 중계가 첫 주기에 헛돌지 않도록 포트가 열릴 때까지 기다립니다. 안 열려도
# 중계는 뜹니다 - 읽기 실패는 통화별로 잡히고 다음 주기에 다시 시도합니다.
$deadline = (Get-Date).AddSeconds(90)
while (-not (Test-Port $Port) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
}
if (Test-Port $Port) { Write-Log "로컬 프라이서: 응답 확인" }
else { Write-Log "로컬 프라이서: 90초 안에 응답 없음 — 중계는 그대로 띄웁니다" }

# ---- 2. 중계 에이전트 -------------------------------------------------------
# 대상 주소도 비밀번호도 .env 에서 읽습니다. 인자로 주면 작업 속성과 프로세스
# 목록에 평문으로 남습니다.
$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
           Where-Object { $_.CommandLine -like "*desk_relay.py*" }
if ($running) {
    Write-Log "중계: 이미 실행 중 (PID $($running.ProcessId -join ', ')) — 건너뜀"
} else {
    Start-Process -FilePath $Python `
        -ArgumentList @("-u", "tools\desk_relay.py") `
        -WorkingDirectory $root -WindowStyle Minimized `
        -RedirectStandardOutput (Join-Path $logs "relay.out.log") `
        -RedirectStandardError  (Join-Path $logs "relay.err.log")
    Write-Log "중계: 실행함"
}

Write-Log "완료"
