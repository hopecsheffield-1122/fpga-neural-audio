# SENTINEL: WEXT-ACC40-REV2-2026-09-03
# Supersedes WEXT-ACC40-REV1 (2026-08-21), whose -DDTACC_W=40 flag was INERT:
# repro_pack/src/gru_va.h hardcodes DT_ACC<32,12> with no DTACC guard, so
# sol_w28_acc40 compiled at <32,12> and duplicated sol_w28 to the last digit.
# REV2 uses a source pack whose gru_va.h is the macro-guarded GVAR-REV1 header
# (gru_va_gvar.h, MD5 EAB6D23B...) renamed to gru_va.h, and HALTS before
# opening the project unless that header contains a DTACC_W guard.
#
# Pre-registration UNCHANGED from REV1 (clause 3 of WEXT-PREREG-REV1):
#   floor moves materially below -90.71 dB  -> ceiling was the ACC<32,12>
#                                              fraction (accumulator-bound at w28)
#   floor stays ~-90.71 (within ~2 dB)      -> ceiling is elsewhere; no
#                                              attribution without a new arm
# Precedent: ACC<40,20> vs ACC<32,12> bit-identical at w8/w12/w20 (GVAR-REV1,
# gb_metrics_REV1 acc40_w20 rows, dumps MD5-identical). Golden-mode csim only;
# rodent_max weights; no deployability claim.
#
# Machine: LENNY. Env: WEXT_SRCPACK = C:/hb/wext_acc40_pack ; WEXT_DIR = C:/hb/wext_probe
set PACK $::env(WEXT_SRCPACK)
set HERE $::env(WEXT_DIR)
set SRC  "$PACK/src"
set TDD  "$PACK/testdata"
set OUTD "$HERE/out"
file mkdir $OUTD
set W 28
set DUMP "$OUTD/golden_wext_w28_acc40_REV2.f32"
if {[file exists $DUMP]} {
    puts "FATAL: $DUMP exists (fail-if-exists)"
    exit 1
}
if {[file exists "$HERE/wext_acc40_REV2_prj"]} {
    puts "FATAL: project dir wext_acc40_REV2_prj exists (fail-if-exists)"
    exit 1
}
# GUARD: the header must actually expose DTACC_W, or this run repeats REV1.
set fh [open "$SRC/gru_va.h" r]
set hdr [read $fh]
close $fh
if {[string first "DTACC_W" $hdr] < 0} {
    puts "FATAL: $SRC/gru_va.h has no DTACC_W guard -- flag would be inert (REV1 failure mode)"
    exit 1
}
puts "GUARD PASS: $SRC/gru_va.h exposes DTACC_W"
puts "WEXT-ACC40-REV2 srcpack=$PACK out=$OUTD"
open_project -reset wext_acc40_REV2_prj
set_top gru_va
set CF "-I$SRC -DDTW_W=$W -DDTW_I=5 -DDTACT_W=$W -DDTACT_I=2 -DDTACC_W=40 -DDTACC_I=20 -DQMODE=AP_RND_CONV -DP_COLS=40 -DALLOC_MAC3_LIMIT=20"
puts "==> wext acc40 REV2 w$W: START cflags = $CF"
open_solution -reset "sol_w28_acc40_REV2" -flow_target vivado
set_part {xc7z020clg400-1}
create_clock -period 10 -name default
add_files $SRC/gru_va_col_fused_mac3.cpp -cflags $CF
add_files $SRC/gru_load.cpp -cflags $CF
add_files -tb $SRC/gru_va_tb_fm2.cpp -cflags $CF
if {[catch {csim_design -O -argv "golden $TDD $DUMP"} err]} {
    puts "==> wext acc40 REV2 w$W: csim TB-gate NONZERO (metrics in log): $err"
} else {
    puts "==> wext acc40 REV2 w$W: csim complete"
}
puts "WEXT-ACC40-REV2 COMPLETE"
exit
# SENTINEL-END: WEXT-ACC40-REV2-2026-09-03
