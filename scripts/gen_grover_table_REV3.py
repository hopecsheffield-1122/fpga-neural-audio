#!/usr/bin/env python3
# SENTINEL: GTAB-REV3-2026-09-03
# gen_grover_table_REV3.py -- supersedes GTAB-REV2. Same table, but the scheduled-cycles
# column now comes from csynth_schedule_REV1.csv (HARV-CSYNTH-REV1, hashed report harvest)
# instead of a dict typed into the script. Offset law is recomputed PER BUILD (102 values),
# not per width, and the constant is printed to 2 decimals from the data.
#
# Machine: LENNY (PowerShell), venv gru. Usage:
#   python "<GRU_DIR>\gen_grover_table_REV3.py" --csv "<NAS>\board_campaign_2026-08-10\campaign_results.csv" --sched "<GRU_DIR>\csynth_schedule_REV1.csv" --outdir "<GRU_DIR>"
#
# Emits (fail-if-exists):
#   grover_latency_table_REV3.csv  -- per-width aggregate + validation columns
#   grover_latency_table_REV3.tex  -- LaTeX tabular
#
# Gates:
#   G1: campaign rows == 102, cell x width once each; fclk == 100.0 on every row
#   G2: schedule CSV has default-arm row for every (cell, width)
#   G3: per-build offset (sched - cyc_hw): spread <= 0.02 cycles across all 102 builds
#   G4: per-width cell-invariance spread of cyc_hw <= 0.01

import argparse, csv, hashlib, os, sys
from collections import defaultdict

SENTINEL = "GTAB-REV3-2026-09-03"
CELLS = {"rodent_max", "rodent_mod", "gt_max", "gt_mod", "fl_max", "fl_mod"}
WIDTHS = list(range(8, 25))

def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()

def main():
    ap = argparse.ArgumentParser(description=f"Grover latency table ({SENTINEL})")
    ap.add_argument("--csv", required=True, help="campaign_results.csv (board)")
    ap.add_argument("--sched", required=True, help="csynth_schedule_REV1.csv (HARV-CSYNTH-REV1)")
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()
    print(f"== {SENTINEL} ==")

    out_csv = os.path.join(args.outdir, "grover_latency_table_REV3.csv")
    out_tex = os.path.join(args.outdir, "grover_latency_table_REV3.tex")
    for p in (out_csv, out_tex):
        if os.path.exists(p):
            print(f"FATAL: output exists (fail-if-exists): {p}"); sys.exit(1)

    rows = list(csv.DictReader(open(args.csv, newline="")))
    print(f"campaign rows read: {len(rows)}  columns: {list(rows[0].keys())}")
    if "cell" not in rows[0]:
        print("FATAL: campaign CSV has no 'cell' column -- edit CELL_COL below to the real header name")
        sys.exit(1)
    if len(rows) != 102:
        print(f"FATAL G1: expected 102 campaign rows, got {len(rows)}"); sys.exit(1)
    seen = {(r["cell"], int(r["width"])) for r in rows}
    if len(seen) != 102 or {c for c, _ in seen} != CELLS:
        print("FATAL G1: campaign cell x width coverage wrong"); sys.exit(1)
    bad_clk = [r for r in rows if float(r["fclk_mhz"]) != 100.0]
    if bad_clk:
        print(f"FATAL G1: {len(bad_clk)} rows with fclk != 100.0"); sys.exit(1)
    print("G1 PASS")

    sched = {}
    for r in csv.DictReader(open(args.sched, newline="")):
        if r["arm"] == "default":
            sched[(r["cell"], int(r["width"]))] = int(r["sched_cyc"])
    missing = seen - set(sched)
    if missing:
        print(f"FATAL G2: schedule missing for {sorted(missing)}"); sys.exit(1)
    print(f"G2 PASS: schedule rows matched for all 102 builds  (sched MD5 {md5_of(args.sched)})")

    offsets = []
    per_w = defaultdict(list)
    for r in rows:
        key = (r["cell"], int(r["width"]))
        cyc = float(r["cyc_hw"])
        off = sched[key] - cyc
        offsets.append(off)
        per_w[key[1]].append((cyc, int(r["ksamp_s"]), float(r["fl_x_rt"]), sched[key], off))
    lo, hi = min(offsets), max(offsets)
    if hi - lo > 0.02 + 1e-9:
        print(f"FATAL G3: per-build offset not constant: {lo:.2f} .. {hi:.2f}"); sys.exit(1)
    off_const = sum(offsets) / len(offsets)
    print(f"G3 PASS: offset law constant at {off_const:.2f} cycles (spread {hi-lo:.2f}, N=102)")

    out_rows = []
    worst = 0.0
    for w in WIDTHS:
        rs = per_w[w]
        cyc = [x[0] for x in rs]
        spread = max(cyc) - min(cyc)
        worst = max(worst, spread)
        scheds = {x[3] for x in rs}
        out_rows.append({
            "width": w, "cells": len(rs),
            "sched_cyc": next(iter(scheds)) if len(scheds) == 1 else "MIXED",
            "meas_cyc_mean": f"{sum(cyc)/len(cyc):.2f}",
            "offset_cyc": f"{sum(x[4] for x in rs)/len(rs):.2f}",
            "meas_cyc_spread": f"{spread:.2f}",
            "ksamp_s_min": min(x[1] for x in rs),
            "fl_x_rt_min": f"{min(x[2] for x in rs):.1f}",
        })
    if worst > 0.01 + 1e-9:
        print(f"FATAL G4: worst cell-invariance spread {worst:.2f} > 0.01"); sys.exit(1)
    print(f"G4 PASS: worst cell-invariance spread {worst:.2f} cycles")

    with open(out_csv, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        wr.writeheader(); wr.writerows(out_rows)
    with open(out_tex, "w") as f:
        f.write(f"% {SENTINEL} -- campaign_results.csv MD5 {md5_of(args.csv)}; schedule MD5 {md5_of(args.sched)}\n")
        f.write("\\begin{tabular}{rrrrrr}\n\\hline\n")
        f.write("Width & Scheduled & Measured & Offset & ksamp/s & RT margin \\\\\n")
        f.write("(bits) & (cycles) & (cyc/sample) & (cycles) & (min, short-run) & (min, full-length) \\\\\n\\hline\n")
        for r in out_rows:
            f.write(f"{r['width']} & {r['sched_cyc']} & {r['meas_cyc_mean']} & "
                    f"$-${r['offset_cyc']} & {r['ksamp_s_min']} & {r['fl_x_rt_min']}$\\times$ \\\\\n")
        f.write("\\hline\n\\end{tabular}\n")
        f.write(f"% Scheduled = csynth SAMPLE_LOOP iteration latency (HARV-CSYNTH-REV1). Measured = board mean over six models;\n")
        f.write(f"% per-width model spread <= {worst:.2f}. Offset law: constant {off_const:.2f} cycles across all 102 builds.\n")
    print(f"wrote {out_csv}")
    print(f"wrote {out_tex}")
    print(f"csv MD5 {md5_of(out_csv)}  bytes {os.path.getsize(out_csv)}")
    print(f"tex MD5 {md5_of(out_tex)}  bytes {os.path.getsize(out_tex)}")
    print(f"script MD5 {md5_of(os.path.abspath(__file__))}  bytes {os.path.getsize(os.path.abspath(__file__))}")
    print(f"== {SENTINEL} COMPLETE ==")
    return 0

if __name__ == "__main__":
    sys.exit(main())
# SENTINEL-END: GTAB-REV3-2026-09-03
