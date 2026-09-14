# run_ippack_fixup_loop.ps1 - IPPACK_FIXUP_LOOP_SENTINEL_2026-08-08
# Repairs export_design "input line is too long" failures by running each
# solution's run_ippack.tcl directly in Vivado (bypasses the HLS cmd wrapper).
# Loops until all 102 solutions under C:\hb have component.xml.
# Safe alongside the HLS queue and the sweeper: only touches solutions whose
# export already failed (run_ippack.tcl present, component.xml absent) and
# whose files have settled for >= 2 min.
$ErrorActionPreference = "Continue"
$VIVADO = "C:\AMDDesignTools\2025.2\Vivado\bin\vivado.bat"
$TARGET = 102
$pass = 0
while ($true) {
  $done = (Get-ChildItem "C:\hb\b_*\sol_*\impl\ip\component.xml" -ErrorAction SilentlyContinue | Measure-Object).Count
  Write-Host ("[{0}] fixup pass {1}: {2}/{3} complete exports" -f (Get-Date -Format "HH:mm"), $pass, $done, $TARGET)
  if ($done -ge $TARGET) { Write-Host "ALL $TARGET EXPORTS COMPLETE - fixup loop done."; break }
  $pass++
  $cands = Get-ChildItem "C:\hb\b_*\sol_*\impl\ip\run_ippack.tcl" -ErrorAction SilentlyContinue | Where-Object {
    -not (Test-Path (Join-Path $_.Directory.FullName "component.xml")) -and
    ((Get-Date) - $_.LastWriteTime).TotalSeconds -gt 120
  }
  foreach ($t in $cands) {
    $ipdir = $t.Directory.FullName
    $sol = Split-Path (Split-Path (Split-Path $ipdir -Parent) -Parent) -Leaf
    Write-Host ("  packing {0} ..." -f $sol)
    Push-Location $ipdir
    & $VIVADO -mode batch -nolog -nojournal -source run_ippack.tcl *> (Join-Path $ipdir "ippack_fixup.log")
    Pop-Location
    if (Test-Path (Join-Path $ipdir "component.xml")) {
      Write-Host ("  PACKED {0}" -f $sol)
    } else {
      Write-Host ("  PACK FAILED {0} - see {1}\ippack_fixup.log" -f $sol, $ipdir)
    }
  }
  Start-Sleep -Seconds 600
}
