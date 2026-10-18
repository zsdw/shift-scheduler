# One-time export (needs Excel): blank form picture + pixel boxes and fonts of the value cells.
# After this the app draws the image without Excel (night_shift/day_form_draw.py).
param([string]$Form, [string]$Spec, [string]$Background, [string]$Geometry)
$ErrorActionPreference = 'Stop'
$work = Join-Path $env:TEMP ("dayform_geo_" + [guid]::NewGuid().ToString() + ".xlsx")
Copy-Item -LiteralPath $Form -Destination $work
$data = Get-Content -LiteralPath $Spec -Raw -Encoding UTF8 | ConvertFrom-Json
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
try {
    $book = $excel.Workbooks.Open($work)
    $sheet = $book.Worksheets.Item(1)
    $area = $sheet.Range($sheet.PageSetup.PrintArea)
    $boxes = @{}
    foreach ($cell in $data.cells) {
        $m = $sheet.Range($cell).MergeArea
        $f = $m.Cells.Item(1, 1).Font
        $boxes[$cell] = @{
            left = $m.Left - $area.Left; top = $m.Top - $area.Top; width = $m.Width; height = $m.Height
            font = [string]$f.Name; size = [double]$f.Size; bold = [bool]$f.Bold
            h = [int]$m.Cells.Item(1, 1).HorizontalAlignment; v = [int]$m.Cells.Item(1, 1).VerticalAlignment
        }
        $m.ClearContents() | Out-Null
    }
    $sheet.Activate()
    $excel.ActiveWindow.Zoom = 100
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Clipboard]::Clear()
    $area.CopyPicture(1, 2) | Out-Null
    $image = $null
    for ($i = 0; $i -lt 20 -and -not $image; $i++) { Start-Sleep -Milliseconds 150; $image = [System.Windows.Forms.Clipboard]::GetImage() }
    if (-not $image) { throw "clipboard image not available" }
    $image.Save($Background, [System.Drawing.Imaging.ImageFormat]::Png)
    $out = @{ width = $area.Width; height = $area.Height; pixels = @($image.Width, $image.Height); cells = $boxes }
    $image.Dispose()
    ($out | ConvertTo-Json -Depth 5) | Out-File -LiteralPath $Geometry -Encoding UTF8
    $book.Close($false)
    "ok"
} finally {
    $excel.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    Remove-Item -LiteralPath $work -ErrorAction SilentlyContinue
}
