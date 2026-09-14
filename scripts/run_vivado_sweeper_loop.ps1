# run_vivado_sweeper_loop.ps1 - VIVADO_SWEEPER_LOOP_SENTINEL_2026-08-08
# Relaunches the Vivado batch sweep every 30 min until all 102 pairs are on the NAS.
# Safe to Ctrl+C anytime and relaunch later - every pass is idempotent.
$ErrorActionPreference = "Continue"
$VIVADO = "C:\AMDDesignTools\2025.2\Vivado\bin\vivado.bat"
$SCRIPT = "<USER_HOME>\VitisProjects\run_bitgen_batch_vivado.tcl"
$OUT = "<BITGEN>\out"
$TARGET = 102
$pass = 0
while ($true) {
  $done = (Get-ChildItem $OUT -Filter "*.bit" -ErrorAction SilentlyContinue | Measure-Object).Count
  Write-Host ("[{0}] pass {1}: {2}/{3} bitstreams on NAS" -f (Get-Date -Format "HH:mm"), $pass, $done, $TARGET)
  if ($done -ge $TARGET) { Write-Host "ALL $TARGET BITSTREAMS BANKED - loop complete."; break }
  $pass++
  & $VIVADO -mode batch -nolog -nojournal -source $SCRIPT
  Write-Host ("[{0}] pass {1} sweep finished; sleeping 30 min" -f (Get-Date -Format "HH:mm"), $pass)
  Start-Sleep -Seconds 1800
}
