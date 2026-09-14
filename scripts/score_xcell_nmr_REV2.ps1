# SCORE-XCELLNMR-REV2
# REV1->REV2: adds --skip 1024 (campaign washout convention, FINAL85 sec.1);
# adds frames/skip validity gate (frames must = 8794, skip must = 1024, else INVALID_FRAMES).
# REV1 rows (skip=0) superseded; REV1 CSV retained per annotate-never-delete (pair rule to NAS).
# Tranche-1 cross-cell NMR: 5 non-anchor cells x 17 widths (w8-w24) on board_nam outputs
# vs per-cell float references. Machine: Lenny (Windows, PowerShell).
# Doubles as the NMR throughput CALIBRATION run (rows/hour printed at end).
#
# Enforced rules:
#   - Scorer instrument gate: nmr_metric.py MD5 + sentinel verified before anything runs
#   - Every board file manifest-MD5-verified before scoring (no verify -> no score)
#   - Any 'WARN' in scorer output => row status INVALID_WARN (auto-invalidate rule)
#   - Incremental append, annotate-never-delete: reruns append; prior OK rows are skipped
#   - Anchor cell (rodent_max) excluded by hard guard
#
# Modes:
#   (no switch)   PREFLIGHT: verify gates, print scorer --help, resolve every file, count vs 85, EXIT
#   -Go           score
#   -Go -AllowPartial   score even if discovered rows != 85 (missing pairs listed either way)

param(
    [switch]$Go,
    [switch]$AllowPartial
)

$ErrorActionPreference = "Stop"
$Sentinel = "SCORE-XCELLNMR-REV2"

# ============================ CONFIG (real values) ============================
$Python      = "<USER_HOME>\venvs\gru\Scripts\python.exe"
$NmrScript   = "<GRU_DIR>\nmr_metric.py"
$NmrMd5Exp   = "3098CB25C61E8099E313D0A2520367CD"   # certified NMR-REV2 hash record
$NmrSentinel = "NMR-REV2"
$BoardDir    = "<NAS>\board_campaign_2026-08-10"
$Manifest    = "<NAS>\board_campaign_2026-08-10\verified_manifest.csv"
$RefDir      = "<USER_HOME>\hls\gru_va\hls_io"
$OutCsv      = "<GRU_DIR>\xcell_nmr_tranche1B.csv"
$LogFile     = "<GRU_DIR>\xcell_nmr_tranche1B_log.txt"
$Cells       = @("rodent_mod","gt_mod","gt_max","fl_mod","fl_max")
$AnchorCell  = "rodent_max"
$Widths      = 8..24
$RequireNamToken = $true    # board_nam files must contain 'nam' (excludes battery files on same NAS dir)
# Invocation template for nmr_metric.py -- CONFIRM against the --help printed in preflight:
$NmrArgsTemplate = '--ref "{REF}" --test "{TEST}" --skip 1024'
$ExpectSkip   = 1024
$ExpectFrames = 8794   # (9007200-1024-2048)/1024 + 1
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
    if (-not (Test-Path -LiteralPath $Manifest)) { throw "STOP: manifest not found at $Manifest" }
    $mf = Import-Csv -LiteralPath $Manifest
    if (-not $mf -or $mf.Count -lt 1) { throw "STOP: manifest empty: $Manifest" }
    $cols    = $mf[0].psobject.Properties.Name
    $md5col  = $cols | Where-Object { $_ -match 'md5|hash' } | Select-Object -First 1
    $filecol = $cols | Where-Object { $_ -match 'file|name|path' } | Select-Object -First 1
    if (-not $md5col -or -not $filecol) {
        throw ("STOP: could not auto-detect manifest columns. Columns present: {0}" -f ($cols -join ", "))
    }
    Write-Host "[GATE] manifest columns: file='$filecol' md5='$md5col'  entries=$($mf.Count)"
    $map = @{}
    foreach ($r in $mf) {
        $leaf = [IO.Path]::GetFileName([string]$r.$filecol)
        if ($leaf) { $map[$leaf.ToLower()] = ([string]$r.$md5col).Trim().ToUpper() }
    }
    return $map
}

function Resolve-Ref([string]$cell) {
    $exact = Join-Path $RefDir ("{0}_nam_ref32.f32" -f $cell)
    if (Test-Path -LiteralPath $exact) { return (Get-Item -LiteralPath $exact) }
    $g = @(Get-ChildItem -LiteralPath $RefDir -Filter "*.f32" -File | Where-Object {
        $_.Name -match [regex]::Escape($cell) -and $_.Name -match 'nam' -and $_.Name -match 'ref' })
    if ($g.Count -eq 1) { return $g[0] }
    if ($g.Count -eq 0) { return $null }
    throw ("STOP: ambiguous ref for {0}: {1}" -f $cell, ((@($g.Name)) -join ", "))
}

