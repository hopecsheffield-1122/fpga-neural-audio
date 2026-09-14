# verify_board_vs_nas_REV2.ps1 - is a board directory safely duplicated on the NAS?
# Sentinel: VERIFY-BVN-REV2
# REV1 (0A9D548F...) superseded: hashtable variable collided with the [string] $Board
# parameter (case-insensitive scope) -> "Unable to index into System.String". Renamed.
# REV1 failed before any comparison; nothing was affected.
# For every file in the board dir (default: *.f32), md5sum on the board and
# Get-FileHash on the NAS; prints OK / MISMATCH / MISSING-ON-NAS counts and the
# offending names. Prints a delete command for the OK set ONLY if every board
# file is OK -- you run that command yourself; this script deletes nothing.
#
# Machine: LENNY:
#   .\verify_board_vs_nas_REV2.ps1 -BDir /home/xilinx/jupyter_notebooks/session2 -NasDir <NAS>\board_session2_2026-08-11

param(
    [Parameter(Mandatory=$true)][string]$BDir,
    [Parameter(Mandatory=$true)][string]$NasDir,
    [string]$Board   = "xilinx@192.168.2.99",
    [string]$Pattern = "*.f32"
)
$ErrorActionPreference = "Stop"
Write-Host "VERIFY-BVN-REV2 $BDir vs $NasDir  ($Pattern)"
if (-not (Test-Path -LiteralPath $NasDir)) { throw "NAS dir missing: $NasDir" }
$raw = ssh $Board "cd $BDir && ls $Pattern >/dev/null 2>&1 && md5sum $Pattern || echo NOFILES"
$bhash = @{}
foreach ($l in @($raw)) { if ($l -match '^([0-9a-fA-F]{32})\s+\*?(.+)$') { $bhash[$Matches[2].Trim()] = $Matches[1].ToUpper() } }
Write-Host ("board: {0} files hashed" -f $bhash.Count)
if ($bhash.Count -eq 0) { Write-Host "nothing matching on the board"; exit 0 }
$ok = @(); $bad = @(); $missing = @()
foreach ($name in ($bhash.Keys | Sort-Object)) {
    $p = Join-Path $NasDir $name
    if (-not (Test-Path -LiteralPath $p)) { $missing += $name; continue }
    $h = (Get-FileHash -LiteralPath $p -Algorithm MD5).Hash
    if ($h -eq $bhash[$name]) { $ok += $name } else { $bad += $name }
}
Write-Host ("RESULT: OK={0} MISMATCH={1} MISSING_ON_NAS={2}" -f $ok.Count, $bad.Count, $missing.Count)
$bad | ForEach-Object { Write-Host "  MISMATCH: $_" }
$missing | ForEach-Object { Write-Host "  MISSING ON NAS: $_" }
if ($bad.Count -eq 0 -and $missing.Count -eq 0) {
    Write-Host "every board file is byte-identical on the NAS. To free the board (your call, run it yourself):"
    Write-Host ("ssh {0} ""cd {1} && rm {2} && df -h . | tail -1""" -f $Board, $BDir, $Pattern)
} else {
    Write-Host "NOT safe to delete: pull the MISSING/MISMATCH files to the NAS first (scp), then rerun."
}
