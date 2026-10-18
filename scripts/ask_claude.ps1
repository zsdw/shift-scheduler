param(
    [Parameter(Mandatory = $true)][string]$Prompt,
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
$claudePath = Join-Path $env:USERPROFILE '.local\bin\claude.exe'
if (-not (Test-Path -LiteralPath $claudePath)) {
    throw 'Claude Code 실행 파일이 없습니다.'
}
if ($Check) {
    & $claudePath auth status
    exit $LASTEXITCODE
}

# 기존 야간 세션을 이어받지 않고 별도의 읽기 전용 세션으로 실행한다.
# safe-mode는 사용자/프로젝트 hook과 플러그인의 자동 실행을 막는다.
$repoPath = Split-Path -Parent $PSScriptRoot
Push-Location $repoPath
try {
    $instruction = '한국어로 답하세요. 파일을 수정하지 않는 검토 전용 요청입니다. AGENTS.md의 역할 분담을 읽고, 요청한 파일만 확인하세요. 현재 다른 Claude 세션이 야간을 작업 중입니다. 해당 세션을 재개하거나 변경하지 마세요.'
    & $claudePath --safe-mode --strict-mcp-config --disable-slash-commands --no-session-persistence --permission-mode dontAsk --tools 'Read,Glob,Grep' --allowedTools 'Read,Glob,Grep' --append-system-prompt $instruction --output-format json -p $Prompt
    $resultCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $resultCode
