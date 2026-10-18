param([string]$IconPath)

$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $projectDir 'launch_night_shift.cmd'
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "실행 파일이 없습니다: $launcher"
}
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
$shortcutPath = Join-Path $desktop '야간 근무표 자동 생성기.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.WorkingDirectory = $projectDir
$shortcut.Description = '야간 근무표 자동 생성기 실행'
if ($IconPath) {
    if (-not (Test-Path -LiteralPath $IconPath -PathType Leaf)) {
        throw "아이콘 파일이 없습니다: $IconPath"
    }
    $shortcut.IconLocation = (Resolve-Path -LiteralPath $IconPath).Path
} else {
    $shortcut.IconLocation = (Join-Path $env:SystemRoot 'System32\shell32.dll') + ',3'
}
$shortcut.Save()
Write-Host "바탕화면 바로가기 생성: $shortcutPath"
