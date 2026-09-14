#!/usr/bin/env python3
# gap_grid_REV2.py — SENTINEL: GAPGRID-REV2
# REV2 (2026-09-10): --workbook replaced by --matrix-dir (build_matrices_REV1 CSVs derived from the
# original scorer outputs); nam ESR read from the esr_matrix nam block (itself verbatim from
# board_nam_metrics.csv) or from --nam-esr-csv if given; --bank/--out-xlsx removed. Arithmetic
# unchanged from REV1. Acceptance gate: --out-csv identical to the 8/29 record check1_gap_grid.csv
# (CA72ADD4AD6884DB792BF7E78AA82CA5) except the sentinel row.
# Computes the displacement grid: mean gap (w_odg - w_esr) over
# ESR bars {-20,-25,-30,-35,-40} dB x ODG bars {-0.1,-0.2,-0.3,-0.5,-1.0},
# plus the per-model decomposition of every grid cell.
#
# Aggregation rule (matches CHECK1-GAP under the mean rule, verified 12/12
# against the plotted five-source mean curves on 2026-08-29):
#   stage 1: per model, mean each metric over the five program sources
#   stage 2: selected width = smallest w in 8..24 where the mean meets the bar
#            (ESR: mean <= bar; ODG: mean >= bar)
#   stage 3: gap = w_odg - w_esr per model; grid cell = mean of six gaps
#
# Inputs (primary):
#   --matrix-dir  folder with esr_matrix.csv, odg_matrix.csv (5 sources each)
#   --nam-esr-csv  board_nam_metrics CSV; ONLY *_float_ref rows are used
#               (ESR vs float32 model output). Plain rows (vs pedal target)
#               are excluded.
#   If --nam-esr-csv is omitted, nam ESR comes from the esr_matrix.csv nam block.
#
# Outputs:
#   --out-csv    grid + per-model decomposition, fail-if-exists
# Sanity gates (hard failures):
#   - 17 widths per model per metric per source
#   - the (-30, -0.2) cell must reproduce the banked Check1 result:
#     w_esr {17,16,15,14,16,16}, w_odg {21,20,19,18,21,20}, mean gap 4.2

import argparse, csv, hashlib, os, sys
import re
import numpy as np

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


CELLS = ["rodent_max", "rodent_mod", "gt_max", "gt_mod", "fl_max", "fl_mod"]
WIDTHS = list(range(8, 25))
SOURCES = ["gtr2", "gtr4sg", "prvtgtr", "ytbass", "nam"]
EBARS = [-20.0, -25.0, -30.0, -35.0, -40.0]
OBARS = [-0.1, -0.2, -0.3, -0.5, -1.0]
CHECK1_WESR = {"rodent_max": 17, "rodent_mod": 16, "gt_max": 15,
               "gt_mod": 14, "fl_max": 16, "fl_mod": 16}
CHECK1_WODG = {"rodent_max": 21, "rodent_mod": 20, "gt_max": 19,
               "gt_mod": 18, "fl_max": 21, "fl_mod": 20}


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def parse_source_blocks(path):
    out, src, widths = {}, None, None
    for row in _csv_rows(path):
        c0 = row[0]
        if isinstance(c0, str) and c0.startswith("source:"):
            src = c0.split(":", 1)[1].strip()
        elif c0 == "cell":
            widths = [int(str(w)[1:]) for w in row[1:] if w]
        elif isinstance(c0, str) and c0 in CELLS and src:
            vals = [float(v) for v in row[1:] if v is not None][:len(widths)]
            if len(vals) != len(widths):
                sys.exit(f"FATAL: short row {src}/{c0} in {path}")
            out.setdefault(src, {})[c0] = dict(zip(widths, vals))
    return out


