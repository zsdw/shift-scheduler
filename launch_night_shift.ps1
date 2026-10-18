# -NoBrowser: 서버만 켜고 브라우저는 열지 않음 (Windows 시작 시 자동 실행용, 폰 접속 대비)
param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectDir '.venv\Scripts\python.exe'
$app = Join-Path $projectDir 'app.py'
$port = 8509
$healthUrl = "http://127.0.0.1:$port/_stcore/health"
$browserUrl = "http://localhost:$port/"
$stderrLog = $null
$exitCode = 0
$hasMutex = $false
$mutex = $null

function Test-ServerReady {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Get-ListenerPids {
    return @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
}

function Assert-OurListener {
    $owners = @(Get-ListenerPids)
    if ($owners.Count -eq 0) {
        throw "포트 $port 서버를 찾을 수 없습니다."
    }
    foreach ($ownerId in $owners) {
        $owner = Get-Process -Id $ownerId -ErrorAction Stop
        if ($owner.Path -ieq $python) {
            return
        }
        # A venv python.exe is a redirector: the listening process is the base
        # interpreter, so identify our server by its command line instead.
        $info = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerId" -ErrorAction SilentlyContinue
        if ($info -and $info.CommandLine -like '*streamlit*' -and $info.CommandLine -like "*$app*") {
            return
        }
    }
    throw "포트 $port 를 다른 프로그램이 사용 중입니다. 해당 프로그램을 종료한 뒤 다시 실행하세요."
}

try {
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Python 실행 파일이 없습니다: $python"
    }
    if (-not (Test-Path -LiteralPath $app -PathType Leaf)) {
        throw "Streamlit 앱 파일이 없습니다: $app"
    }

    # Two rapid double-clicks wait for the first launcher to finish starting the server.
    $mutex = [System.Threading.Mutex]::new($false, 'Local\NightShiftSchedulerLaunch8509')
    $hasMutex = $mutex.WaitOne([TimeSpan]::FromSeconds(75))
    if (-not $hasMutex) {
        throw '다른 실행 요청이 끝나지 않았습니다. 잠시 후 다시 시도하세요.'
    }

    $owners = @(Get-ListenerPids)
    if ($owners.Count -gt 0) {
        Assert-OurListener
        Write-Host '실행 중인 Streamlit 서버를 재사용합니다.'
    } else {
        $logDir = Join-Path $projectDir 'logs'
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
        $stdoutLog = Join-Path $logDir "streamlit-$stamp.out.log"
        $stderrLog = Join-Path $logDir "streamlit-$stamp.err.log"
        $arguments = @(
            '-m', 'streamlit', 'run', "`"$app`"",
            '--server.address', '127.0.0.1', '--server.port', "$port",
            '--server.headless', 'true', '--browser.gatherUsageStats', 'false'
        )
        $server = Start-Process -FilePath $python -ArgumentList $arguments `
            -WorkingDirectory $projectDir -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
        Write-Host "Streamlit 서버 준비 중... (PID $($server.Id))"
    }

    $ready = $false
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        if (Test-ServerReady) {
            $ready = $true
            break
        }
        if ($server -and $server.HasExited) {
            throw "Streamlit 프로세스가 종료되었습니다. 종료 코드: $($server.ExitCode)"
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) {
        throw '60초 안에 Streamlit 서버가 준비되지 않았습니다.'
    }
    Assert-OurListener
    if ($NoBrowser) {
        Write-Host "서버를 켰습니다 (브라우저 열지 않음): $browserUrl"
    } else {
        Start-Process -FilePath $browserUrl
        Write-Host "브라우저를 열었습니다: $browserUrl"
    }
} catch {
    $exitCode = 1
    Write-Host "실행 오류: $($_.Exception.Message)" -ForegroundColor Red
    if ($stderrLog -and (Test-Path -LiteralPath $stderrLog)) {
        Write-Host "오류 로그: $stderrLog"
        Get-Content -LiteralPath $stderrLog -Tail 25
    }
} finally {
    if ($hasMutex) {
        $mutex.ReleaseMutex()
    }
    if ($mutex) {
        $mutex.Dispose()
    }
}
exit $exitCode
