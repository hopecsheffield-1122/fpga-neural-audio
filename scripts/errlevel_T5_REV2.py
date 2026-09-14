#!/usr/bin/env python3
# SENTINEL: ERRLEVEL-T5-REV2-2026-09-04
# REV2 (supersedes REV1 after one field run; PRE-REGISTRATION UNCHANGED; instrument hardening after
# external review): (1) ref_len/test_len recorded BEFORE truncation and a length mismatch is FATAL;
# (2) non-finite samples or non-finite rho/beta/ESR are FATAL (FAIL_NONFINITE); (3) clauses C1/C2 are
# evaluated on full-precision rho, rounding only at CSV write; (4) zero-variance frame levels are
# FAIL_DEGENERATE, not (0,0); (5) expected pairs-file MD5s and row counts are banked below and checked;
# (6) header wording: rho_L -> 0 means little LINEAR dependence of error level on reference level
# (consistent with an additive-noise-like regime), not independence; (7) documented: error power is
# floored at 1e-30 (-300 dB) before the log; source-mean rho is the equal-weight arithmetic mean of the
# five per-source rho values (not a pooled-frame correlation); (8) C1 prints an overall HIT/MISS.
# REV1 field run (35A3CE3AE75FA572DFF4E2010324D10F) is kept, annotated; its digits are unaffected by
# (1)-(5) (0 truncations, 0 non-finite, 0 degenerate rows, clause margins >= 0.14).
# Diagnostic exhibit (Tier 2). Digits never comparable to certified NMR/ESR/ODG rows.
#
# T5 - frame-level error-level vs reference-level dependence, on the SAME 510 pairs as ERRSPEC
# (pairs_music340.csv + pairs_anchor85.csv + pairs_nam85.csv; columns cell,src,width,ref,test).
#
# Per (cell, src, W):
#   e[n] = y_W[n] - y_f32[n], n >= 1024 (washout, same as ERRSPEC / IV-D scoring)
#   frames of L=2048 samples, hop 1024 (50% overlap), no window
#   P_e[i] = mean(e^2) over frame i ; P_r[i] = mean(y_f32^2) over frame i
#   frames with P_r < 1e-12 (below -120 dB) are dropped (silence; log-domain undefined)
#   rho_L  = Pearson correlation of 10log10(P_e) vs 10log10(P_r) across frames
#   beta   = least-squares slope of 10log10(P_e) on 10log10(P_r)  [dB/dB]
#   error power is floored at 1e-30 (-300 dB) before the log (zero error would give -inf)
# Reading: rho_L -> 1, beta -> 1 : error level tracks signal level (signal-dependent, any path)
#          rho_L -> 0            : little linear dependence of error level on reference level
#                                  (consistent with an additive-noise-like regime; not independence)
#          rho_L < 0             : error level higher in frames where the reference is quieter
# Source-mean rho_L per (cell, W) = equal-weight arithmetic mean over the five per-source rho_L values.
#
# PRE-REGISTERED CLAUSES (banked 2026-09-04 BEFORE any rho_L digit was read):
#   T5-C1  hump cells (rodent_max, rodent_mod, fl_max, fl_mod): source-mean rho_L(w8) - rho_L(w16) >= 0.30
#   T5-C2  regime B (w15-w21): source-mean rho_L < 0.30 at every W in B, in >= 4/6 cells
#   T5-C3  descriptive: gt_max, gt_mod rho_L logged at every width; no clause
#   Misses logged as findings. No clause is rerun to flip. Adjudicate only after all 510 rows land.
#
# Parser: --pairs uses action="extend" (repeated flags and space-separated lists accumulate);
# per-file loaded count printed; a pairs file contributing zero rows is FATAL (ERRSPEC REV2 lesson).
# Coverage gate: exactly the 510 grid or no CSV is written. Fail-if-exists on the output.
#
# Usage (Elle):
#   python3 errlevel_T5_REV1.py --pairs A.csv --pairs B.csv --pairs C.csv --out T5.csv [--workers 8]
import argparse, csv, hashlib, os, sys
import numpy as np
from concurrent.futures import ProcessPoolExecutor

SENTINEL = "ERRLEVEL-T5-REV2-2026-09-04"
# pairs files of record (same 510 pairs as ERRSPEC-T1T3-REV4): basename -> (MD5, rows)
PAIRS_OF_RECORD = {"pairs_music340.csv": ("D2ECBAE93BB5884FD90BC5AD0DD2309D", 340),
                   "pairs_anchor85.csv": ("8B9A4FCF7FEBDFAF890AA908FA65B37E", 85),
                   "pairs_nam85.csv":    ("A2619016991178565E0DEDA8FAE1D73D", 85)}
CELLS = ["rodent_max", "rodent_mod", "gt_max", "gt_mod", "fl_max", "fl_mod"]
SRCS = ["nam", "gtr2", "gtr4sg", "prvtgtr", "ytbass"]
W = list(range(8, 25))
WASHOUT, L, HOP, PFLOOR = 1024, 2048, 1024, 1e-12
HUMP = ["rodent_max", "rodent_mod", "fl_max", "fl_mod"]
REGB = list(range(15, 22))

def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest().upper()

def load_pairs(paths):
    rows = []
    for p in paths:
        n = 0
        for r in csv.DictReader(open(p)):
            rows.append({"cell": r["cell"], "src": r["src"], "width": int(r["width"]),
                         "ref": r["ref"], "test": r["test"], "pairs_file": os.path.basename(p)})
            n += 1
        h = md5(p); exp = PAIRS_OF_RECORD.get(os.path.basename(p))
        tag = "OK" if exp and exp == (h, n) else "WARN not a pairs file of record"
        print(f"{p}: loaded {n} pairs (MD5 {h}) {tag}")
        if n == 0:
            sys.exit(f"FAIL pairs file contributed zero rows: {p}")
    return rows

