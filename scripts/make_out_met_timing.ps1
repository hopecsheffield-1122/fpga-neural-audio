# make_out_met_timing.ps1 - OUT_MET_SENTINEL_2026-08-09
# Builds <BITGEN>\out_met_timing\ : one timing-MET pair per (cell,width),
# UNIFORM names gru_L20_<cell>_w<W>.bit/.hwh (arm suffixes dropped).
# Arm precedence: default MET -> forced-DSP MET -> strategy-race best.
# Also writes bitstream_of_record.csv (source arm + WNS + original path per row)
# into the same folder, and verifies every copy by size.
$ErrorActionPreference = "Stop"
$OUT = "<BITGEN>\out_met_timing"
New-Item -ItemType Directory -Force -Path $OUT | Out-Null
$def = Import-Csv "<BITGEN>\build_manifest.csv"
$dsp = Import-Csv "<BITGEN>\build_manifest_dsp.csv"
$cells = @("rodent_mod","rodent_max","gt_mod","gt_max","fl_mod","fl_max")
$rows = @()
foreach ($c in $cells) {
  foreach ($w in 8..24) {
    $d = $def | Where-Object { $_.cell -eq $c -and [int]$_.width -eq $w } | Select-Object -First 1
    $arm = ""; $src = ""; $wns = ""
    if ($c -eq "rodent_max" -and $w -eq 20) {
      $arm = "default(pilot)"; $src = "<BITGEN>\out\gru_L20_rodent_max_w20"; $wns = "0.039"
    } elseif ($d -and $d.timing_met -eq "MET") {
      $arm = "default"; $src = "<BITGEN>\out\gru_L20_${c}_w${w}"; $wns = $d.wns_ns
    } else {
      $f = $dsp | Where-Object { $_.cell -eq $c -and [int]$_.width -eq $w -and $_.solution -notlike "STRAT_*" -and $_.timing_met -eq "MET" } | Select-Object -First 1
      if ($f) {
        $arm = "forced_dsp"; $src = "<BITGEN>\out_dsp\gru_L20_${c}_w${w}_dsp"; $wns = $f.wns_ns
      } else {
        $s = $dsp | Where-Object { $_.cell -eq $c -and [int]$_.width -eq $w -and $_.solution -like "STRAT_*" -and $_.timing_met -eq "MET" } | Sort-Object { [double]$_.wns_ns } -Descending | Select-Object -First 1
        if ($s) {
          $arm = "strategy_race($($s.solution -replace 'STRAT_',''))"
          $src = "<BITGEN>\out_dsp\gru_L20_${c}_w${w}_dsp_best"; $wns = $s.wns_ns
        }
      }
    }
    if (-not $src) { $rows += [pscustomobject]@{cell=$c;width=$w;arm="UNCLOSED";wns_ns="";source="";copied=$false}; continue }
    $dstBase = Join-Path $OUT "gru_L20_${c}_w${w}"
    Copy-Item "$src.bit" "$dstBase.bit" -Force
    Copy-Item "$src.hwh" "$dstBase.hwh" -Force
    $ok = ((Get-Item "$dstBase.bit").Length -eq (Get-Item "$src.bit").Length) -and ((Get-Item "$dstBase.hwh").Length -eq (Get-Item "$src.hwh").Length)
    $rows += [pscustomobject]@{ cell=$c; width=$w; arm=$arm; wns_ns=$wns; source="$src.bit"; copied=$ok }
  }
}
$rows | Export-Csv (Join-Path $OUT "bitstream_of_record.csv") -NoTypeInformation
"pairs in out_met_timing: $((Get-ChildItem $OUT -Filter '*.bit').Count)/102"
"by arm:"; $rows | Group-Object arm | Select-Object Name, Count | Format-Table -AutoSize
$bad = $rows | Where-Object { -not $_.copied }
if ($bad) { "PROBLEM ROWS:"; $bad | Format-Table cell, width, arm -AutoSize } else { "All rows copied and size-verified. Folder is board-ready." }