def load_nam_esr_from_csv(path):
    out = {c: {} for c in CELLS}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            lab = r["label"]
            if not lab.endswith("_float_ref"):
                continue
            core = lab[: -len("_float_ref")].replace("board_", "")
            cell, wtag = core.rsplit("_nam_w", 1)
            out[cell][int(wtag)] = float(r["esr_db"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix-dir", required=True, help="folder with esr_matrix.csv / odg_matrix.csv")
    ap.add_argument("--nam-esr-csv", default=None)
    ap.add_argument("--out-csv", required=True)
    args = ap.parse_args()

    if os.path.exists(args.out_csv):
        sys.exit(f"FATAL: output exists: {args.out_csv} (fail-if-exists)")

    ep = os.path.join(args.matrix_dir, "esr_matrix.csv"); op = os.path.join(args.matrix_dir, "odg_matrix.csv")
    print(f"esr_matrix.csv MD5: {md5(ep)}"); print(f"odg_matrix.csv MD5: {md5(op)}")
    esr = parse_source_blocks(ep)
    odg = parse_source_blocks(op)

    if args.nam_esr_csv:
        print(f"nam ESR csv MD5: {md5(args.nam_esr_csv)}")
        esr["nam"] = load_nam_esr_from_csv(args.nam_esr_csv)
        nam_esr_src = os.path.basename(args.nam_esr_csv)
    elif "nam" in esr:
        nam_esr_src = "esr_matrix.csv nam block (verbatim board_nam_metrics.csv)"
    else:
        sys.exit("FATAL: no nam ESR source (--nam-esr-csv absent and no nam block in esr_matrix.csv)")
    print(f"nam ESR source: {nam_esr_src}")

    for c in CELLS:
        for s in SOURCES:
            assert len(esr[s][c]) == 17, f"ESR incomplete: {c}/{s}"
            assert len(odg[s][c]) == 17, f"ODG incomplete: {c}/{s}"

    mean_esr = {c: {w: float(np.mean([esr[s][c][w] for s in SOURCES]))
                    for w in WIDTHS} for c in CELLS}
    mean_odg = {c: {w: float(np.mean([odg[s][c][w] for s in SOURCES]))
                    for w in WIDTHS} for c in CELLS}

    def sel(mean_curve, pred):
        return next((w for w in WIDTHS if pred(mean_curve[w])), None)

    # sanity gate: reproduce banked Check1 at (-30, -0.2)
    for c in CELLS:
        we = sel(mean_esr[c], lambda v: v <= -30.0)
        wo = sel(mean_odg[c], lambda v: v >= -0.2)
        if we != CHECK1_WESR[c] or wo != CHECK1_WODG[c]:
            sys.exit(f"FATAL: Check1 reproduction failed for {c}: "
                     f"w_esr {we} (expect {CHECK1_WESR[c]}), "
                     f"w_odg {wo} (expect {CHECK1_WODG[c]})")
    print("sanity gate: Check1 (-30 dB, -0.2) reproduced 12/12 OK")

    rows = [["sentinel", "GAPGRID-REV2"],
            ["rule", "per model: five-source mean curve; smallest w meeting "
                     "bar; gap = w_odg - w_esr; grid cell = mean of 6 gaps"],
            ["esr_bar_db", "odg_bar", "mean_gap"] + [f"gap_{c}" for c in CELLS]
            + [f"w_esr_{c}" for c in CELLS] + [f"w_odg_{c}" for c in CELLS]]
    grid_disp = []
    for eb in EBARS:
        line = []
        for ob in OBARS:
            wes = {c: sel(mean_esr[c], lambda v: v <= eb) for c in CELLS}
            wos = {c: sel(mean_odg[c], lambda v: v >= ob) for c in CELLS}
            gaps = {c: (wos[c] - wes[c]) if wes[c] and wos[c] else None
                    for c in CELLS}
            valid = [g for g in gaps.values() if g is not None]
            mg = float(np.mean(valid))
            rows.append([eb, ob, round(mg, 2)]
                        + [gaps[c] for c in CELLS]
                        + [wes[c] for c in CELLS] + [wos[c] for c in CELLS])
            line.append(f"{mg:+.1f}")
        grid_disp.append((eb, line))

    with open(args.out_csv, "x", newline="") as f:
        csv.writer(f).writerows(rows)
    print(f"wrote {args.out_csv}  (MD5 {md5(args.out_csv)})")

    print("\nmean-gap grid (rows = ESR bar dB, cols = ODG bar):")
    print("        " + "".join(f"{o:>8.1f}" for o in OBARS))
    for eb, line in grid_disp:
        print(f"{eb:>8.0f}" + "".join(f"{x:>8s}" for x in line))


if __name__ == "__main__":
    main()