def frames(x):
    n = (len(x) - L) // HOP + 1
    if n < 2:
        return None
    idx = np.arange(L)[None, :] + HOP * np.arange(n)[:, None]
    return x[idx]

def one(r):
    try:
        ref = np.fromfile(r["ref"], dtype="<f4").astype(np.float64)
        tst = np.fromfile(r["test"], dtype="<f4").astype(np.float64)
        ref_len, test_len = len(ref), len(tst)
        if ref_len != test_len:
            return dict(r, status="FAIL_LENGTH_MISMATCH", n_frames=0, ref_len=ref_len, test_len=test_len)
        if not np.isfinite(ref).all() or not np.isfinite(tst).all():
            return dict(r, status="FAIL_NONFINITE", n_frames=0, ref_len=ref_len, test_len=test_len)
        ref, tst = ref[WASHOUT:], tst[WASHOUT:]
        e = tst - ref
        Fe, Fr = frames(e), frames(ref)
        if Fe is None:
            return dict(r, status="FAIL_SHORT", n_frames=0)
        Pe = (Fe ** 2).mean(axis=1); Pr = (Fr ** 2).mean(axis=1)
        keep = Pr >= PFLOOR
        Pe, Pr = Pe[keep], Pr[keep]
        if len(Pe) < 3:
            return dict(r, status="FAIL_SILENT", n_frames=int(keep.sum()))
        de = 10 * np.log10(np.maximum(Pe, 1e-30)); dr = 10 * np.log10(Pr)
        if de.std() == 0 or dr.std() == 0:
            return dict(r, status="FAIL_DEGENERATE", n_frames=int(len(Pe)), ref_len=ref_len, test_len=test_len)
        rho = float(np.corrcoef(de, dr)[0, 1])
        beta = float(np.polyfit(dr, de, 1)[0])
        esr = float(10 * np.log10(max((e ** 2).sum() / max((ref ** 2).sum(), 1e-30), 1e-30)))
        if not all(np.isfinite(v) for v in (rho, beta, esr)):
            return dict(r, status="FAIL_NONFINITE", n_frames=int(len(Pe)), ref_len=ref_len, test_len=test_len)
        return dict(r, status="OK", n_frames=int(len(Pe)), n_dropped=int((~keep).sum()),
                    rho_full=rho, rho_L=f"{rho:.4f}", beta_dBdB=f"{beta:.4f}",
                    ref_len=ref_len, test_len=test_len, truncated=0, esr_db=f"{esr:.2f}")
    except Exception as ex:
        return dict(r, status=f"FAIL_{type(ex).__name__}", n_frames=0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", action="extend", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    print(SENTINEL)
    if os.path.exists(a.out):
        sys.exit(f"FAIL fail-if-exists: {a.out}")
    rows = load_pairs(a.pairs)
    print(f"{len(rows)} pairs, {a.workers} workers")
    keys = {(r["cell"], r["src"], r["width"]) for r in rows}
    grid = {(c, s, w) for c in CELLS for s in SRCS for w in W}
    if len(rows) != 510 or keys != grid:
        sys.exit(f"FAIL coverage before run: {len(rows)} rows, missing {len(grid-keys)}, extra {len(keys-grid)}")
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        res = list(ex.map(one, rows, chunksize=4))
    bad = [r for r in res if r["status"] != "OK"]
    if bad:
        for r in bad[:10]:
            print("  ", r["cell"], r["src"], r["width"], r["status"])
        sys.exit(f"FAIL {len(bad)} pairs did not score; no output written")
    res.sort(key=lambda r: (CELLS.index(r["cell"]), SRCS.index(r["src"]), r["width"]))
    fields = ["cell", "src", "width", "rho_L", "beta_dBdB", "n_frames", "n_dropped", "esr_db",
              "ref_len", "test_len", "truncated", "status", "pairs_file", "ref", "test"]
    with open(a.out, "x", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        wr.writeheader(); wr.writerows(res)
    print(f"coverage gate PASS 510/510; wrote {a.out} bytes {os.path.getsize(a.out)} MD5 {md5(a.out)}")

    D = {(r["cell"], r["src"], r["width"]): r["rho_full"] for r in res}  # full precision for clauses
    def m(c, w): return float(np.mean([D[(c, s, w)] for s in SRCS]))
    print(f"\nsource-mean rho_L\n{'cell':11}" + "".join(f"{w:>6}" for w in W))
    for c in CELLS:
        print(f"{c:11}" + "".join(f"{m(c, w):6.2f}" for w in W))
    c1 = {c: m(c, 8) - m(c, 16) for c in HUMP}
    c1_hit = sum(v >= 0.30 for v in c1.values())
    c2_cells = [c for c in CELLS if all(m(c, w) < 0.30 for w in REGB)]
    print(f"\nT5-C1 rho_L(w8)-rho_L(w16) >= 0.30 in hump cells: {c1_hit}/4 "
          + " ".join(f"{c}={v:+.4f}" for c, v in c1.items()) + f" -> {'HIT' if c1_hit == 4 else 'MISS'}")
    print(f"T5-C2 rho_L < 0.30 at every W in w15-w21 (full precision; max in B = {max(m(c, w) for c in CELLS for w in REGB):.4f}): {len(c2_cells)}/6 cells {c2_cells} "
          f"-> {'HIT' if len(c2_cells) >= 4 else 'MISS'}")
    print("T5-C3 gt_max/gt_mod rows above are descriptive (no clause)")

if __name__ == "__main__":
    main()
