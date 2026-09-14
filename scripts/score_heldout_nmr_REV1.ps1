# SCORE-HELDOUT-NMR-REV1  (derived from SCORE-XCELLNMR-REV2, 70551B74...)
# Held-out NMR scoring: 6 cells x 2 sources x 17 widths = 204 rows, board outputs
# vs per-cell float refs, nmr_metric.py NMR-REV2 with --skip 1024.
# Changes vs REV2 (configuration + exact-name resolution; scoring path identical):
#   - all six cells (anchor guard removed: rodent_max is a scored cell here)
#   - per-source frames expectation (washout convention: frames = floor((N-3072)/1024)+1)
#   - exact filenames: board_<stim>_<cell>_w<W>.f32 and anchor_<stim>_ref32_<cell>.f32
#   - manifest = verified_manifest.csv written by PULL-HO-REV1 (file,md5 columns)
#   - output CSV gains a 'stim' column; expected rows 204
# Enforced rules (unchanged): scorer MD5+sentinel gate; manifest-MD5 verify before
# scoring; WARN -> INVALID_WARN; frames/skip gate; incremental append; annotate-never-delete.
#
# Modes:
#   (no switch)   PREFLIGHT: gates, scorer --help, resolve files, count vs 204, EXIT
#   -Go           score
#   -Go -AllowPartial   score even if discovered rows != 204
#
# Machine: LENNY, GRU dir:   .\score_heldout_nmr_REV1.ps1        then  .\score_heldout_nmr_REV1.ps1 -Go

param(
    [switch]$Go,
    [switch]$AllowPartial
)

$ErrorActionPreference = "Stop"
$Sentinel = "SCORE-HELDOUT-NMR-REV1"

# ============================ CONFIG (real values) ============================
$Python      = "<VENV>\Scripts\python.exe"
$NmrScript   = "<GRU_DIR>\nmr_metric.py"
$NmrMd5Exp   = "3098CB25C61E8099E313D0A2520367CD"   # certified NMR-REV2 hash record
$NmrSentinel = "NMR-REV2"
$BoardDir    = "<NAS>\board_heldout_2026-09-06"
$Manifest    = "<NAS>\board_heldout_2026-09-06\verified_manifest.csv"
$RefDir      = "<HLS_IO_HELDOUT>"
$OutCsv      = "<GRU_DIR>\heldout_nmr_REV1.csv"
$LogFile     = "<GRU_DIR>\heldout_nmr_REV1_log.txt"
$Cells       = @("rodent_max","rodent_mod","gt_max","gt_mod","fl_max","fl_mod")
$Stims       = @("bass","gtr4ib")
$Widths      = 8..24
$NmrArgsTemplate = '--ref "{REF}" --test "{TEST}" --skip 1024'
$ExpectSkip   = 1024
$ExpectFrames = @{ bass = 16622; gtr4ib = 14559 }   # floor((N-1024-2048)/1024)+1: N=17023200 / 14911200
# ==============================================================================

Write-Host ("{0}  run={1}  mode={2}" -f $Sentinel, (Get-Date -Format s), $(if ($Go) {"GO"} else {"PREFLIGHT"}))

function Assert-Scorer {
    if (-not (Test-Path -LiteralPath $NmrScript)) { throw "STOP: nmr_metric.py not found at $NmrScript" }
    $h = (Get-FileHash -LiteralPath $NmrScript -Algorithm MD5).Hash
    if ($h -ne $NmrMd5Exp) { throw "STOP: nmr_metric.py MD5 $h does not match certified $NmrMd5Exp" }
    if (-not (Select-String -LiteralPath $NmrScript -Pattern $NmrSentinel -Quiet)) {
        throw "STOP: sentinel $NmrSentinel not found inside $NmrScript"
    }
    Write-Host "[GATE] scorer verified: MD5 $h, sentinel $NmrSentinel"
}

function Load-Manifest {
    if (-not (Test-Path -LiteralPath $Manifest)) { throw "STOP: manifest not found at $Manifest (run pull_heldout_REV1.ps1)" }
    $mf = Import-Csv -LiteralPath $Manifest
    if (-not $mf -or $mf.Count -lt 1) { throw "STOP: manifest empty: $Manifest" }
    $map = @{}
    foreach ($r in $mf) { $map[([string]$r.file).ToLower()] = ([string]$r.md5).Trim().ToUpper() }
    Write-Host "[GATE] verified manifest entries=$($map.Count)"
    return $map
}

