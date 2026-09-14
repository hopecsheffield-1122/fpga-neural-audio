#!/usr/bin/env python3
# SENTINEL: HARV-PLACED-REV2-2026-09-13
# REV2: flat repo layout (reports/impl + reports/impl_nondeployed, build name in the file name), repo-relative defaults,
#       _dsp_best recognised as its own variant. Parsing, deployed-arm rule and the Table 2 self-check unchanged from REV1.
# harvest_placed_util_REV1.py -- walks the bitgen reports tree, parses every
# *utilization_placed.rpt (Vivado post-place, full overlay = kernel + AXI DMA + PS7),
# and emits:
#   1) <outdir>\placed_util_per_build_REV1.csv   -- one row per report (cell, width, variant, LUT, FF, BRAM, DSP, path, md5)
#   2) <outdir>\resources_placed_by_width_REV1.csv -- per width, max over the six models, for the DEFAULT-flow builds
#      and for the DEPLOYED set (default unless a remedied _dsp/_best build exists for that cell,width)
# Self-check: per-width max LUT/BRAM/DSP compared against Table 2 of the 2026-09-09 draft for
# W = 8,12,16,20,22,24. Mismatches are printed, never silently fixed.
#
# Usage (from the repo root):
#   python scripts/harvest_placed_util_REV2.py --outdir <somewhere-empty>
#   [--reports reports/impl reports/impl_nondeployed]   (default: both, so the deployed-arm rule can be exercised)
# Fail-if-exists on both outputs. Read-only on the reports tree. Output file names keep the REV1 suffix so the
# regenerated CSVs can be diffed against results/hardware/*_REV1.csv directly.

import argparse, csv, hashlib, os, re, sys
from collections import defaultdict

SENTINEL = "HARV-PLACED-REV2-2026-09-13"
CELLS = ["rodent_max", "rodent_mod", "gt_max", "gt_mod", "fl_max", "fl_mod"]
WIDTHS = list(range(8, 25))
TAG_RE = re.compile(r"gru_L20_(rodent_max|rodent_mod|gt_max|gt_mod|fl_max|fl_mod)_w(\d+)(?:_(dsp_best|dsp|best\w*))?", re.I)

# Table 2, paper_spconf_20260909 (BRAM, LUT max, DSP max) -- the self-check targets
TABLE2 = {8: (4, 17092, 72), 12: (5, 16793, 69), 16: (5, 18568, 76),
          20: (6, 24509, 74), 22: (6, 20042, 135), 24: (6, 20942, 133)}

ROW_RE = {
    "LUT":  re.compile(r"^\|\s*Slice LUTs\s*\|\s*(\d+)\s*\|"),
    "FF":   re.compile(r"^\|\s*Slice Registers\s*\|\s*(\d+)\s*\|"),
    "BRAM": re.compile(r"^\|\s*Block RAM Tile\s*\|\s*(\d+(?:\.\d+)?)\s*\|"),
    "DSP":  re.compile(r"^\|\s*DSPs\s*\|\s*(\d+)\s*\|"),
}

def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()

def parse_report(path):
    vals = {}
    with open(path, "r", errors="replace") as f:
        for line in f:
            for k, rx in ROW_RE.items():
                if k in vals: continue
                m = rx.match(line)
                if m:
                    v = float(m.group(1))
                    vals[k] = int(v) if v.is_integer() else v
    missing = [k for k in ROW_RE if k not in vals]
    return vals, missing

