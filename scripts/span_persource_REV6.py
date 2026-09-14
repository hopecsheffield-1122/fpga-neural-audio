#!/usr/bin/env python3
# SENTINEL: SPAN-PERSRC-REV6-20260910
# REV6 (2026-09-10): first positional argument is the matrix folder written by build_matrices_REV1
# (esr_matrix.csv / odg_matrix.csv derived from the original scorer CSVs) instead of the workbook.
# nam ESR still read from board_nam_metrics CSV (unchanged). Every rule, loader and verdict
# unchanged from REV5. Acceptance gate: output CSV byte-identical to span_heldout_REV5.csv except
# the sentinel field.
# Lineage: REV2 (4B09B591) as-registered adjudication; REV3 (F8543D0D) added an aligned
# hump rule + in-training comparison; REV4 (951EFA68) fixed a shadowed variable; REV5
# finalises the aligned rule on the in-training nam curves (REV4's rule reproduced 27/30;
# the 3 misses were ceiling wobbles at w21/w23 and a 0.16 dB bump).
# H4 as registered ("NMR local-maximum width" was under-specified in HELDOUT-PREREG-REV1;
# REV2 used the highest-value local maximum) is UNCHANGED and reported first.
# Aligned rule "last_qualifying_max" (post-registration, reported beside H4, never replacing
# it): hump_w_aligned = the largest-W interior local maximum (9..23) with prominence >
# --aligned-tol dB (default 0.5) AND a drop of >= --min-drop dB (default 20) from the
# maximum to W=24. None qualifying => monotone. --train-nmr (tidy CSV, NMRPULL-REV2
# schema) applies the same rule to the 30 in-training curves next to the pre-reg values.
# Held-out program-source arm: adjudicates HELDOUT-PREREG-REV1 clauses H1-H4, reports H5.
# Derived from SPAN-PERSRC-REV1 (AEA21257...): the selection rule, first-crossing helper,
# in-training loaders (workbook + nam CSV) and the source-mean check are UNCHANGED.
# REV2 adds: held-out rows read from the three scorer CSVs (never the workbook):
#   ESR  : heldout_esr_REV1.csv   (hls_metrics.py CSV; label board_<src>_<cell>_w<W>, esr_db)
#   ODG  : peaq_heldout_REV1.csv  (SCORE-PEAQ-REV2; cell,src,width,odg,...)
#   NMR  : heldout_nmr_REV1.csv   (SCORE-HELDOUT-NMR-REV1; cell,stim,width,nmr_db,status)
# Coverage gate: 6 cells x 2 sources x 17 widths present in ALL THREE CSVs, NMR status OK,
# else FAIL before any verdict is printed (read rule: adjudicate only on the full 204).
# Fail-if-exists output. Self-MD5 and every input MD5 printed.
#
# Usage (LENNY, GRU dir, gru venv):
#   python span_persource_REV6.py <matrix folder> board_nam_metrics.csv ^
#       heldout_esr_REV1.csv peaq_heldout_REV1.csv heldout_nmr_REV1.csv span_heldout_REV6.csv
#   options: --tau -20 --theta -0.5 --hump-tol 0.0 --taus ... --thetas ...
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


SENT = "SPAN-PERSRC-REV6-20260910"
CELLS = ["rodent_max", "rodent_mod", "gt_max", "gt_mod", "fl_max", "fl_mod"]
SRCS = ["nam", "gtr2", "gtr4sg", "prvtgtr", "ytbass"]          # in-training (Fig. 1)
HSRCS = ["bass", "gtr4ib"]                                       # held-out
W = list(range(8, 25))
PAPER_SPANS = {"rodent_max": 3, "rodent_mod": 4, "gt_max": 5, "gt_mod": 3, "fl_max": 6, "fl_mod": 4}
# H4 in-training NMR local-maximum widths (five-source mean) from HELDOUT_PREREG_REV1.txt
H4_HUMP = {"rodent_max": (13, 14), "rodent_mod": (12, 12), "fl_max": (13, 13), "fl_mod": (13, 13)}
H4_MONO = ["gt_max", "gt_mod"]

def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest().upper()

