"""VERIFY-RES-REV2-20260913
REV2: repo-relative defaults and a flat report layout. Re-derives every row of
results/hardware/resources_by_width_REV1.csv from reports/impl/<report_dir>_utilization_placed.rpt and
<report_dir>_timing_summary_routed.rpt and compares LUT / FF / BRAM / DSP and WNS.
Run from the repo root:  python scripts/verify_resources_REV2.py [--csv PATH] [--reports DIR] [--out PATH]
Writes the verdict CSV only when --out is given (fail-if-exists). Exit 0 iff every row MATCHes.
REV1 (2026-09-06) read the NAS tree; its logic is unchanged.
"""
import argparse
import csv, hashlib, os, re, sys

SENTINEL = "VERIFY-RES-REV2-20260913"
CSV_MD5_EXPECT = "0F619220C9333A962BBABF5CEF29E221"   # resources_by_width_REV1.csv of record; mismatch is a WARN
UTIL = "utilization_placed.rpt"
TIMING = "timing_summary_routed.rpt"

def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest().upper()

def grab(text, label):
    m = re.search(r"^\|\s*" + re.escape(label) + r"\s*\|\s*([0-9.]+)\s*\|", text, re.M)
    return float(m.group(1)) if m else None

def wns(text):
    # first numeric row after the "WNS(ns)" header in the Design Timing Summary
    i = text.find("WNS(ns)")
    if i < 0:
        return None
    for line in text[i:].splitlines()[2:6]:
        toks = line.split()
        if toks and re.match(r"^-?[0-9]+\.[0-9]+$", toks[0]):
            return float(toks[0])
    return None

def main():
    ap = argparse.ArgumentParser(description=SENTINEL)
    ap.add_argument("--csv", default=os.path.join("results", "hardware", "resources_by_width_REV1.csv"))
    ap.add_argument("--reports", default=os.path.join("reports", "impl"))
    ap.add_argument("--out", default=None, help="verdict CSV path (fail-if-exists); omitted = print only")
    a = ap.parse_args()
    CSV_IN, REPORTS, CSV_OUT = a.csv, a.reports, a.out
    if CSV_OUT and os.path.exists(CSV_OUT):
        sys.exit(f"FAIL: output exists (fail-if-exists): {CSV_OUT}")
    m = md5(CSV_IN)
    if m != CSV_MD5_EXPECT:
        print(f"WARN: input CSV MD5 {m} != record {CSV_MD5_EXPECT} (continuing)")
    rows = list(csv.DictReader(open(CSV_IN, newline="")))
    out, n_ok, n_bad, n_missing = [], 0, 0, 0
    for r in rows:
        up = os.path.join(REPORTS, f'{r["report_dir"]}_{UTIL}')
        tp = os.path.join(REPORTS, f'{r["report_dir"]}_{TIMING}')
        rec = dict(cell=r["cell"], width=r["width"], arm=r["arm"], report_dir=r["report_dir"])
        if not os.path.exists(up):
            rec.update(status="MISSING_REPORT", note=up); n_missing += 1; out.append(rec); continue
        t = open(up, encoding="utf-8", errors="replace").read()
        got = dict(lut=grab(t, "Slice LUTs"), ff=grab(t, "Slice Registers"),
                   bram=grab(t, "Block RAM Tile"), dsp=grab(t, "DSPs"))
        has_timing = os.path.exists(tp)
        got["wns_ns"] = wns(open(tp, encoding="utf-8", errors="replace").read()) if has_timing else None
        diffs, notes = [], []
        for k in ("lut", "ff", "bram", "dsp", "wns_ns"):
            want = float(r[k]) if r[k] not in ("", None) else None
            g = got[k]
            if k == "wns_ns" and not has_timing:
                notes.append("wns:no_timing_report"); continue
            if g is None or want is None:
                diffs.append(f"{k}:unparsed")
            elif abs(g - want) > (0.0005 if k == "wns_ns" else 0):
                diffs.append(f"{k}:csv={want:g} rpt={g:g}")
        rec.update({f"rpt_{k}": got[k] for k in got})
        rec.update(util_md5=md5(up), status="MATCH" if not diffs else "MISMATCH", note=";".join(diffs + notes))
        n_ok += not diffs; n_bad += bool(diffs)
        out.append(rec)
    fields = ["cell", "width", "arm", "report_dir", "status", "note",
              "rpt_lut", "rpt_ff", "rpt_bram", "rpt_dsp", "rpt_wns_ns", "util_md5"]
    if CSV_OUT:
        with open(CSV_OUT, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
            for rec in out:
                w.writerow({k: rec.get(k, "") for k in fields})
    print(f"{SENTINEL}  rows={len(rows)}  MATCH={n_ok}  MISMATCH={n_bad}  MISSING={n_missing}")
    shown = 0
    for rec in out:
        if rec["status"] != "MATCH":
            shown += 1
            if shown <= 25:
                print(f"  {rec['status']:14s} {rec['report_dir']}: {rec['note']}")
    if shown > 25:
        print(f"  ... {shown - 25} more non-MATCH rows in the CSV")
    if CSV_OUT:
        print(f"  wrote {CSV_OUT}  bytes {os.path.getsize(CSV_OUT)}  MD5 {md5(CSV_OUT)}")
    sys.exit(0 if (n_bad == 0 and n_missing == 0) else 1)

if __name__ == "__main__":
    main()
