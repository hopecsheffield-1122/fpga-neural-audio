# run_batch_hls_rodent_max.tcl — generated from run_batch_hls_template.tcl
# BITGEN_BATCH_HLS_rodent_max_SENTINEL
open_project gru_va_batch_rodent_max
set_top gru_va
set SRC "<USER_HOME>/hls/gru_va/build_src/rodent_max"
foreach W {20 18 16 14 13 12 11 10 9 8 15 17 19 21 22 23 24} {
    set SOL "sol_rodent_max_w${W}"
    if {[file exists "<USER_HOME>/VitisProjects/gru_va_batch_rodent_max/${SOL}/impl/ip"]} {
        puts "==> ${SOL}: SKIP (already exported)"
        continue
    }
    set CF "-DDTW_W=${W} -DDTW_I=5 -DDTACT_W=${W} -DDTACT_I=2 -DP_COLS=40 -DALLOC_MAC3_LIMIT=20"
    open_solution ${SOL} -reset
    set_part {xc7z020clg400-1}
    create_clock -period 10 -name default
    add_files $SRC/gru_va_col_fused_mac3.cpp -cflags $CF
    add_files $SRC/gru_load.cpp -cflags $CF
    add_files -tb $SRC/gru_va_tanh_0_tb.cpp -cflags $CF
    if {[catch {csim_design} err]} { puts "==> ${SOL}: csim FAILED: $err"; continue }
    puts "==> ${SOL}: csim complete"
    if {[catch {csynth_design} err]} { puts "==> ${SOL}: csynth FAILED: $err"; continue }
    if {[catch {export_design -rtl verilog -format ip_catalog} err]} { puts "==> ${SOL}: export FAILED: $err"; continue }
    puts "==> ${SOL}: EXPORTED"
}
puts "CELL rodent_max COMPLETE"
exit

