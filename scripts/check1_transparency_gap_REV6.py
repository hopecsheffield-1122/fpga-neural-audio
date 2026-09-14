#!/usr/bin/env python3
# =============================================================================
# CHECK1-GAP-REV6 : ESR-transparent vs perceptual-transparent width gap
# -----------------------------------------------------------------------------
# Input : matrix folder written by build_matrices_REV1.py from the original scorer CSVs
#           - nmr_matrix.csv   music sources, mean over 4 (nam block present, not used here)
#           - esr_matrix.csv   music sources, mean over 4 (nam block present, not used here)
#           - odg_matrix.csv   all 5 sources, mean over 5
#         Same block layout as the former workbook sheets. No workbook is read.
# Output: prints
#           1) per-cell transparency widths + gap at primary thresholds
#           2) threshold sensitivity sweep (gap under every threshold pair)
#           3) threshold-free inversion table (NMR hump vs ESR monotone, w12->15)
# Writes check1_output.txt + check1_transparency_gap.csv into --out-dir.
# Inputs are never written.
#
# REV6 (2026-09-10): inputs and outputs are explicit arguments (--matrix-dir,
#   --out-dir); nothing is located relative to the script file. Zero analysis
#   changes. Acceptance gate: check1_transparency_gap.csv byte-identical to the
#   REV4/REV5 record (A85451A4DE10AF1876B7BE4397706F24).
#
# REV5 (2026-09-10): input moved from the 8/15 workbook to build_matrices_REV1 CSVs
#   derived from the original scorer outputs. Zero analysis changes.
#   Acceptance gate: check1_transparency_gap.csv byte-identical to REV4 output on
#   the 8/15 workbook (A85451A4DE10AF1876B7BE4397706F24) - verified 2026-09-10.
#
# REV3 (external review 2026-08-16, pre-rerun):
#   - strict preflight validation: sheets/sources/cells/widths complete,
#     numeric, finite - partial means now FATAL instead of silent
#   - matched-source secondary columns (ODG restricted to the 4 music
#     sources, same population as ESR) - primary definition UNCHANGED
#   - ITU wording corrected (-0.2 is operational, not a BS.1387 bound)
#   - read_only=True (implementation now matches protocol language)
#   Acceptance gate: primary table must reproduce REV1's +4.2 digits.
# REV4 (2026-08-16, post-REV3-acceptance): adds file output ONLY -
#   full console duplicated to check1_output.txt (UTF-8, Python-written;
#   never PowerShell redirect = UTF-16 trap) and the primary table to
#   check1_transparency_gap.csv. Zero analysis changes; REV3 digits are
#   the acceptance reference.
#
# PRE-REGISTERED DEFINITIONS (fixed before reading results):
#   perceptual-transparent width = smallest w such that mean ODG >= T_ODG
#                                  for ALL widths >= w   (stays transparent)
#   energy-transparent width     = smallest w such that mean ESR <= T_ESR
#                                  for ALL widths >= w
#   gap = perceptual - energy    (positive => ESR is optimistic:
#                                 it certifies transparency at a narrower
#                                 width than the perceptual metric accepts)
#   PRIMARY thresholds: T_ODG = -0.2 (pre-registered near-transparent
#                       operating threshold; BS.1387 defines ODG 0 as
#                       imperceptible - -0.2 is OUR operational bar, not ITU's)
#                       T_ESR = -30 dB
#   Sensitivity sweep:  T_ODG in {-0.2, -0.5, -1.0}
#                       T_ESR in {-25, -30, -35, -40} dB
#
# Run (standard library only):
#   python check1_transparency_gap_REV6.py --matrix-dir <folder with the three matrix CSVs> --out-dir <folder>
# =============================================================================

import argparse
import csv
import math
import os
import re
import sys
import statistics as st

class _Tee:
    def __init__(self, path):
        self._f = open(path, "w", encoding="utf-8")
        self._s = sys.stdout
    def write(self, x):
        self._s.write(x)
        self._f.write(x)
    def flush(self):
        self._s.flush()
        self._f.flush()

def _num(s):
    """CSV cell -> int / float / str / None (the types the former workbook sheets held)."""
    if s is None or s == "":
        return None
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    try:
        return float(s)
    except ValueError:
        return s

def _csv_rows(path):
    """All rows of a CSV as tuples of typed cells, padded to the widest row (empty rows kept)."""
    with open(path, newline="", encoding="utf-8") as f:
        raw = list(csv.reader(f))
    width = max((len(r) for r in raw), default=0)
    return [tuple(_num(v) for v in r) + (None,) * (width - len(r)) for r in raw]

