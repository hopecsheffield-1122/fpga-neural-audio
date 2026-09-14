#!/usr/bin/env python3
# BUILD-MATRICES-REV2-20260910
# REV2: also writes one tidy 510-row file per metric (esr_510.csv, nmr_510.csv, odg_510.csv;
#       columns cell,source,width,value; sorted cell/source/width) so a reviewer sees the full
#       matrix in one file per metric. Matrix CSV values unchanged from REV1; only the banner sentinel differs.
# Builds the three per-source matrix CSVs (ESR, NMR, ODG: cell x width, one block per program
# source) from the ORIGINAL scorer CSVs. This is the INDEX/MATCH lookup that the workbook sheets
# 'ESR matrix (dB)', 'NMR matrix (dB)', 'ODG matrix' performed, written in Python so it is visible
# and reproducible. No workbook is read. Values are copied verbatim (as strings) from the source
# CSVs - no rounding, no arithmetic.
#
# Inputs (all originals, MD5 recorded in the output banner):
#   --esr-music   board_music_esr.csv      label board_<src>_<cell>_w<W>, esr_db          (408 rows)
#   --nmr-music   board_music_nmr.csv      label board_<src>_<cell>_w<W>, nmr_db          (408 rows)
#   --nmr-anchor  nmr_results.csv          label nam_w<W>_float_ref, nmr_db (rodent_max, csim FINAL85)
#   --nmr-nam     xcell_nmr_tranche1B.csv  cell,width,nmr_db,status (5 cells, status OK)
#   --esr-nam     board_nam_metrics.csv    label board_<cell>_nam_w<W>_float_ref, esr_db
#   --peaq        peaq_fleet_REV3.csv      cell,src,width,odg                              (510 rows)
# Outputs (fail-if-exists): <outdir>/esr_matrix.csv, nmr_matrix.csv, odg_matrix.csv
#                           <outdir>/esr_510.csv, nmr_510.csv, odg_510.csv (tidy, 510 rows each)
#   Layout per block:  "source: <src>" / "cell,w8..w24" / six cell rows / blank row.
#   ESR and NMR matrices: all 5 sources (music 4 + nam). ODG matrix: all 5 sources.
#   (The workbook's ESR/NMR sheets carried only the 4 music sources; nam lived in a separate sheet.
#    Consumers that want music-only select by source name; extra blocks are harmless to them.)
# Gates: every (cell, source, width) present exactly once per metric, 510 per metric; duplicate
#   rows must be value-identical (nmr_results.csv holds identical reruns); anything else is FATAL.
import argparse, csv, hashlib, os, re, sys

SENT = "BUILD-MATRICES-REV2-20260910"
CELLS = ["rodent_max", "rodent_mod", "gt_max", "gt_mod", "fl_max", "fl_mod"]
MUSIC = ["gtr2", "gtr4sg", "prvtgtr", "ytbass"]
SRCS = MUSIC + ["nam"]
W = list(range(8, 25))
CELL_RE = "(rodent_max|rodent_mod|gt_max|gt_mod|fl_max|fl_mod)"

def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest().upper()

def put(d, key, val, where):
    if key in d and d[key] != val:
        sys.exit(f"FATAL: conflicting duplicate for {key} in {where}: {d[key]} vs {val}")
    d[key] = val

def load_music(path, col, d):
    pat = re.compile(r"^board_(gtr2|gtr4sg|prvtgtr|ytbass)_" + CELL_RE + r"_w(\d+)$")
    n = 0
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            m = pat.match(r["label"])
            if m:
                put(d, (m.group(2), m.group(1), int(m.group(3))), r[col].strip(), path); n += 1
    return n

def load_esr_nam(path, d):
    pat = re.compile(r"^board_" + CELL_RE + r"_nam_w(\d+)_float_ref$")
    n = 0
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            m = pat.match(r["label"])
            if m:
                put(d, (m.group(1), "nam", int(m.group(2))), r["esr_db"].strip(), path); n += 1
    return n

def load_nmr_anchor(path, d):
    pat = re.compile(r"^nam_w(\d+)_float_ref$")
    n = 0
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            m = pat.match(r["label"])
            if m:
                put(d, ("rodent_max", "nam", int(m.group(1))), r["nmr_db"].strip(), path); n += 1
    return n

def load_nmr_nam(path, d):
    n = 0
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["status"] == "OK" and r["cell"] in CELLS:
                put(d, (r["cell"], "nam", int(r["width"])), r["nmr_db"].strip(), path); n += 1
    return n

def load_peaq(path, d):
    n = 0
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["cell"] in CELLS and r["src"] in SRCS:
                put(d, (r["cell"], r["src"], int(r["width"])), r["odg"].strip(), path); n += 1
    return n

