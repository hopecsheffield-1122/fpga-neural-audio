# SENTINEL: WEXT-PROBE-REV1-2026-08-21
# Guard-bit / width-extension probe: golden csims at w28 and w32 on the
# anchor cell (rodent_max), deployed semantics otherwise unchanged
# (ACC<32,12>, AP_RND_CONV, P_COLS=40, MAC3 limit 20, table-1025 tanh).
# Purpose: locate the storage-width ceiling above w24 (accumulator vs
# activation-table attribution deferred to a later ACC40 arm per pre-reg
# WEXT-PREREG-REV1). csim ONLY -- numerics, not deployability; w28/w32
# multipliers exceed DSP48 native widths and no fit claim is made.
# Invocation mirrors REPRO-GOLDEN-REV1 (itself adapted from the
# fleet-certified GBXCELL-REV1 gate arm). Dumps are first-recorded
# artifacts: no certified reference exists at these widths yet.
set PACK $::env(WEXT_SRCPACK)
set HERE $::env(WEXT_DIR)
set SRC  "$PACK/src"
set TDD  "$PACK/testdata"
set OUTD "$HERE/out"
file mkdir $OUTD
puts "WEXT-PROBE-REV1 srcpack=$PACK out=$OUTD"
open_project -reset wext_prj
set_top gru_va
foreach W {28 32} {
    set DUMP "$OUTD/golden_wext_w${W}.f32"
    if {[file exists $DUMP]} {
        puts "FATAL: $DUMP exists (fail-if-exists)"
        exit 1
    }
    set CF "-I$SRC -DDTW_W=$W -DDTW_I=5 -DDTACT_W=$W -DDTACT_I=2 -DDTACC_W=32 -DDTACC_I=12 -DQMODE=AP_RND_CONV -DP_COLS=40 -DALLOC_MAC3_LIMIT=20"
    puts "==> wext w$W: START cflags = $CF"
    open_solution -reset "sol_w${W}" -flow_target vivado
    set_part {xc7z020clg400-1}
    create_clock -period 10 -name default
    add_files $SRC/gru_va_col_fused_mac3.cpp -cflags $CF
    add_files $SRC/gru_load.cpp -cflags $CF
    add_files -tb $SRC/gru_va_tb_fm2.cpp -cflags $CF
    if {[catch {csim_design -O -argv "golden $TDD $DUMP"} err]} {
        puts "==> wext w$W: csim TB-gate NONZERO (metrics in log): $err"
    } else {
        puts "==> wext w$W: csim complete"
    }
}
puts "WEXT-PROBE-REV1 COMPLETE (w28, w32)"
exit
# SENTINEL-END: WEXT-PROBE-REV1-2026-08-21
