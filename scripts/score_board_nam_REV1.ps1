# =====================================================================
# SCORE-BOARDNAM-REV1
# B2 scoring wrapper: 102 board_nam outputs -> hls_metrics.py v4
#   - MD5-verifies every file against verified_manifest.csv BEFORE scoring
#     (mismatch => row not scored, logged as VERIFY_FAIL)
#   - rodent_max rows: two passes (target + float ref)
#   - other cells:     float-ref pass only, file anchor_nam_ref32_<cell>.f32
#     (missing per-cell ref => row logged as NOREF, not scored, rerun-safe)
#   - incremental: labels already present in the output CSV are skipped
#   - output CSV: board_nam_metrics.csv (fresh lineage; never appends to
#     hls_target_metrics_postlock.csv)
# Run on LENNY from the GRU working directory with the gru venv active:
#   & "<VENV>\Scripts\Activate.ps1"
#   cd "<GRU_DIR>"
#   .\score_board_nam_REV1.ps1
# =====================================================================

$Sentinel = "SCORE-BOARDNAM-REV1"
Write-Host "== $Sentinel =="

# ---- configuration (all paths explicit) -----------------------------
$NasDir   = "<NAS>\board_campaign_2026-08-10"
$HlsIo    = "<HLS_IO>"
$WorkDir  = "<GRU_DIR>"
$Manifest = Join-Path $NasDir "verified_manifest.csv"
$OutCsv   = Join-Path $WorkDir "board_nam_metrics.csv"
$Scorer   = Join-Path $WorkDir "hls_metrics.py"

$TargetRef = Join-Path $HlsIo "anchor_nam_target.f32"   # rodent_max target
$FloatRefAnchor = Join-Path $HlsIo "anchor_nam_ref32.f32" # rodent_max float ref

$Cells  = @("rodent_max","rodent_mod","gt_max","gt_mod","fl_max","fl_mod")
$Widths = 8..24
$ExpectedBytes = 36028800

# ---- preflight ------------------------------------------------------
foreach ($p in @($NasDir, $Manifest, $Scorer, $TargetRef, $FloatRefAnchor)) {
    if (-not (Test-Path $p)) {
        Write-Host "FATAL: missing required path: $p"
        exit 1
    }
}
$sentCheck = Select-String -Path $Scorer -Pattern "HLSMETRICS-V4-REV1" -SimpleMatch -Quiet
if (-not $sentCheck) {
    Write-Host "FATAL: hls_metrics.py does not carry sentinel HLSMETRICS-V4-REV1"
    exit 1
}

# manifest into memory once; lookup = line containing filename + 32-hex token
$ManifestLines = Get-Content $Manifest

function Get-ManifestMd5([string]$fname) {
    foreach ($line in $ManifestLines) {
        if ($line -match [regex]::Escape($fname)) {
            if ($line -match "([0-9a-fA-F]{32})") { return $Matches[1].ToLower() }
        }
    }
    return $null
}

# existing labels for incremental skip
$DoneLabels = @{}
if (Test-Path $OutCsv) {
    foreach ($line in (Get-Content $OutCsv)) {
        $lbl = ($line -split ",")[0]
        if ($lbl) { $DoneLabels[$lbl] = $true }
    }
}

# ---- pass runner ----------------------------------------------------
function Invoke-Pass([string]$hlsPath, [string]$refPath, [string]$label) {
    # returns "OK" | "SKIP" | "FAIL"
    if ($script:DoneLabels.ContainsKey($label)) { return "SKIP" }
    python $script:Scorer --hls $hlsPath --target $refPath --skip 1024 --window-sec 30 --label $label --csv $script:OutCsv
    if ($LASTEXITCODE -ne 0) { return "FAIL" }
    $script:DoneLabels[$label] = $true
    return "OK"
}

# ---- main loop ------------------------------------------------------
$nScored = 0; $nSkipped = 0; $nFailed = 0; $nMissing = 0
$nVerifyFail = 0; $nNoRef = 0
$ProblemRows = @()

foreach ($cell in $Cells) {
    foreach ($w in $Widths) {
        $fname = "board_nam_${cell}_w${w}.f32"
        $fpath = Join-Path $NasDir $fname

        # build this row's pass list
        $passes = @()
        if ($cell -eq "rodent_max") {
            $passes += ,@{ ref = $TargetRef;      lbl = "board_${cell}_nam_w${w}" }
            $passes += ,@{ ref = $FloatRefAnchor; lbl = "board_${cell}_nam_w${w}_float_ref" }
        } else {
            $cellRef = Join-Path $HlsIo "anchor_nam_ref32_${cell}.f32"
            if (Test-Path $cellRef) {
                $passes += ,@{ ref = $cellRef; lbl = "board_${cell}_nam_w${w}_float_ref" }
            } else {
                Write-Host "NOREF       $fname (expected $cellRef)"
                $nNoRef++
                continue
            }
        }

        # if every pass label is already banked, skip before touching the NAS
        $allDone = $true
        foreach ($p in $passes) {
            if (-not $DoneLabels.ContainsKey($p.lbl)) { $allDone = $false }
        }
        if ($allDone) { $nSkipped++; continue }

        if (-not (Test-Path $fpath)) {
            Write-Host "MISSING     $fname"
            $nMissing++; $ProblemRows += "MISSING $fname"
            continue
        }

        $len = (Get-Item $fpath).Length
        if ($len -ne $ExpectedBytes) {
            Write-Host "VERIFY_FAIL $fname (length $len != $ExpectedBytes)"
            $nVerifyFail++; $ProblemRows += "VERIFY_FAIL(len) $fname"
            continue
        }

        $want = Get-ManifestMd5 $fname
        if ($null -eq $want) {
            Write-Host "VERIFY_FAIL $fname (no manifest row)"
            $nVerifyFail++; $ProblemRows += "VERIFY_FAIL(nomanifest) $fname"
            continue
        }
        $have = (Get-FileHash -Algorithm MD5 $fpath).Hash.ToLower()
        if ($have -ne $want) {
            Write-Host "VERIFY_FAIL $fname (md5 $have != manifest $want)"
            $nVerifyFail++; $ProblemRows += "VERIFY_FAIL(md5) $fname"
            continue
        }

        foreach ($p in $passes) {
            $r = Invoke-Pass $fpath $p.ref $p.lbl
            switch ($r) {
                "OK"   { Write-Host "SCORED      $($p.lbl)"; $nScored++ }
                "SKIP" { $nSkipped++ }
                "FAIL" { Write-Host "FAIL        $($p.lbl)"; $nFailed++
                         $ProblemRows += "FAIL $($p.lbl)" }
            }
        }
    }
}

# ---- summary --------------------------------------------------------
Write-Host ""
Write-Host "== $Sentinel summary =="
Write-Host "scored=$nScored skipped=$nSkipped failed=$nFailed missing=$nMissing verify_fail=$nVerifyFail noref=$nNoRef"
if ($ProblemRows.Count -gt 0) {
    Write-Host "-- problem rows --"
    $ProblemRows | ForEach-Object { Write-Host "  $_" }
}
Write-Host "output CSV: $OutCsv"
