#!/usr/bin/env python3
# HELDOUT-SRCMEAN-SPAN-REV1-20260908
# IV-A source-mean selection rule applied to the two ToneTwist test-split sources
# (idmt-bass, idmt-gtr4-ib) on their own, plus the per-(model, source) spans as a
# cross-check against span_heldout_REV5.csv (6E012338...).
#
# Rule (unchanged from IV-A): W_esr = smallest W with source-mean ESR <= tau;
#   W_odg = smallest W with source-mean ODG >= theta; span = W_odg - W_esr.
#   Source mean = arithmetic mean of the per-source dB / ODG values.
#
# Inputs (hash-gated):
#   heldout_esr_REV1.csv   MD5 1006EEDF2ACE6A4026FB1F0DE7D56B34  (label,esr_db,mrstft)
#   peaq_heldout_REV1.csv  MD5 4B3FE06EB40DFF73BBBD7EEE9F3174CA  (cell,src,width,odg,...)
# Output: fail-if-exists CSV with the six per-model rows + the twelve per-pair rows,
#   sentinel + input hashes in the header row. Prints the same to console.
#
# Usage (Lenny, GRU dir, venv):
#   python heldout_srcmean_span_REV1.py heldout_esr_REV1.csv peaq_heldout_REV1.csv heldout_srcmean_span_REV1.csv
#   optional: --tau -20 --theta -0.5
import argparse, csv, hashlib, os, re, statistics as st, sys

SENT = "HELDOUT-SRCMEAN-SPAN-REV1-20260908"
CELLS = ["rodent_max", "rodent_mod", "gt_max", "gt_mod", "fl_max", "fl_mod"]
SRCS = ["bass", "gtr4ib"]
W = list(range(8, 25))
EXPECT = {"esr": "1006EEDF", "peaq": "4B3FE06E"}

def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest().upper()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("esr_csv"); ap.add_argument("peaq_csv"); ap.add_argument("out_csv")
    ap.add_argument("--tau", type=float, default=-20.0); ap.add_argument("--theta", type=float, default=-0.5)
    ap.add_argument("--no-hash-gate", action="store_true", help="skip the input-hash check (other input revisions)")
    a = ap.parse_args()
    if os.path.exists(a.out_csv):
        sys.exit(f"FAIL-IF-EXISTS: {a.out_csv}")
    h_esr, h_peaq = md5(a.esr_csv), md5(a.peaq_csv)
    print(f"{SENT}\n  esr_csv : {a.esr_csv} {os.path.getsize(a.esr_csv)} B MD5 {h_esr}\n  peaq_csv: {a.peaq_csv} {os.path.getsize(a.peaq_csv)} B MD5 {h_peaq}")
    if not a.no_hash_gate:
        if not h_esr.startswith(EXPECT["esr"]) or not h_peaq.startswith(EXPECT["peaq"]):
            sys.exit("HASH GATE FAIL: inputs are not the REV1 files of record (use --no-hash-gate for other revisions)")
    print(f"  rule: tau={a.tau:g} dB, theta={a.theta:g}; source mean = mean of per-source values")

    esr, odg = {}, {}
    pat = re.compile(r"board_(bass|gtr4ib)_(rodent_max|rodent_mod|gt_max|gt_mod|fl_max|fl_mod)_w(\d+)$")
    for r in csv.DictReader(open(a.esr_csv, newline="")):
        m = pat.match(r["label"])
        if m:
            esr[(m.group(2), m.group(1), int(m.group(3)))] = float(r["esr_db"])
    for r in csv.DictReader(open(a.peaq_csv, newline="")):
        if r["cell"] in CELLS and r["src"] in SRCS:
            odg[(r["cell"], r["src"], int(r["width"]))] = float(r["odg"])
    n = len(CELLS) * len(SRCS) * len(W)
    if len(esr) != n or len(odg) != n:
        sys.exit(f"COVERAGE FAIL: esr {len(esr)}/{n}, odg {len(odg)}/{n}")
    print(f"  coverage: ESR {len(esr)}/{n}, ODG {len(odg)}/{n}")

    def sm(d, c, w):
        return st.mean(d[(c, s, w)] for s in SRCS)

    def first(seq, cond):
        return next((w for w in W if cond(seq(w))), None)

    rows_model, rows_pair = [], []
    print("\n  per-model (source mean over the two test sources)")
    print("  model       W_esr  W_odg  span")
    for c in CELLS:
        we = first(lambda w: sm(esr, c, w), lambda v: v <= a.tau)
        wo = first(lambda w: sm(odg, c, w), lambda v: v >= a.theta)
        span = None if (we is None or wo is None) else wo - we
        rows_model.append((c, we, wo, span))
        print(f"  {c:10} {str(we):>5}  {str(wo):>5}  {('undef' if span is None else f'{span:+d}'):>5}")
        for s in SRCS:
            wes = first(lambda w: esr[(c, s, w)], lambda v: v <= a.tau)
            wos = first(lambda w: odg[(c, s, w)], lambda v: v >= a.theta)
            rows_pair.append((c, s, wes, wos, None if (wes is None or wos is None) else wos - wes))
    sp = [r[3] for r in rows_model if r[3] is not None]
    print(f"  per-model spans {['%+d' % x for x in sp]}  mean {st.mean(sp):+.2f}  defined {len(sp)}/6")
    pp = [r[4] for r in rows_pair if r[4] is not None]
    print(f"\n  per (model, source): defined {len(pp)}/12, range {min(pp):+d}..{max(pp):+d}, mean {st.mean(pp):+.2f}, positive {sum(x > 0 for x in pp)}")
    for c, s, wes, wos, span in rows_pair:
        print(f"    {c:10} {s:7} {wes}->{wos} {'undef' if span is None else f'{span:+d}'}")

    with open(a.out_csv, "x", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["sentinel", SENT, "tau", a.tau, "theta", a.theta, "esr_md5", h_esr, "peaq_md5", h_peaq])
        wr.writerow(["kind", "cell", "src", "w_esr", "w_odg", "span"])
        for c, we, wo, span in rows_model:
            wr.writerow(["model_srcmean", c, "bass+gtr4ib", we, wo, span])
        for c, s, wes, wos, span in rows_pair:
            wr.writerow(["pair", c, s, wes, wos, span])
        wr.writerow(["summary", "per_model_mean", "", "", "", round(st.mean(sp), 2)])
        wr.writerow(["summary", "per_pair_mean", "", "", "", round(st.mean(pp), 2)])
    print(f"\nwrote {a.out_csv} {os.path.getsize(a.out_csv)} B MD5 {md5(a.out_csv)}")

if __name__ == "__main__":
    main()
