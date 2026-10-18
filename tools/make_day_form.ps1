# 원본 편성표의 주간 시트 하나를 서식 그대로 복사해 양식 파일로 저장 (원본은 읽기 전용으로만 연다).
param([string]$Source, [string]$Sheet, [string]$Target)
$ErrorActionPreference = 'Stop'
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
try {
    $book = $excel.Workbooks.Open($Source, 0, $true)
    $book.Worksheets.Item($Sheet).Copy()
    $copy = $excel.ActiveWorkbook
    $copy.SaveAs($Target, 51)
    $copy.Close($false)
    $book.Close($false)
    "ok"
} finally {
    $excel.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
}