function Build-NmrArgs([string]$ref, [string]$test) {
    $a = @()
    foreach ($tok in ($NmrArgsTemplate -split ' ')) {
        $t = $tok.Trim('"')
        $a += $t.Replace('{REF}', $ref).Replace('{TEST}', $test)
    }
    return ,$a
}

function Parse-Nmr([string[]]$lines) {
    $cand = $lines | Where-Object { $_ -match 'NMR' -and $_ -match '(-?\d+\.\d+)' } | Select-Object -Last 1
    if (-not $cand) { $cand = $lines | Where-Object { $_ -match '(-?\d+\.\d+)' } | Select-Object -Last 1 }
    if ($cand -and $cand -match '(-?\d+\.\d+)') { return [double]$Matches[1] }
    return $null
}

function Parse-Diag([string[]]$lines) {
    $d = @{ frames = $null; skip = $null }
    $cand = $lines | Where-Object { $_ -match 'frames=(\d+)' } | Select-Object -Last 1
    if ($cand -and $cand -match 'frames=(\d+)') { $d.frames = [int]$Matches[1] }
    if ($cand -and $cand -match 'skip=(\d+)')   { $d.skip   = [int]$Matches[1] }
    return $d
}

# ---------- gates ----------
Assert-Scorer
$ManifestMap = Load-Manifest

# ---------- resolve refs (exact names) ----------
$RefInfo = @{}
$missingRefs = @()
foreach ($cell in $Cells) { foreach ($stim in $Stims) {
    $p = Join-Path $RefDir ("anchor_{0}_ref32_{1}.f32" -f $stim, $cell)
    if (-not (Test-Path -LiteralPath $p)) { Write-Host ("[REF ] {0,-10} {1,-6} MISSING {2}" -f $cell, $stim, $p); $missingRefs += "$cell/$stim"; continue }
    $it = Get-Item -LiteralPath $p
    $rm = (Get-FileHash -LiteralPath $p -Algorithm MD5).Hash
    Write-Host ("[REF ] {0,-10} {1,-6} {2}  {3} B  MD5 {4}" -f $cell, $stim, $it.Name, $it.Length, $rm)
    $RefInfo["$cell|$stim"] = [pscustomobject]@{ File=$it; Md5=$rm }
} }

# ---------- resolve board grid (exact names) ----------
$Rows = @(); $Missing = @()
foreach ($cell in $Cells) { foreach ($stim in $Stims) { foreach ($w in $Widths) {
    $p = Join-Path $BoardDir ("board_{0}_{1}_w{2}.f32" -f $stim, $cell, $w)
    if (Test-Path -LiteralPath $p) { $Rows += [pscustomobject]@{ Cell=$cell; Stim=$stim; W=$w; File=(Get-Item -LiteralPath $p) } }
    else { $Missing += ("{0} {1} w{2}" -f $cell, $stim, $w) }
} } }
$Expected = $Cells.Count * $Stims.Count * $Widths.Count
Write-Host ("[GRID] resolved {0}/{1} board files; missing {2}" -f $Rows.Count, $Expected, $Missing.Count)
if ($Missing.Count -gt 0) { $Missing | ForEach-Object { Write-Host "  MISSING: $_" } }

# ---------- preflight exit ----------
if (-not $Go) {
    Write-Host ""
    Write-Host "----- scorer --help (confirm `$NmrArgsTemplate against this) -----"
    $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & $Python $NmrScript --help 2>&1 | Select-Object -First 40 | ForEach-Object { Write-Host ([string]$_) } }
    catch { Write-Host "(--help raised: $_)" }
    $ErrorActionPreference = $prevEAP
    Write-Host "------------------------------------------------------------------"
    Write-Host "PREFLIGHT ONLY. Re-run with -Go to score. Nothing was scored, nothing written."
    exit 0
}

if (($Rows.Count -ne $Expected) -and (-not $AllowPartial)) {
    throw ("STOP: {0}/{1} rows resolved and -AllowPartial not set" -f $Rows.Count, $Expected)
}
if ($missingRefs.Count -gt 0) { throw ("STOP: missing refs for: {0}" -f ($missingRefs -join ", ")) }

# ---------- incremental skip set ----------
$Done = @{}
if (Test-Path -LiteralPath $OutCsv) {
    foreach ($r in (Import-Csv -LiteralPath $OutCsv)) {
        if ($r.status -eq "OK") { $Done[("{0}|{1}|{2}" -f $r.cell, $r.stim, $r.width)] = $true }
    }
    Write-Host ("[INCR] existing CSV found; {0} prior OK rows will be skipped" -f $Done.Count)
}