def main():
    ap = argparse.ArgumentParser(description=f"Placed utilization harvester ({SENTINEL})")
    ap.add_argument("--reports", nargs="+", default=[os.path.join("reports", "impl"), os.path.join("reports", "impl_nondeployed")],
                    help="one or more report folders (flat, build name in file name)")
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()
    print(f"== {SENTINEL} ==")

    out_build = os.path.join(args.outdir, "placed_util_per_build_REV1.csv")
    out_width = os.path.join(args.outdir, "resources_placed_by_width_REV1.csv")
    for p in (out_build, out_width):
        if os.path.exists(p):
            print(f"FATAL: output exists (fail-if-exists): {p}"); sys.exit(1)
    for rp in args.reports:
        if not os.path.isdir(rp):
            print(f"FATAL: reports folder not found: {rp}"); sys.exit(1)

    rows = []
    untagged = []
    for rp in args.reports:
      for dirpath, _, files in os.walk(rp):
        for fn in files:
            if not fn.lower().endswith("utilization_placed.rpt"): continue
            full = os.path.join(dirpath, fn)
            m = TAG_RE.search(full)
            if not m:
                untagged.append(full); continue
            cell, width, variant = m.group(1).lower(), int(m.group(2)), (m.group(3) or "default").lower()
            if variant == "dsp_best": variant = "best"
            vals, missing = parse_report(full)
            if missing:
                print(f"WARN: {full} missing rows {missing} -- skipped"); continue
            rows.append({"cell": cell, "width": width, "variant": variant,
                         "LUT": vals["LUT"], "FF": vals["FF"], "BRAM": vals["BRAM"], "DSP": vals["DSP"],
                         "path": full, "md5": md5_of(full)})
    print(f"reports parsed: {len(rows)}   untagged (ignored): {len(untagged)}")
    for u in untagged[:10]: print(f"  untagged: {u}")
    if not rows:
        print("FATAL: no tagged reports found -- check --reports root and folder naming (expected gru_L20_<cell>_w<W>)"); sys.exit(1)

    # coverage of the default arm
    have = {(r["cell"], r["width"]) for r in rows if r["variant"] == "default"}
    need = {(c, w) for c in CELLS for w in WIDTHS}
    miss = sorted(need - have)
    print(f"default-arm coverage: {len(have)}/102" + (f"  MISSING: {miss}" if miss else ""))
    remedied = sorted({(r["cell"], r["width"], r["variant"]) for r in rows if r["variant"] != "default"})
    print(f"remedied builds found: {len(remedied)}")
    for t in remedied: print(f"  {t}")

    rows.sort(key=lambda r: (r["width"], CELLS.index(r["cell"]), r["variant"]))
    with open(out_build, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["cell", "width", "variant", "LUT", "FF", "BRAM", "DSP", "path", "md5"])
        wr.writeheader(); wr.writerows(rows)

    # deployed set: default unless a remedied build exists for (cell,width); if both dsp and best exist, best wins
    by_key = defaultdict(dict)
    for r in rows: by_key[(r["cell"], r["width"])][r["variant"]] = r
    def deployed(k):
        d = by_key[k]
        for v in sorted(d):            # 'best*' sorts before 'default' before 'dsp'
            if v.startswith("best"): return d[v]
        if "dsp" in d: return d["dsp"]
        return d.get("default")

    out_rows = []
    for w in WIDTHS:
        dflt = [by_key[(c, w)].get("default") for c in CELLS]
        dflt = [r for r in dflt if r]
        depl = [deployed((c, w)) for c in CELLS]
        depl = [r for r in depl if r]
        def mx(rs, k): return max(r[k] for r in rs) if rs else ""
        def cell_of_max(rs, k): return max(rs, key=lambda r: r[k])["cell"] if rs else ""
        out_rows.append({
            "width": w, "n_default": len(dflt), "n_deployed": len(depl),
            "LUT_max_default": mx(dflt, "LUT"), "FF_max_default": mx(dflt, "FF"),
            "BRAM_max_default": mx(dflt, "BRAM"), "DSP_max_default": mx(dflt, "DSP"),
            "LUT_max_deployed": mx(depl, "LUT"), "FF_max_deployed": mx(depl, "FF"),
            "BRAM_max_deployed": mx(depl, "BRAM"), "DSP_max_deployed": mx(depl, "DSP"),
            "FF_max_deployed_cell": cell_of_max(depl, "FF"),
            "LUT_max_deployed_cell": cell_of_max(depl, "LUT"),
        })
    with open(out_width, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        wr.writeheader(); wr.writerows(out_rows)

    # self-check vs Table 2
    print("\nSELF-CHECK vs Table 2 (BRAM, LUT, DSP) -- which arm reproduces the published digits:")
    print(f"{'W':>3} {'Table2':>18} {'default':>18} {'deployed':>18}  verdict")
    for w, (b, l, d) in TABLE2.items():
        r = next(x for x in out_rows if x["width"] == w)
        td = (r["BRAM_max_default"], r["LUT_max_default"], r["DSP_max_default"])
        tp = (r["BRAM_max_deployed"], r["LUT_max_deployed"], r["DSP_max_deployed"])
        v = []
        if td == (b, l, d): v.append("default=T2")
        if tp == (b, l, d): v.append("deployed=T2")
        if not v: v.append("NO MATCH")
        print(f"{w:>3} {str((b,l,d)):>18} {str(td):>18} {str(tp):>18}  {' '.join(v)}")

    print("\nFF max per width (deployed set):")
    for r in out_rows:
        print(f"  W={r['width']:>2}  FF={r['FF_max_deployed']}  ({r['FF_max_deployed_cell']})")

    print(f"\nwrote {out_build}  bytes {os.path.getsize(out_build)}  MD5 {md5_of(out_build)}")
    print(f"wrote {out_width}  bytes {os.path.getsize(out_width)}  MD5 {md5_of(out_width)}")
    print(f"script MD5 {md5_of(os.path.abspath(__file__))}  bytes {os.path.getsize(os.path.abspath(__file__))}")
    print(f"== {SENTINEL} COMPLETE ==")

if __name__ == "__main__":
    sys.exit(main())
# SENTINEL-END: HARV-PLACED-REV2-2026-09-13