def check_full(d, name):
    miss = [(c, s, w) for c in CELLS for s in SRCS for w in W if (c, s, w) not in d]
    if miss:
        sys.exit(f"FATAL: {name} incomplete, {len(miss)} missing, first {miss[:5]}")
    if len(d) != 510:
        sys.exit(f"FATAL: {name} has {len(d)} keys, expected 510")

def write_matrix(path, d, banner):
    if os.path.exists(path):
        sys.exit(f"FATAL: output exists (fail-if-exists): {path}")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([banner])
        w.writerow([])
        for s in SRCS:
            w.writerow([f"source: {s}"])
            w.writerow(["cell"] + [f"w{x}" for x in W])
            for c in CELLS:
                w.writerow([c] + [d[(c, s, x)] for x in W])
            w.writerow([])
    return md5(path)

def write_tidy(path, d):
    """One row per (cell, source, width), 510 rows, values verbatim; sorted for stable hashing."""
    if os.path.exists(path):
        sys.exit(f"FATAL: output exists (fail-if-exists): {path}")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cell", "source", "width", "value"])
        for c in CELLS:
            for s in SRCS:
                for x in W:
                    w.writerow([c, s, x, d[(c, s, x)]])
    return md5(path)

def main():
    ap = argparse.ArgumentParser()
    for k in ("esr-music", "nmr-music", "nmr-anchor", "nmr-nam", "esr-nam", "peaq"):
        ap.add_argument("--" + k, required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    print(SENT)
    print(f"script MD5 {md5(os.path.abspath(__file__))}")
    src = {}
    for k in ("esr_music", "nmr_music", "nmr_anchor", "nmr_nam", "esr_nam", "peaq"):
        p = getattr(a, k); src[k] = (os.path.basename(p), os.path.getsize(p), md5(p))
        print(f"  {k:10} {p}  {src[k][1]} B  MD5 {src[k][2]}")
    esr, nmr, odg = {}, {}, {}
    n1 = load_music(a.esr_music, "esr_db", esr); n2 = load_esr_nam(a.esr_nam, esr)
    n3 = load_music(a.nmr_music, "nmr_db", nmr); n4 = load_nmr_anchor(a.nmr_anchor, nmr); n5 = load_nmr_nam(a.nmr_nam, nmr)
    n6 = load_peaq(a.peaq, odg)
    print(f"rows accepted: esr music {n1} + nam {n2}; nmr music {n3} + anchor nam {n4} (dupes identical) + fleet nam {n5}; odg {n6}")
    check_full(esr, "ESR"); check_full(nmr, "NMR"); check_full(odg, "ODG")
    print("coverage gate PASS: 510/510 per metric, no conflicting duplicates")
    os.makedirs(a.outdir, exist_ok=True)
    prov = "; ".join(f"{v[0]} {v[2]}" for v in src.values())
    outs = [("esr_matrix.csv", esr, f"{SENT} ESR (dB) float-ref, cell x width per source, verbatim from {src['esr_music'][0]} {src['esr_music'][2]} + {src['esr_nam'][0]} {src['esr_nam'][2]}"),
            ("nmr_matrix.csv", nmr, f"{SENT} NMR (dB), cell x width per source, verbatim from {src['nmr_music'][0]} {src['nmr_music'][2]} + {src['nmr_anchor'][0]} {src['nmr_anchor'][2]} + {src['nmr_nam'][0]} {src['nmr_nam'][2]}"),
            ("odg_matrix.csv", odg, f"{SENT} PEAQ ODG, cell x width per source, verbatim from {src['peaq'][0]} {src['peaq'][2]}")]
    rec = [["sentinel", SENT], ["input", "bytes", "md5"]] + [[v[0], v[1], v[2]] for v in src.values()] + [["output", "bytes", "md5"]]
    for name, d, banner in outs:
        p = os.path.join(a.outdir, name); h = write_matrix(p, d, banner)
        rec.append([name, os.path.getsize(p), h]); print(f"wrote {p}  {os.path.getsize(p)} B  MD5 {h}")
    for name, d in (("esr_510.csv", esr), ("nmr_510.csv", nmr), ("odg_510.csv", odg)):
        p = os.path.join(a.outdir, name); h = write_tidy(p, d)
        rec.append([name, os.path.getsize(p), h]); print(f"wrote {p}  {os.path.getsize(p)} B  MD5 {h}")
    rp = os.path.join(a.outdir, "build_matrices_hash_record.csv")
    with open(rp, "w", newline="") as f: csv.writer(f).writerows(rec)
    print(f"wrote {rp}  MD5 {md5(rp)}")
    print(f"{SENT} done")

if __name__ == "__main__":
    main()