# ---------------- unchanged from REV1 ----------------
def parse_source_blocks(path):
    out, src, widths = {}, None, None
    for row in _csv_rows(path):
        c0 = row[0]
        if isinstance(c0, str) and c0.startswith("source:"):
            src = c0.split(":", 1)[1].strip()
        elif c0 == "cell":
            widths = [int(str(w)[1:]) for w in row[1:] if w]
        elif isinstance(c0, str) and c0 in CELLS and src:
            vals = [float(v) for v in row[1:1 + len(widths)]]
            out.setdefault(src, {})[c0] = dict(zip(widths, vals))
    return out

def load_nam_esr(esr_csv):
    out = {c: {} for c in CELLS}
    with open(esr_csv, newline="") as f:
        for row in csv.DictReader(f):
            lab = row["label"]
            if not lab.endswith("_float_ref"):
                continue
            core = lab[: -len("_float_ref")].replace("board_", "")
            cell, wtag = core.rsplit("_nam_w", 1)
            out[cell][int(wtag)] = float(row["esr_db"])
    for c in CELLS:
        assert len(out[c]) == 17, f"nam ESR incomplete for {c}: {len(out[c])}"
    return out

def first(curve, pred):
    for w in W:
        if pred(curve[w]):
            return w
    return None
# -----------------------------------------------------

def load_heldout_esr(p):
    out = {s: {c: {} for c in CELLS} for s in HSRCS}
    with open(p, newline="") as f:
        for row in csv.DictReader(f):
            lab = row["label"]
            if not lab.startswith("board_"):
                continue
            core = lab[len("board_"):]
            src, rest = core.split("_", 1)
            if src not in HSRCS:
                continue
            cell, wtag = rest.rsplit("_w", 1)
            if cell in CELLS:
                out[src][cell][int(wtag)] = float(row["esr_db"])
    return out

def load_heldout_odg(p):
    out = {s: {c: {} for c in CELLS} for s in HSRCS}
    with open(p, newline="") as f:
        for row in csv.DictReader(f):
            if row["src"] in HSRCS and row["cell"] in CELLS:
                out[row["src"]][row["cell"]][int(row["width"])] = float(row["odg"])
    return out

