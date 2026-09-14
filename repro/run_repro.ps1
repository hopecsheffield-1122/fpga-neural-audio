# SENTINEL: REPRO-RUN-REV3-2026-09-10
# Golden reproduction, one command:   .\run_repro.ps1 -Width 20
# Requires: Vitis HLS 2025.2, Python 3 on PATH. Run from the pack directory.
# REV3: stops when Vitis exits nonzero, so a dump left over from an earlier
#       run can never be reported as a fresh MATCH.
param([Parameter(Mandatory=$true)][ValidateRange(8,24)][int]$Width)
$ErrorActionPreference = "Stop"
# --- adjust these two lines only if your install paths differ -------------
$VitisRun = "C:\AMDDesignTools\2025.2\Vitis\bin\vitis-run.bat"
$Python   = "python"
# --------------------------------------------------------------------------
$Pack = $PSScriptRoot
if (-not (Test-Path (Join-Path $Pack "expected_golden.csv"))) {
    Write-Host "FATAL: expected_golden.csv missing (pack incomplete)"; exit 1
}
if (-not (Test-Path $VitisRun)) {
    Write-Host "FATAL: Vitis not found at $VitisRun -- edit `$VitisRun at the top of this script"; exit 1
}
$Dump = Join-Path $Pack ("out\golden_repro_w{0}.f32" -f $Width)
if (Test-Path $Dump) {
    Write-Host "FATAL: $Dump already exists. Rename or move the previous run's dump first; nothing was built or verified."; exit 1
}
$env:REPRO_W = "$Width"
$env:REPRO_DIR = ($Pack -replace '\\','/')
Write-Host "=== REPRO-RUN-REV3: width $Width -- csim ~2-3 minutes ==="
Push-Location $Pack
& $VitisRun --mode hls --tcl (Join-Path $Pack "repro_golden.tcl")
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) {
    Write-Host "FATAL: vitis-run exited $rc -- the simulation did not complete; nothing verified. See repro_prj\sol_w$Width\csim\report\gru_va_csim.log"; exit $rc
}
if (-not (Test-Path $Dump)) {
    Write-Host "FATAL: simulation finished but no dump at $Dump; nothing verified."; exit 1
}
Write-Host "=== vitis-run exit $rc; verifying dump against the certified record ==="
$Log  = Join-Path $Pack ("repro_prj\sol_w{0}\csim\report\gru_va_csim.log" -f $Width)
& $Python (Join-Path $Pack "repro_verify.py") --width $Width --dump $Dump --expected (Join-Path $Pack "expected_golden.csv") --log $Log
$VerifyRc = $LASTEXITCODE
Write-Host "=== exporting human-readable CSV of this run ==="
& $Python (Join-Path $Pack "dump_csv.py") --width $Width
exit $VerifyRc
# SENTINEL-END: REPRO-RUN-REV3-2026-09-10
