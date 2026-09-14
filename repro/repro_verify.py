# SENTINEL: REPRO-VERIFY-REV1
# Verifies one reproduction run against the certified record. Hash-primary:
# the MD5 of the dump your machine just produced is compared to golden_md5,
# which (by gate B1, 102/102, 2026-08-10) equals BOTH the certified C-sim
# export and the on-silicon FPGA capture for this width. A MATCH means the
# number generated on THIS machine is byte-identical to what the deployed
# hardware produced. The testbench's own metric lines are echoed verbatim
# from the csim log for eyeball comparison against the expected digits.
# Stdlib only; no external packages.
import argparse, csv, hashlib, os, re, sys
ap = argparse.ArgumentParser()
ap.add_argument("--width", type=int, required=True)
ap.add_argument("--dump", required=True)
ap.add_argument("--expected", required=True)
ap.add_argument("--log", default="")
a = ap.parse_args()
print("REPRO-VERIFY-REV1  width=%d" % a.width)
exp = None
with open(a.expected, newline="") as f:
    for r in csv.DictReader(f):
        if int(r["width"]) == a.width:
            exp = r
if exp is None:
    sys.exit("FATAL: width %d not in %s" % (a.width, a.expected))
if not os.path.exists(a.dump):
    sys.exit("FATAL: dump not found: %s (csim may have failed; see log)" % a.dump)
h = hashlib.md5()
with open(a.dump, "rb") as f:
    for blk in iter(lambda: f.read(1 << 20), b""):
        h.update(blk)
got = h.hexdigest()
ref = exp["golden_md5"].lower()
size = os.path.getsize(a.dump)
print("dump: %s  (%d bytes)" % (a.dump, size))
print("MD5 this run : %s" % got)
print("MD5 certified: %s  (csim export == board silicon, gate B1 102/102)" % ref)
match = (got == ref)
print("VERDICT: %s" % ("MATCH -- byte-identical to the certified simulation AND the FPGA silicon capture"
                        if match else "MISMATCH -- do not proceed; check width, sources, and log"))
print("-" * 66)
print("expected digits (cell_grid_102.csv, certified 2026-08-04):")
print("  cosine %s   ESR %s dB   RMSE %s   gate %s" % (exp["cosine"], exp["esr_db"], exp["rmse"], exp["gate"]))
print("  typedef of record: %s" % exp["typedef_note"])
if a.log and os.path.exists(a.log):
    print("testbench metric lines from this run's csim log (verbatim):")
    pat = re.compile(r"cosine|ESR|RMSE|worst|typedef|DT_W|FORMAT", re.I)
    shown = 0
    for line in open(a.log, errors="replace"):
        if pat.search(line):
            print("  | " + line.rstrip())
            shown += 1
            if shown > 25:
                break
    if not shown:
        print("  (no metric lines matched; open the log directly)")
elif a.log:
    print("log not found at %s -- open the csim log manually to compare digits" % a.log)
sys.exit(0 if match else 1)
