# SENTINEL: REPRO-GOLDEN-REV2-2026-09-10
# One-width golden reproduction of the anchor model (rodent_max) in the
# deployed configuration: same kernel, same testbench, same cflags as the
# 102-build campaign (W-bit weights <W,5> and activations <W,2>,
# accumulators <32,12>, AP_RND_CONV, P_COLS=40, mac3 instance limit 20).
# Width arrives via env REPRO_W; pack root via env REPRO_DIR.
# Runs C simulation only (~2-3 min). The dump lands in <pack>/out/ and is
# verified by repro_verify.py against expected_golden.csv, whose hashes
# equal both the campaign's C-simulation export and the FPGA capture.
# REV2: header comments only; the build commands are unchanged from REV1.
set W    $::env(REPRO_W)
set PACK $::env(REPRO_DIR)
set SRC  "$PACK/src"
set TDD  "$PACK/testdata"
set OUTD "$PACK/out"
file mkdir $OUTD
set DUMP "$OUTD/golden_repro_w${W}.f32"
if {[file exists $DUMP]} {
    puts "FATAL: $DUMP exists (fail-if-exists; delete or rename previous run)"
    exit 1
}
puts "REPRO-GOLDEN-REV2 width=$W pack=$PACK"
open_project -reset repro_prj
set_top gru_va
set CF "-I$SRC -DDTW_W=$W -DDTW_I=5 -DDTACT_W=$W -DDTACT_I=2 -DDTACC_W=32 -DDTACC_I=12 -DQMODE=AP_RND_CONV -DP_COLS=40 -DALLOC_MAC3_LIMIT=20"
puts "==> cflags = $CF"
open_solution -reset "sol_w${W}" -flow_target vivado
set_part {xc7z020clg400-1}
create_clock -period 10 -name default
add_files $SRC/gru_va_col_fused_mac3.cpp -cflags $CF
add_files $SRC/gru_load.cpp -cflags $CF
add_files -tb $SRC/gru_va_tb_fm2.cpp -cflags $CF
if {[catch {csim_design -O -argv "golden $TDD $DUMP"} err]} {
    puts "==> csim returned nonzero (expected at low widths where the TB's cosine gate fails; metrics still in log): $err"
} else {
    puts "==> csim complete"
}
puts "REPRO-GOLDEN-REV2 DONE width=$W dump=$DUMP"
exit
# SENTINEL-END: REPRO-GOLDEN-REV2-2026-09-10
