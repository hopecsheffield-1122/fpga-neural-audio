# run_batch_hls_all.ps1 - BITGEN_BATCH_HLS_SENTINEL_2026-08-08_REV3_SHORTPATH
# 6 cells x 17 widths at short root C:\hb (export cmd-line-length fix).
# Requires run_batch_hls_template.tcl (REV3) in <USER_HOME>\VitisProjects.
# Run from a terminal where vitis-run resolves.
$ErrorActionPreference = "Stop"
$VP = "<USER_HOME>\VitisProjects"
$HB = "C:\hb"
$TD = "<USER_HOME>\hls\gru_va\testdata"
$G  = "<GRU_DIR>"
New-Item -ItemType Directory -Force -Path $HB | Out-Null
$TemplatePath = Join-Path $VP "run_batch_hls_template.tcl"
if (-not (Test-Path $TemplatePath)) { throw "Template missing: $TemplatePath" }
$TclTemplate = Get-Content $TemplatePath -Raw
if ($TclTemplate -notmatch "SENTINEL_REV3") { throw "Template is not REV3 - wrong file version" }

$CellSrc = [ordered]@{
  rodent_max = (Join-Path $G "hls_testdata")
  rodent_mod = (Join-Path $G "hls_testdata_rodent_mod")
  gt_mod     = (Join-Path $G "hls_testdata_gt_mod")
  gt_max     = (Join-Path $G "hls_testdata_gt_max")
  fl_mod     = (Join-Path $G "hls_testdata_fl_mod")
  fl_max     = (Join-Path $G "hls_testdata_fl_max")
}
foreach ($k in $CellSrc.Keys) {
  if (-not (Test-Path (Join-Path $CellSrc[$k] "weights_flat.bin"))) { throw "Cell source missing weights_flat.bin: $($CellSrc[$k])" }
  if (-not (Test-Path "<USER_HOME>\hls\gru_va\build_src\$k\weights.h")) { throw "Staged weights.h missing for cell $k" }
}
if (-not (Test-Path "<USER_HOME>\hls\gru_va\testdata_backup_orig")) {
  Copy-Item $TD "<USER_HOME>\hls\gru_va\testdata_backup_orig" -Recurse
  Write-Host "Original testdata backed up."
}
foreach ($cell in $CellSrc.Keys) {
  Write-Host "===== CELL $cell : swapping testdata ====="
  Get-ChildItem $TD -File | Remove-Item -Force
  Copy-Item (Join-Path $CellSrc[$cell] "*") $TD -Force
  $tclPath = Join-Path $HB "hls_$cell.tcl"
  Set-Content -Path $tclPath -Value ($TclTemplate -replace "__CELL__", $cell)
  Push-Location $HB
  try {
    vitis-run --mode hls --tcl $tclPath *>&1 | Tee-Object -FilePath (Join-Path $VP "batch_hls_${cell}_hb.log")
  } finally {
    Pop-Location
  }
}
Get-ChildItem $TD -File | Remove-Item -Force
Copy-Item "<USER_HOME>\hls\gru_va\testdata_backup_orig\*" $TD -Force
Write-Host "testdata restored to original. HLS BATCH ALL CELLS COMPLETE"
