<#
.SYNOPSIS
  로그온할 때 로컬 프라이서와 중계가 뜨도록 작업 스케줄러에 등록한다.

.DESCRIPTION
  등록하면 이 PC 에 로그인할 때마다 desk_autostart.ps1 이 한 번 돌고, 그 안에서
  로컬 프라이서와 중계가 뜹니다. 그때부터 배포본이 ● BASE 가 아니라 ● RELAY 를
  보여줍니다.

  부팅이 아니라 로그온인 이유: LSEG Workspace 는 데스크탑 프로그램이라 사용자
  세션이 있어야 뜹니다. 세션 없이 프라이서만 띄워봐야 기준호가만 나옵니다.

  Workspace 가 아직 로딩 중이어도 괜찮습니다. 중계는 붙을 때까지 "미연결 —
  보내지 않음" 을 찍으며 기다립니다.

  관리자 권한은 필요 없습니다. 현재 사용자로만 등록합니다.

.PARAMETER Uninstall
  등록을 지웁니다. 이미 떠 있는 프로세스는 건드리지 않습니다.

.PARAMETER Status
  등록 상태와 지금 돌고 있는 프로세스를 보여줍니다.

.PARAMETER DelaySeconds
  로그온 후 몇 초 뒤에 시작할지. 기본 60초 - 로그인 직후는 Workspace 와 다른
  프로그램이 함께 뜨느라 느립니다.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\install_autostart.ps1
  powershell -ExecutionPolicy Bypass -File tools\install_autostart.ps1 -Status
  powershell -ExecutionPolicy Bypass -File tools\install_autostart.ps1 -Uninstall
#>
param(
    [switch]$Uninstall,
    [switch]$Status,
    [int]$DelaySeconds = 60,
    [int]$RepeatMinutes = 10
)

$ErrorActionPreference = "Stop"
$TaskName = "MultiPricer Desk Relay"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$script = Join-Path $root "tools\desk_autostart.ps1"

function Show-Status {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($t) {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        Write-Output "등록됨   : $TaskName ($($t.State))"
        Write-Output "  마지막 : $($info.LastRunTime)  결과 $($info.LastTaskResult)"
        Write-Output "  다음   : $($info.NextRunTime)"
    } else {
        Write-Output "등록됨   : 아니오"
    }
    # uvicorn 만 찾으면 `python server/app.py` 로 띄운 프라이서를 놓칩니다 -
    # 실제로 그래서 "안 돌고 있다" 고 잘못 보고했습니다.
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
             Where-Object { $_.CommandLine -like "*uvicorn server.app*" -or
                            $_.CommandLine -like "*serverpp.py*" -or
                            $_.CommandLine -like "*server/app.py*" -or
                            $_.CommandLine -like "*desk_relay.py*" }
    if ($procs) {
        Write-Output "실행 중  :"
        foreach ($p in $procs) {
            $what = if ($p.CommandLine -like "*desk_relay*") { "중계        " } else { "로컬 프라이서" }
            Write-Output "  $what PID $($p.ProcessId)"
        }
    } else {
        Write-Output "실행 중  : 없음"
    }
}

if ($Status) { Show-Status; exit 0 }

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "지웠습니다: $TaskName"
        Write-Output "이미 떠 있는 프로세스는 그대로입니다 - 끄려면 창을 닫으세요."
    } else {
        Write-Output "등록된 작업이 없습니다."
    }
    exit 0
}

# ---- 설치 -------------------------------------------------------------------
if (-not (Test-Path $script)) { throw "desk_autostart.ps1 을 찾지 못했습니다: $script" }

# 설치 시점의 파이썬 경로를 박아둡니다. 작업 스케줄러는 사용자의 PATH 를 그대로
# 물려받지 않는 경우가 있어, "python" 만 적어두면 로그온 때 찾지 못합니다.
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $py) { throw "python 을 찾지 못했습니다. PATH 를 확인하세요." }

# .env 가 중계에 필요한 값을 갖고 있는지 먼저 봅니다. 없으면 로그온 때 조용히
# 실패하고, 그건 몇 주 뒤에야 "왜 BASE 지" 로 발견됩니다.
$envPath = Join-Path $root ".env"
$missing = @()
if (Test-Path $envPath) {
    $envText = Get-Content $envPath -Raw
    foreach ($k in @("PRICER_RELAY_TARGET", "PRICER_RELAY_USER", "PRICER_RELAY_PASS")) {
        if ($envText -notmatch "(?m)^\s*$k\s*=\s*\S") { $missing += $k }
    }
} else {
    $missing = @("PRICER_RELAY_TARGET", "PRICER_RELAY_USER", "PRICER_RELAY_PASS")
}
if ($missing.Count -gt 0) {
    Write-Warning "`.env 에 다음이 없습니다: $($missing -join ', ')"
    Write-Warning "중계가 뜨자마자 종료됩니다. .env 에 추가한 뒤 다시 실행하세요:"
    Write-Warning "  PRICER_RELAY_TARGET=https://multipricer.onrender.com"
    Write-Warning "  PRICER_RELAY_USER=<대시보드 아이디>"
    Write-Warning "  PRICER_RELAY_PASS=<대시보드 비밀번호>"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument ("-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden " +
               "-File `"$script`" -Python `"$py`"") `
    -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT${DelaySeconds}S"

# 로그온 때 한 번만 돌면, 그 뒤에 프로세스가 죽었을 때 다시 로그인할 때까지
# 배포본이 기준호가로 남습니다. 실제로 그렇게 됐습니다 - 몇 시간 동안
# ● BASE 였고 아무도 몰랐습니다. 주기적으로 다시 돌려 스스로 낫게 합니다.
# desk_autostart.ps1 은 이미 떠 있으면 건너뛰므로 반복해도 해가 없습니다.
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Minutes $RepeatMinutes)

# 배터리로 돌더라도 중단하지 않습니다. 노트북에서 화면을 덮으면 중계가 멈추고,
# 배포본은 조용히 오래된 호가를 들고 있게 됩니다 - 배지가 그걸 알려주긴 하지만
# 굳이 멈출 이유가 없습니다.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($trigger, $repeat) `
    -Settings $settings -Description "MULTIPRICER: 로컬 프라이서 + 데스크 중계" `
    -Force | Out-Null

Write-Output "등록했습니다: $TaskName"
Write-Output "  파이썬 : $py"
Write-Output "  스크립트: $script"
Write-Output "  시작   : 로그온 후 ${DelaySeconds}초"
Write-Output "  반복   : ${RepeatMinutes}분마다 (죽어 있으면 다시 띄움)"
Write-Output ""
Write-Output "지금 바로 한 번 돌려보려면:"
Write-Output "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Output "상태 확인:"
Write-Output "  powershell -ExecutionPolicy Bypass -File tools\install_autostart.ps1 -Status"