# --- configuration ------------------------------------------------------------
_ap = argparse.ArgumentParser(description="CHECK1-GAP-REV6")
_ap.add_argument("--matrix-dir", required=True, help="folder with nmr_matrix.csv, esr_matrix.csv, odg_matrix.csv")
_ap.add_argument("--out-dir", required=True, help="folder for check1_output.txt and check1_transparency_gap.csv (created if absent)")
_args = _ap.parse_args()
MATRIX_DIR = _args.matrix_dir
OUT_DIR = _args.out_dir
MATRIX_FILES = {"NMR matrix (dB)": "nmr_matrix.csv", "ESR matrix (dB)": "esr_matrix.csv", "ODG matrix": "odg_matrix.csv"}

WIDTHS = list(range(8, 25))
CELLS = ["rodent_max", "rodent_mod", "gt_max", "gt_mod", "fl_max", "fl_mod"]
MUSIC = ("gtr2", "gtr4sg", "prvtgtr", "ytbass")

T_ODG_PRIMARY = -0.2
T_ESR_PRIMARY = -30.0
T_ODG_SWEEP = (-0.2, -0.5, -1.0)
T_ESR_SWEEP = (-25.0, -30.0, -35.0, -40.0)

# --- matrix CSV parsing (same block grammar the workbook sheets had) ------------
def parse_matrix(folder, sheet):
    """Parse a 'source: X' block-structured matrix CSV -> {src:{cell:{w:val}}}."""
    data, cur = {}, None
    for row in _csv_rows(os.path.join(folder, MATRIX_FILES[sheet])):
        if not row or row[0] is None:
            continue
        c0 = str(row[0])
        m = re.match(r"source:\s*(\S+)", c0)
        if m:
            cur = m.group(1)
            data[cur] = {}
            continue
        if c0 in CELLS and cur is not None:
            vals = row[1:1 + len(WIDTHS)]
            data[cur][c0] = {
                w: (v if isinstance(v, (int, float)) else None)
                for w, v in zip(WIDTHS, vals)
            }
    return data

def cell_mean_curve(data, cell, srcs):
    """Mean over sources at each width -> {w: mean or None}."""
    out = {}
    for w in WIDTHS:
        vs = [data[s][cell][w] for s in srcs
              if s in data and cell in data[s] and data[s][cell].get(w) is not None]
        out[w] = st.mean(vs) if vs else None
    return out

# --- preflight validation (REV3) ---
def validate(NMR, ESR, ODG):
    problems = []
    exp_odg = set(MUSIC) | {"nam"}
    for name, data, req in (("NMR matrix (dB)", NMR, set(MUSIC)),
                            ("ESR matrix (dB)", ESR, set(MUSIC)),
                            ("ODG matrix", ODG, exp_odg)):
        missing = req - set(data)
        if missing:
            problems.append(f"{name}: missing sources {sorted(missing)}")
        if name == "ODG matrix":
            extra = set(data) - exp_odg
            if extra:
                problems.append(f"{name}: unexpected sources {sorted(extra)}")
        for src in sorted(req & set(data)):
            for cell in CELLS:
                if cell not in data[src]:
                    problems.append(f"{name}/{src}: missing cell {cell}")
                    continue
                for w in WIDTHS:
                    v = data[src][cell].get(w)
                    if v is None or not isinstance(v, (int, float))                             or not math.isfinite(v):
                        problems.append(
                            f"{name}/{src}/{cell}/w{w}: missing or nonfinite ({v!r})")
    if problems:
        print("FATAL: matrix validation failed "
              f"({len(problems)} problem(s)):")
        for p in problems[:40]:
            print("  -", p)
        sys.exit(1)
    print("preflight validation PASS: all sheets/sources/cells/widths "
          "complete, numeric, finite")

# --- transparency-width finders --------------------------------------------------
def first_stays_below(curve, thr):
    """Smallest w such that curve[w'] <= thr for ALL w' >= w. None if never."""
    for i, w in enumerate(WIDTHS):
        if all(curve[w2] is not None and curve[w2] <= thr for w2 in WIDTHS[i:]):
            return w
    return None

def first_stays_above(curve, thr):
    """Smallest w such that curve[w'] >= thr for ALL w' >= w. None if never."""
    for i, w in enumerate(WIDTHS):
        if all(curve[w2] is not None and curve[w2] >= thr for w2 in WIDTHS[i:]):
            return w
    return None