# Cache the board directory listing once (NAS recursion is slow)
Write-Host "[SCAN] listing $BoardDir ..."
$AllBoard = @(Get-ChildItem -LiteralPath $BoardDir -Recurse -File | Where-Object {
    ($_.Extension -eq ".f32" -or $_.Extension -eq ".bin") })
Write-Host ("[SCAN] {0} candidate files (.f32/.bin) under board dir" -f $AllBoard.Count)

function Resolve-Board([string]$cell, [int]$w) {
    $rx = "(^|[_\-])w0?$w([_\-\.])"
    $hits = @($AllBoard | Where-Object {
        $_.Name -match [regex]::Escape($cell) -and
        $_.Name -notmatch [regex]::Escape($AnchorCell) -and
        ((-not $RequireNamToken) -or ($_.Name -match 'nam')) -and
        $_.Name -match $rx })
    if ($hits.Count -eq 1) { return $hits[0] }
    if ($hits.Count -eq 0) { return $null }
    throw ("STOP: ambiguous board file for {0} w{1}: {2}" -f $cell, $w, ((@($hits.Name)) -join ", "))
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

# ---------- resolve refs ----------
$RefInfo = @{}
foreach ($cell in $Cells) {
    if ($cell -eq $AnchorCell) { throw "STOP: anchor cell in cell list" }
    $r = Resolve-Ref $cell
    if ($null -eq $r) {
        Write-Host ("[REF ] {0,-12} MISSING (looked for {0}_nam_ref32.f32 then *{0}*nam*ref*.f32 in {1})" -f $cell, $RefDir)
        $RefInfo[$cell] = $null
    } else {
        $rm = (Get-FileHash -LiteralPath $r.FullName -Algorithm MD5).Hash
        Write-Host ("[REF ] {0,-12} {1}  {2} B  MD5 {3}" -f $cell, $r.Name, $r.Length, $rm)
        $RefInfo[$cell] = [pscustomobject]@{ File=$r; Md5=$rm }
    }
}

# ---------- resolve board grid ----------
$Rows = @()
$Missing = @()
foreach ($cell in $Cells) {
    foreach ($w in $Widths) {
        $b = Resolve-Board $cell $w
        if ($null -eq $b) { $Missing += "{0} w{1}" -f $cell, $w }
        else { $Rows += [pscustomobject]@{ Cell=$cell; W=$w; File=$b } }
    }
}
$Expected = $Cells.Count * $Widths.Count
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
$missingRefs = @($Cells | Where-Object { $null -eq $RefInfo[$_] })
if ($missingRefs.Count -gt 0) { throw ("STOP: missing refs for: {0}" -f ($missingRefs -join ", ")) }

# ---------- incremental skip set ----------
$Done = @{}
if (Test-Path -LiteralPath $OutCsv) {
    foreach ($r in (Import-Csv -LiteralPath $OutCsv)) {
        if ($r.status -eq "OK") { $Done[("{0}|{1}" -f $r.cell, $r.width)] = $true }
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

    foreach ($row in ($Rows | Sort-Object Cell, W)) {
        $key = "{0}|{1}" -f $row.Cell, $row.W
        if ($Done.ContainsKey($key)) { $skip++; continue }
        $n++
        $bf = $row.File
        $ref = $RefInfo[$row.Cell]
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
                elseif (($diag.frames -ne $ExpectFrames) -or ($diag.skip -ne $ExpectSkip)) {
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

        Write-Host ("[{0,3}] {1,-12} w{2,-2} {3,-14} {4,7}s  {5}" -f $n, $row.Cell, $row.W, $status, $el, $nmr)
    }

    Write-Host ""
    Write-Host ("SUMMARY  ok={0} invalid_warn={1} invalid_frames={2} verify_fail={3} run_fail={4} parse_fail={5} len_mismatch={6} manifest_missing={7} skipped_prior_ok={8}" -f `
        $ok, $warnInv, $ffail, $vfail, $rfail, $pfail, $lenmm, $mmiss, $skip)

    if ($rowSecs.Count -gt 0) {
        $mean = ($rowSecs | Measure-Object -Average).Average
        $rph  = 3600.0 / $mean
        Write-Host ("CALIBRATION  mean={0:N1} s/row  rate={1:N1} rows/hour" -f $mean, $rph)
        Write-Host ("PROJECTION   425-row expansion at this rate = {0:N1} h Lenny-solo ({1:N1} h for the remaining 340)" -f (425.0/$rph), (340.0/$rph))
    }
    Write-Host ("CSV: {0}" -f $OutCsv)
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
