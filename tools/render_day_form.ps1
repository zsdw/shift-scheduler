# 양식(원본 편성표 주간 시트)에 값만 채우고 인쇄 영역을 엑셀이 그린 그대로 PNG로 내보낸다.
# Spec JSON: {"clear": ["F5", ...], "values": {"F5": "1만년", ...}}. 양식 파일은 바꾸지 않는다(사본에 작업).
param([string]$Form, [string]$Spec, [string]$Output)
$ErrorActionPreference = 'Stop'
$work = Join-Path $env:TEMP ("dayform_" + [guid]::NewGuid().ToString() + ".xlsx")
Copy-Item -LiteralPath $Form -Destination $work
$data = Get-Content -LiteralPath $Spec -Raw -Encoding UTF8 | ConvertFrom-Json
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
try {
    $book = $excel.Workbooks.Open($work)
    $sheet = $book.Worksheets.Item(1)
    foreach ($cell in $data.clear) { $sheet.Range($cell).MergeArea.ClearContents() | Out-Null }
    foreach ($p in $data.values.PSObject.Properties) {
        $range = $sheet.Range($p.Name)
        $range.NumberFormat = "@"
        $range.Value2 = [string]$p.Value
    }
    $area = $sheet.Range($sheet.PageSetup.PrintArea)
    $sheet.Activate()
    $excel.ActiveWindow.Zoom = 100
    $excel.ActiveWindow.DisplayGridlines = $false
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Clipboard]::Clear()
    $area.CopyPicture(1, 2) | Out-Null          # xlScreen, xlBitmap
    $image = $null
    for ($i = 0; $i -lt 20 -and -not $image; $i++) {
        Start-Sleep -Milliseconds 150
        $image = [System.Windows.Forms.Clipboard]::GetImage()
    }
    if (-not $image) { throw "clipboard image not available" }
    $image.Save($Output, [System.Drawing.Imaging.ImageFormat]::Png)
    $image.Dispose()
    [System.Windows.Forms.Clipboard]::Clear()
    $book.Close($false)
    "ok"
} finally {
    $excel.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    Remove-Item -LiteralPath $work -ErrorAction SilentlyContinue
}