# --- main ------------------------------------------------------------------------
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    sys.stdout = _Tee(os.path.join(OUT_DIR, "check1_output.txt"))
    csv_rows = []
    try:
        NMR = parse_matrix(MATRIX_DIR, "NMR matrix (dB)")
        ESR = parse_matrix(MATRIX_DIR, "ESR matrix (dB)")
        ODG = parse_matrix(MATRIX_DIR, "ODG matrix")
    except FileNotFoundError as e:
        sys.exit(f"FATAL: matrix CSV not found: {e}")
    validate(NMR, ESR, ODG)
    odg_srcs = tuple(ODG.keys())          # all 5 (nam + 4 music)

    # ---- 1) primary table --------------------------------------------------------
    print("=" * 78)
    print("CHECK 1 - transparency-width gap  "
          f"(primary: ODG>={T_ODG_PRIMARY}, ESR<={T_ESR_PRIMARY:.0f} dB)")
    print("=" * 78)
    print(f"{'cell':11} {'w_ESR':>6} {'w_ODG':>6} {'w_NMR0':>7} {'gap':>5} "
          f"{'w_ODGm':>7} {'gap_m':>6}   (m = ODG on 4 music sources, "
          f"matched to ESR population)")
    gaps, gaps_m = [], []
    per_cell = {}
    for cell in CELLS:
        esr_c = cell_mean_curve(ESR, cell, MUSIC)
        odg_c = cell_mean_curve(ODG, cell, odg_srcs)
        odg_m = cell_mean_curve(ODG, cell, MUSIC)
        nmr_c = cell_mean_curve(NMR, cell, MUSIC)
        wE = first_stays_below(esr_c, T_ESR_PRIMARY)
        wO = first_stays_above(odg_c, T_ODG_PRIMARY)
        wOm = first_stays_above(odg_m, T_ODG_PRIMARY)
        wN = first_stays_below(nmr_c, 0.0)
        gap = (wO - wE) if (wO is not None and wE is not None) else None
        gap_m = (wOm - wE) if (wOm is not None and wE is not None) else None
        per_cell[cell] = (esr_c, odg_c, nmr_c)
        if gap is not None:
            gaps.append(gap)
        if gap_m is not None:
            gaps_m.append(gap_m)
        csv_rows.append([cell, wE, wO, wN, gap, wOm, gap_m])
        print(f"{cell:11} {str(wE):>6} {str(wO):>6} {str(wN):>7} "
              f"{(f'{gap:+d}') if gap is not None else 'n/a':>5} "
              f"{str(wOm):>7} {(f'{gap_m:+d}') if gap_m is not None else 'n/a':>6}")
    if gaps:
        print(f"\n  PRIMARY  mean gap {st.mean(gaps):+.1f} bits   "
              f"range {min(gaps):+d}..{max(gaps):+d}   "
              f"direction-consistent: {all(g > 0 for g in gaps)}")
    if gaps_m:
        print(f"  MATCHED  mean gap {st.mean(gaps_m):+.1f} bits   "
              f"range {min(gaps_m):+d}..{max(gaps_m):+d}   "
              f"direction-consistent: {all(g > 0 for g in gaps_m)}   "
              f"(secondary; closes source-population objection if ~= primary)")

    # ---- 2) threshold sensitivity sweep ------------------------------------------
    print()
    print("=" * 78)
    print("Sensitivity sweep - mean gap (bits) over 6 cells, per threshold pair")
    print("(rows: T_ODG; cols: T_ESR)  n/a = a cell never reaches a threshold")
    print("=" * 78)
    header = f"{'':>8}" + "".join(f"{f'ESR<={int(t)}':>10}" for t in T_ESR_SWEEP)
    print(header)
    for to in T_ODG_SWEEP:
        rowtxt = f"ODG>={to:>4}"
        for te in T_ESR_SWEEP:
            g = []
            ok = True
            for cell in CELLS:
                esr_c, odg_c, _ = per_cell[cell]
                wE = first_stays_below(esr_c, te)
                wO = first_stays_above(odg_c, to)
                if wE is None or wO is None:
                    ok = False
                    break
                g.append(wO - wE)
            rowtxt += f"{(f'{st.mean(g):+.1f}' if ok else 'n/a'):>10}"
        print(rowtxt)

    # ---- 3) threshold-free inversion (w12 -> w13..15) ------------------------------
    print()
    print("=" * 78)
    print("Threshold-free inversion, w12 vs max(w13..w15), music-mean")
    print("hump>0 with ESR monotone  =>  metrics move in opposite directions")
    print("=" * 78)
    print(f"{'cell':11} {'NMR w12':>8} {'NMR max13-15':>13} {'hump dB':>8} "
          f"{'ESR mono 12-16?':>16}")
    for cell in CELLS:
        esr_c, _, nmr_c = per_cell[cell]
        n12 = nmr_c[12]
        nmax = max(nmr_c[w] for w in (13, 14, 15))
        hump = nmax - n12
        esr_mono = all(esr_c[w + 1] <= esr_c[w] + 1e-6 for w in range(12, 16))
        print(f"{cell:11} {n12:8.2f} {nmax:13.2f} {hump:+8.2f} {str(esr_mono):>16}")

    with open(os.path.join(OUT_DIR, "check1_transparency_gap.csv"),
              "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cell", "w_esr", "w_odg", "w_nmr0", "gap",
                    "w_odg_music", "gap_matched"])
        w.writerows(csv_rows)
    print("\nwrote check1_output.txt + check1_transparency_gap.csv")
    print("\nSENTINEL: CHECK1-GAP-REV6 complete")

if __name__ == "__main__":
    main()
