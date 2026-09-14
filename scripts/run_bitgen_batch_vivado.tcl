# run_bitgen_batch_vivado.tcl
# BITGEN_BATCH_VIVADO_SENTINEL_2026-08-08_NAS_REV4
# REV4: consumes solutions from short root C:/hb. Per-build catch; export must
# be complete (component.xml) and settled (>=3 min) before building.
set CELLS  {rodent_mod rodent_max gt_mod gt_max fl_mod fl_max}
set WIDTHS {8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24}
set OUT "<BITGEN>/out"
set REP "<BITGEN>/reports"
set MANIFEST "<BITGEN>/build_manifest.csv"
set SCRATCH "<USER_HOME>/bitgen"
file mkdir $OUT
file mkdir $REP
file mkdir $SCRATCH
if {![file exists $MANIFEST]} {
    set mf [open $MANIFEST w]
    puts $mf "cell,width,solution,wns_ns,timing_met,bit_path,build_end"
    close $mf
}
proc build_one {CELL W OUT REP SCRATCH MANIFEST} {
    set TAG "gru_L20_${CELL}_w${W}"
    set SOL "C:/hb/b_${CELL}/sol_${CELL}_w${W}"
    set PRJ "$SCRATCH/${TAG}"
    create_project ${TAG} $PRJ -part xc7z020clg400-1 -force
    set_property ip_repo_paths [list $SOL] [current_project]
    update_ip_catalog
    source <USER_HOME>/gru_va_bin/gru_bin_version_bd_export.tcl
    make_wrapper -files [get_files gru_bin_version.bd] -top
    add_files -norecurse $PRJ/${TAG}.gen/sources_1/bd/gru_bin_version/hdl/gru_bin_version_wrapper.v
    update_compile_order -fileset sources_1
    launch_runs impl_1 -to_step write_bitstream -jobs 4
    wait_on_run impl_1
    set BIT "$PRJ/${TAG}.runs/impl_1/gru_bin_version_wrapper.bit"
    set HWH "$PRJ/${TAG}.gen/sources_1/bd/gru_bin_version/hw_handoff/gru_bin_version.hwh"
    if {![file exists $BIT]} { error "impl finished but no bitstream at $BIT" }
    file copy -force $BIT "$OUT/${TAG}.bit"
    file copy -force $HWH "$OUT/${TAG}.hwh"
    file mkdir "$REP/${TAG}"
    foreach r [glob -nocomplain "$PRJ/${TAG}.runs/impl_1/*timing_summary_routed.rpt" "$PRJ/${TAG}.runs/impl_1/*utilization_placed.rpt" "$PRJ/${TAG}.runs/impl_1/*power_routed.rpt"] {
        file copy -force $r "$REP/${TAG}/"
    }
    open_run impl_1
    set WNS [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
    set MET [expr {$WNS >= 0 ? "MET" : "FAIL"}]
    close_design
    set mf [open $MANIFEST a]
    puts $mf "$CELL,$W,sol_${CELL}_w${W},$WNS,$MET,$OUT/${TAG}.bit,[clock format [clock seconds]]"
    close $mf
    if {[file size "$OUT/${TAG}.bit"] == [file size $BIT] && [file exists "$OUT/${TAG}.hwh"]} {
        catch {close_project}
        file delete -force $PRJ
        puts "DONE $TAG WNS=$WNS $MET (archived to NAS, local scratch deleted)"
    } else {
        catch {close_project}
        puts "DONE $TAG WNS=$WNS $MET -- NAS COPY UNVERIFIED, local project KEPT at $PRJ"
    }
}
foreach CELL $CELLS {
    foreach W $WIDTHS {
        set TAG "gru_L20_${CELL}_w${W}"
        if {[file exists "$OUT/${TAG}.bit"]} { puts "SKIP $TAG (on NAS)"; continue }
        set SOL "C:/hb/b_${CELL}/sol_${CELL}_w${W}"
        set CXML "$SOL/impl/ip/component.xml"
        if {![file exists $CXML]} { puts "NOIP $TAG (export not complete)"; continue }
        if {[expr {[clock seconds] - [file mtime $CXML]}] < 180} { puts "FRESH $TAG (export <3 min old, next pass)"; continue }
        if {[catch {build_one $CELL $W $OUT $REP $SCRATCH $MANIFEST} err]} {
            catch {close_project}
            set mf [open $MANIFEST a]
            puts $mf "$CELL,$W,sol_${CELL}_w${W},,BUILD_ERROR,,[clock format [clock seconds]]"
            close $mf
            puts "BUILD_ERROR $TAG : $err (local project kept, pass continues)"
        }
    }
}
puts "BATCH VIVADO SWEEP COMPLETE"
exit
