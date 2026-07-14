# Convert survey ECW orthos to RGB GeoTIFF using QGIS GDAL (ECW plugin).
# Docker open-source GDAL cannot read ECW — this must run on the host with QGIS.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Qgis = "C:\Program Files\QGIS 3.44.4"
if (-not (Test-Path "$Qgis\bin\gdal_translate.exe")) {
  throw "QGIS not found at $Qgis — update the path in this script."
}

$env:PATH = "$Qgis\bin;$env:PATH"
$env:GDAL_DRIVER_PATH = "$Qgis\apps\gdal\lib\gdalplugins"
$env:GDAL_DATA = "$Qgis\apps\gdal\share\gdal"
$gdal = "$Qgis\bin\gdal_translate.exe"
$out = Join-Path $Root "backend\processed\nacala-coal-field"
New-Item -ItemType Directory -Force -Path $out | Out-Null

$jobs = @(
  @{
    src = Join-Path $Root "backend\data\24 February\ortho\MOZAMBIQUE PORT & COAL FIELD 24-Feb.ecw"
    dst = Join-Path $out "report-24-feb-ortho-rgb.tif"
  },
  @{
    src = Join-Path $Root "backend\data\3rd March\ortho\MOZAMBIQUE PORT & COAL FIELD 03-March.ecw"
    dst = Join-Path $out "report-3rd-march-ortho-rgb.tif"
  }
)

foreach ($job in $jobs) {
  if (-not (Test-Path $job.src)) {
    Write-Warning "Missing $($job.src)"
    continue
  }
  Write-Host "Converting $($job.src) -> $($job.dst)"
  & $gdal -b 1 -b 2 -b 3 -of GTiff `
    -co COMPRESS=JPEG -co PHOTOMETRIC=YCBCR -co TILED=YES `
    -outsize 2048 0 `
    $job.src $job.dst
}

Write-Host "Done. Restart/process API so previews + 3D pick up true-color ortho."