# ---------- scoring loop ----------
Start-Transcript -Path $LogFile -Append | Out-Null
try {
    $RunId = Get-Date -Format "yyyyMMdd_HHmmss"
    $sw = [System.Diagnostics.Stopwatch]::new()
    $n = 0; $ok = 0; $warnInv = 0; $vfail = 0; $rfail = 0; $skip = 0; $lenmm = 0; $mmiss = 0; $pfail = 0; $ffail = 0
    $rowSecs = @()

    foreach ($row in ($Rows | Sort-Object Cell, Stim, W)) {
        $key = "{0}|{1}|{2}" -f $row.Cell, $row.Stim, $row.W
        if ($Done.ContainsKey($key)) { $skip++; continue }
        $n++
        $bf = $row.File
        $ref = $RefInfo["$($row.Cell)|$($row.Stim)"]
        $status = ""; $nmr = ""; $tail = ""; $bmd5 = ""; $diag = @{ frames = ""; skip = "" }

        # manifest verify
        $mkey = $bf.Name.ToLower()
        if (-not $ManifestMap.ContainsKey($mkey)) {
            $status = "MANIFEST_MISSING"; $mmiss++
        } else {
            $bmd5 = (Get-FileHash -LiteralPath $bf.FullName -Algorithm MD5).Hash
            if ($bmd5 -ne $ManifestMap[$mkey]) { $status = "VERIFY_FAIL"; $vfail++ }
        }

        # cheap length pre-check
        if (-not $status) {
            if ($bf.Length -ne $ref.File.Length) { $status = "LEN_MISMATCH"; $lenmm++ }
        }

        $el = 0.0
        if (-not $status) {
            $nmrArgs = Build-NmrArgs $ref.File.FullName $bf.FullName
            $sw.Restart()
            $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
            $out = & $Python $NmrScript @nmrArgs 2>&1 | ForEach-Object { $_.ToString() }
            $code = $LASTEXITCODE
            $ErrorActionPreference = $prevEAP
            $sw.Stop()
            $el = [math]::Round($sw.Elapsed.TotalSeconds, 1)
            $rowSecs += $el
            $tail = (($out | Select-Object -Last 2) -join " | ")
            $diag = Parse-Diag $out
            if ($code -ne 0) { $status = "RUN_FAIL"; $rfail++ }
            elseif ($out -match 'WARN') { $status = "INVALID_WARN"; $warnInv++; $nmr = Parse-Nmr $out }
            else {
                $nmr = Parse-Nmr $out
                if ($null -eq $nmr) { $status = "PARSE_FAIL"; $pfail++ }
                elseif (($diag.frames -ne $ExpectFrames[$row.Stim]) -or ($diag.skip -ne $ExpectSkip)) {
                    $status = "INVALID_FRAMES"; $ffail++
                }
                else { $status = "OK"; $ok++ }
            }
        }

        [pscustomobject]@{
            sentinel   = $Sentinel
            run_id     = $RunId
            timestamp  = (Get-Date -Format s)
            cell       = $row.Cell
            stim       = $row.Stim
            width      = $row.W
            board_file = $bf.Name
            board_md5  = $bmd5
            ref_file   = $ref.File.Name
            ref_md5    = $ref.Md5
            nmr_db     = $nmr
            frames     = $diag.frames
            skip_val   = $diag.skip
            status     = $status
            elapsed_s  = $el
            raw_tail   = $tail
        } | Export-Csv -LiteralPath $OutCsv -Append -NoTypeInformation

        Write-Host ("[{0,3}] {1,-10} {2,-6} w{3,-2} {4,-14} {5,7}s  {6}" -f $n, $row.Cell, $row.Stim, $row.W, $status, $el, $nmr)
    }

    Write-Host ""
    Write-Host ("SUMMARY  ok={0} invalid_warn={1} invalid_frames={2} verify_fail={3} run_fail={4} parse_fail={5} len_mismatch={6} manifest_missing={7} skipped_prior_ok={8}" -f `
        $ok, $warnInv, $ffail, $vfail, $rfail, $pfail, $lenmm, $mmiss, $skip)
    if ($rowSecs.Count -gt 0) {
        $mean = ($rowSecs | Measure-Object -Average).Average
        Write-Host ("CALIBRATION  mean={0:N1} s/row  rate={1:N1} rows/hour" -f $mean, (3600.0 / $mean))
    }
    Write-Host ("CSV: {0}" -f $OutCsv)
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
