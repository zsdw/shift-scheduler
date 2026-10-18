# 폰용(Streamlit Cloud) 업로드 폴더를 최신 상태로 다시 만든다.
# 사용: PowerShell에서  .\make_deploy_copy.ps1
# 결과: C:\Users\LJH\Documents\Codex\shift-scheduler-deploy  (이 폴더 내용을 GitHub에 올림)
$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$dst = Join-Path (Split-Path $src -Parent) "shift-scheduler-deploy"

New-Item -ItemType Directory -Force $dst | Out-Null
foreach ($name in "app.py", "requirements.txt", "배포_안내.md") {
    Copy-Item (Join-Path $src $name) $dst -Force
}
# 화면 모듈 전부 (2026-10-18: 주말 주간·연차일정·일보·명령서 등이 빠지던 문제 — 이름 목록 대신 *_ui.py 전체)
Get-ChildItem $src -File -Filter "*_ui.py" | ForEach-Object { Copy-Item $_.FullName $dst -Force }
# Hugging Face Spaces용 실행 설정 (Dockerfile, README.md 머리말)
Copy-Item (Join-Path $src "deploy_files\*") $dst -Force
# 엔진·화면 부품 (캐시 제외)
robocopy (Join-Path $src "night_shift") (Join-Path $dst "night_shift") /MIR /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
# 저장된 근무 이력 (휴지통 제외) — 폰에서 지난 근무표 보기·이력 밸런스용
robocopy (Join-Path $src "history") (Join-Path $dst "history") /MIR /XD .trash __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
Set-Content -Path (Join-Path $dst ".gitignore") -Encoding utf8 -Value @"
__pycache__/
*.pyc
.venv/
history/.trash/
history/day/.trash/
"@
$files = Get-ChildItem $dst -Recurse -File
"완료: $dst  (파일 $($files.Count)개)"

