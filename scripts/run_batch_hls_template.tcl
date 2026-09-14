# run_batch_hls___CELL__.tcl — generated from run_batch_hls_template.tcl
# BITGEN_BATCH_HLS___CELL___SENTINEL_REV3
# REV3: short project root C:/hb (fixes export_design "input line is too long"
# cmd.exe 8191-char limit at widths 17/19/21/22/23). csim TB-gate non-blocking.
# Skip check = component.xml (partial exports rebuild).
# NOTE: orchestrator must cd to C:\hb before vitis-run.
open_project b___CELL__
set_top gru_va
set SRC "<USER_HOME>/hls/gru_va/build_src/__CELL__"
foreach W {20 18 16 14 13 12 11 10 9 8 15 17 19 21 22 23 24} {
    set SOL "sol___CELL___w${W}"
    if {[file exists "C:/hb/b___CELL__/${SOL}/impl/ip/component.xml"]} {
        puts "==> ${SOL}: SKIP (complete export exists)"
        continue
    }
    set CF "-DDTW_W=${W} -DDTW_I=5 -DDTACT_W=${W} -DDTACT_I=2 -DP_COLS=40 -DALLOC_MAC3_LIMIT=20"
    open_solution ${SOL} -reset
    set_part {xc7z020clg400-1}
    create_clock -period 10 -name default
    add_files $SRC/gru_va_col_fused_mac3.cpp -cflags $CF
    add_files $SRC/gru_load.cpp -cflags $CF
    add_files -tb $SRC/gru_va_tanh_0_tb.cpp -cflags $CF
    if {[catch {csim_design} err]} {
        puts "==> ${SOL}: csim TB-gate NONZERO (metrics in log; proceeding): $err"
    } else {
        puts "==> ${SOL}: csim complete"
    }
    if {[catch {csynth_design} err]} { puts "==> ${SOL}: csynth FAILED: $err"; continue }
    if {[catch {export_design -rtl verilog -format ip_catalog} err]} { puts "==> ${SOL}: export FAILED: $err"; continue }
    puts "==> ${SOL}: EXPORTED"
}
puts "CELL __CELL__ COMPLETE"
exit