def load_heldout_nmr(p):
    out = {s: {c: {} for c in CELLS} for s in HSRCS}
    with open(p, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("status") != "OK":
                continue
            if row["stim"] in HSRCS and row["cell"] in CELLS:
                out[row["stim"]][row["cell"]][int(row["width"])] = float(row["nmr_db"])
    return out

def coverage(d, name):
    miss = [(s, c, w) for s in HSRCS for c in CELLS for w in W if w not in d[s][c]]
    if miss:
        sys.exit(f"FAIL coverage {name}: {len(miss)} missing, first {miss[:5]}")

def hump_last_qualifying(curve, tol, min_drop):
    """Largest interior local-max W with prominence > tol and (nmr[W] - nmr[24]) >= min_drop."""
    for w, v, _ in sorted(local_maxima(curve, tol), reverse=True):
        if v - curve[24] >= min_drop:
            return w
    return None

def load_train_nmr(p):
    out = {}
    with open(p, newline="") as f:
        for r in csv.DictReader(f):
            if r["cell"] in CELLS:
                out.setdefault((r["cell"], r["source"]), {})[int(r["width"])] = float(r["nmr_db"])
    return out

def local_maxima(curve, tol):
    """Interior W (9..23) where nmr[W] exceeds BOTH neighbours by more than tol dB."""
    out = []
    for w in W[1:-1]:
        if curve[w] - curve[w - 1] > tol and curve[w] - curve[w + 1] > tol:
            out.append((w, curve[w], min(curve[w] - curve[w - 1], curve[w] - curve[w + 1])))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("matrix_dir", help="folder with esr_matrix.csv / odg_matrix.csv"); ap.add_argument("nam_esr_csv")
    ap.add_argument("ho_esr_csv"); ap.add_argument("ho_peaq_csv"); ap.add_argument("ho_nmr_csv")
    ap.add_argument("out")
    ap.add_argument("--tau", type=float, default=-20.0); ap.add_argument("--theta", type=float, default=-0.5)
    ap.add_argument("--hump-tol", type=float, default=0.0,
                    help="dB by which an NMR local max must exceed both neighbours (H4). Fix BEFORE running.")
    ap.add_argument("--aligned-tol", type=float, default=0.5,
                    help="prominence (dB) a local maximum needs under the aligned rule")
    ap.add_argument("--min-drop", type=float, default=20.0,
                    help="minimum drop (dB) from the hump to W=24 under the aligned rule")
    ap.add_argument("--train-nmr", default=None, help="tidy in-training NMR CSV (cell,source,width,nmr_db)")
    ap.add_argument("--taus", default="-10,-15,-20,-25,-30", help="H5 grid taus (dB)")
    ap.add_argument("--thetas", default="-0.2,-0.5,-1.0", help="H5 grid thetas (ODG)")
    a = ap.parse_args()
    if os.path.exists(a.out):
        sys.exit(f"FAIL fail-if-exists: {a.out}")
    print(SENT)
    print(f"script  : {os.path.basename(__file__)} MD5 {md5(os.path.abspath(__file__))}")
    for k in ("nam_esr_csv", "ho_esr_csv", "ho_peaq_csv", "ho_nmr_csv"):
        p = getattr(a, k)
        print(f"{k:11}: {p}  {os.path.getsize(p)} B  MD5 {md5(p)}")
    if a.train_nmr:
        print(f"{'train_nmr':11}: {a.train_nmr}  {os.path.getsize(a.train_nmr)} B  MD5 {md5(a.train_nmr)}")
    print(f"rule: tau={a.tau:g} dB, theta={a.theta:g}, hump-tol={a.hump_tol:g} dB (as-registered); "
          f"aligned: prominence>{a.aligned_tol:g} dB, drop>={a.min_drop:g} dB")

    # in-training (unchanged path)
    ep = os.path.join(a.matrix_dir, "esr_matrix.csv"); op = os.path.join(a.matrix_dir, "odg_matrix.csv")
    for p in (ep, op):
        print(f"{os.path.basename(p):11}: {p}  {os.path.getsize(p)} B  MD5 {md5(p)}")
    esr = parse_source_blocks(ep); odg = parse_source_blocks(op)
    esr["nam"] = load_nam_esr(a.nam_esr_csv)
    missing = [(c, s) for s in SRCS for c in CELLS if c not in esr.get(s, {}) or c not in odg.get(s, {})]
    if missing:
        sys.exit(f"FAIL in-training coverage: missing {missing}")

    # held-out (CSV-only), full-coverage gate
    hesr = load_heldout_esr(a.ho_esr_csv); hodg = load_heldout_odg(a.ho_peaq_csv); hnmr = load_heldout_nmr(a.ho_nmr_csv)
    coverage(hesr, "held-out ESR"); coverage(hodg, "held-out ODG"); coverage(hnmr, "held-out NMR (status OK)")
    print("coverage gate PASS: 204/204 rows in ESR, ODG and NMR")

    # ---- 12 held-out spans ----
    rows = []
    for c in CELLS:
        for s in HSRCS:
            we = first(hesr[s][c], lambda v: v <= a.tau); wo = first(hodg[s][c], lambda v: v >= a.theta)
            span = (wo - we) if (we is not None and wo is not None) else None
            lm = local_maxima(hnmr[s][c], a.hump_tol)
            primary = max(lm, key=lambda t: t[1])[0] if lm else None
            aligned = hump_last_qualifying(hnmr[s][c], a.aligned_tol, a.min_drop)
            rows.append(dict(cell=c, src=s, w_esr=we, w_odg=wo, span=span,
                             nmr_lmax=";".join(f"w{w}:{v:.3f}(+{pr:.3f})" for w, v, pr in lm) or "none",
                             hump_w=primary, hump_w_aligned=aligned))

    print(f"\nheld-out span at (tau={a.tau:g} dB, theta={a.theta:g})  [w_esr->w_odg]   NMR local maxima")
    for r in rows:
        cellstr = "undef" if r["span"] is None else f"{r['w_esr']}->{r['w_odg']} ({r['span']:+d})"
        print(f"  {r['cell']:11} {r['src']:7} {cellstr:>14}   {r['nmr_lmax']}")

    vals = [r["span"] for r in rows if r["span"] is not None]
    und = [(r["cell"], r["src"]) for r in rows if r["span"] is None]
    # ---- verdicts ----
    h1 = all(v > 0 for v in vals)
    h2 = all(2 <= v <= 6 for v in vals)
    h3 = len(und) <= 1
    h4_parts = []
    h4 = True
    for c, (lo, hi) in H4_HUMP.items():
        for s in HSRCS:
            hw = next(r["hump_w"] for r in rows if r["cell"] == c and r["src"] == s)
            ok = hw is not None and (lo - 1) <= hw <= (hi + 1)
            h4 &= ok
            h4_parts.append(f"{c}/{s}: hump {hw} vs [{lo-1},{hi+1}] {'HIT' if ok else 'MISS'}")
    for c in H4_MONO:
        for s in HSRCS:
            lm = next(r["nmr_lmax"] for r in rows if r["cell"] == c and r["src"] == s)
            ok = (lm == "none")
            h4 &= ok
            h4_parts.append(f"{c}/{s}: monotone {'HIT' if ok else 'MISS (' + lm + ')'}")

    print(f"\nn defined = {len(vals)}/12; " + (f"min {min(vals):+d}, max {max(vals):+d}, mean {np.mean(vals):+.2f}; " if vals else "")
          + f"positive {sum(v > 0 for v in vals)}, zero {sum(v == 0 for v in vals)}, negative {sum(v < 0 for v in vals)}"
          + (f"; undefined {und}" if und else ""))
    h4a_parts = []; h4a = True
    for c, (lo, hi) in H4_HUMP.items():
        for s in HSRCS:
            hw = next(r["hump_w_aligned"] for r in rows if r["cell"] == c and r["src"] == s)
            ok = hw is not None and (lo - 1) <= hw <= (hi + 1)
            h4a &= ok
            h4a_parts.append(f"{c}/{s}: hump {hw} vs [{lo-1},{hi+1}] {'HIT' if ok else 'MISS'}")
    for c in H4_MONO:
        for s in HSRCS:
            hw = next(r["hump_w_aligned"] for r in rows if r["cell"] == c and r["src"] == s)
            ok = hw is None
            h4a &= ok
            h4a_parts.append(f"{c}/{s}: monotone {'HIT' if ok else 'MISS (hump ' + str(hw) + ')'}")

    print("\nVERDICTS (HELDOUT-PREREG-REV1)")
    print(f"  H1 sign      : {'HIT' if h1 else 'MISS'}  (deciding: min span {min(vals) if vals else 'n/a'})")
    print(f"  H2 range     : {'HIT' if h2 else 'MISS'}  (deciding: spans outside [2,6] = {[v for v in vals if not 2 <= v <= 6]})")
    print(f"  H3 count     : {'HIT' if h3 else 'MISS'}  (deciding: {len(und)} undefined of 12)")
    print(f"  H4 hump      : {'HIT' if h4 else 'MISS'}")
    for p in h4_parts:
        print("     " + p)
    print(f"  H4_aligned   : {'HIT' if h4a else 'MISS'}  (post-registration rule last_qualifying_max: "
          f"prominence>{a.aligned_tol:g} dB, drop>={a.min_drop:g} dB)")
    for p in h4a_parts:
        print("     " + p)

    if a.train_nmr:
        tr = load_train_nmr(a.train_nmr)
        print("\nin-training hump widths under the aligned rule (per source; pre-reg five-source value in brackets)")
        for c in CELLS:
            tv = []
            for (cc, ss), curve in sorted(tr.items()):
                if cc != c: continue
                if not all(w in curve for w in W): continue
                tv.append(f"{ss}:{hump_last_qualifying(curve, a.aligned_tol, a.min_drop)}")
            ref = H4_HUMP.get(c)
            print(f"  {c:11} {' '.join(tv):60} [{ref[0]}-{ref[1]}]" if ref else f"  {c:11} {' '.join(tv):60} [monotone]")

    # ---- H5: (tau, theta) grid, source means over 5 (in-training) and 7 (with held-out) ----
    taus = [float(x) for x in a.taus.split(",")]; thetas = [float(x) for x in a.thetas.split(",")]
    def grid(esr_d, odg_d, srcs):
        res = {}
        for t in taus:
            for th in thetas:
                spans = {}
                for c in CELLS:
                    me = {w: np.mean([esr_d[s][c][w] for s in srcs]) for w in W}
                    mo = {w: np.mean([odg_d[s][c][w] for s in srcs]) for w in W}
                    we = first(me, lambda v: v <= t); wo = first(mo, lambda v: v >= th)
                    spans[c] = (wo - we) if (we is not None and wo is not None) else None
                res[(t, th)] = spans
        return res
    esr7 = dict(esr); odg7 = dict(odg)
    for s in HSRCS:
        esr7[s] = hesr[s]; odg7[s] = hodg[s]
    g5 = grid(esr, odg, SRCS); g7 = grid(esr7, odg7, SRCS + HSRCS)
    def npos(sp): return sum(1 for v in sp.values() if v is not None and v > 0)
    print(f"\nH5 grid (descriptive): source-mean spans per model; cell = #models with span>0 / 6")
    print(f"{'tau\\theta':>10}" + "".join(f"{th:>22g}" for th in thetas))
    for t in taus:
        print(f"{t:>10g}" + "".join(f"{'5src ' + str(npos(g5[(t, th)])) + ' | 7src ' + str(npos(g7[(t, th)])):>22}" for th in thetas))
    all5 = sum(1 for k in g5 if npos(g5[k]) == 6); all7 = sum(1 for k in g7 if npos(g7[k]) == 6)
    print(f"grid cells with all six spans positive: 5-source {all5}/{len(g5)}, 7-source {all7}/{len(g7)}")

    # ---- source-mean check (unchanged from REV1) ----
    print("\nsource-mean check (Fig. 1 rule, 5 in-training sources): model  w_esr w_odg span  paper")
    ok = True
    for c in CELLS:
        me = {w: np.mean([esr[s][c][w] for s in SRCS]) for w in W}
        mo = {w: np.mean([odg[s][c][w] for s in SRCS]) for w in W}
        we = first(me, lambda v: v <= a.tau); wo = first(mo, lambda v: v >= a.theta)
        sp = wo - we
        flag = "" if sp == PAPER_SPANS[c] else "  <-- MISMATCH"
        ok &= (sp == PAPER_SPANS[c])
        print(f"  {c:11} {we:5d} {wo:5d} {sp:+4d}  {PAPER_SPANS[c]:+d}{flag}")
    print("source-mean spans reproduce the paper:", "PASS" if ok else "FAIL")

    # ---- output ----
    with open(a.out, "x", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["sentinel", SENT, "tau", a.tau, "theta", a.theta, "hump_tol", a.hump_tol, "aligned_tol", a.aligned_tol, "min_drop", a.min_drop])
        wr.writerow(["cell", "src", "w_esr", "w_odg", "span", "nmr_hump_w", "nmr_hump_w_aligned", "nmr_local_maxima"])
        for r in rows:
            wr.writerow([r["cell"], r["src"], r["w_esr"], r["w_odg"], r["span"], r["hump_w"], r["hump_w_aligned"], r["nmr_lmax"]])
        wr.writerow([])
        wr.writerow(["clause", "verdict", "detail"])
        wr.writerow(["H1", "HIT" if h1 else "MISS", f"min span {min(vals) if vals else 'n/a'}"])
        wr.writerow(["H2", "HIT" if h2 else "MISS", f"outside [2,6]: {[v for v in vals if not 2 <= v <= 6]}"])
        wr.writerow(["H3", "HIT" if h3 else "MISS", f"{len(und)} undefined of 12 {und}"])
        wr.writerow(["H4", "HIT" if h4 else "MISS", " | ".join(h4_parts)])
        wr.writerow(["H4_aligned", "HIT" if h4a else "MISS",
                     f"rule last_qualifying_max prominence>{a.aligned_tol:g} drop>={a.min_drop:g}: " + " | ".join(h4a_parts)])
        wr.writerow(["H5", "descriptive", f"all-positive grid cells 5src {all5}/{len(g5)}, 7src {all7}/{len(g7)}"])
        for (t, th), sp in g7.items():
            wr.writerow(["H5_grid7", f"tau={t:g}", f"theta={th:g}"] + [sp[c] for c in CELLS])
    print(f"\nwrote {a.out} bytes {os.path.getsize(a.out)} MD5 {md5(a.out)}")

if __name__ == "__main__":
    main()
