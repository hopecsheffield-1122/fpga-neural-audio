# SENTINEL: REPRO-CSV-REV1
# Exports a reproduction run to a human-readable CSV: one row per sample,
# with the golden input, the FP32 reference, this run's fixed-point output,
# and the per-sample error. Openable directly in Excel. Stdlib only.
# Called automatically by run_repro.ps1 after verification; can also be run
# standalone on an existing dump:  python dump_csv.py --width 20
import argparse, csv, os, struct, sys
ap = argparse.ArgumentParser()
ap.add_argument("--width", type=int, required=True)
ap.add_argument("--pack", default=os.path.dirname(os.path.abspath(__file__)))
a = ap.parse_args()
tdd = os.path.join(a.pack, "testdata")
dump = os.path.join(a.pack, "out", "golden_repro_w%d.f32" % a.width)
out = os.path.join(a.pack, "out", "golden_repro_w%d.csv" % a.width)
print("REPRO-CSV-REV1  width=%d" % a.width)
if os.path.exists(out):
    sys.exit("FATAL: %s exists (fail-if-exists; delete to regenerate)" % out)
def read_f32(p):
    if not os.path.exists(p):
        sys.exit("FATAL: missing %s" % p)
    raw = open(p, "rb").read()
    if len(raw) % 4:
        sys.exit("FATAL: %s size %d not a multiple of 4" % (p, len(raw)))
    return struct.unpack("<%df" % (len(raw) // 4), raw)
x = read_f32(os.path.join(tdd, "golden_input.bin"))
g = read_f32(os.path.join(tdd, "golden_output.bin"))
y = read_f32(dump)
if not (len(x) == len(g) == len(y)):
    sys.exit("FATAL: length mismatch input=%d golden=%d output=%d" % (len(x), len(g), len(y)))
with open(out, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["sample", "input", "golden_fp32", "fixed_output_w%d" % a.width, "error"])
    for i in range(len(x)):
        w.writerow([i, "%.9g" % x[i], "%.9g" % g[i], "%.9g" % y[i], "%.9g" % (y[i] - g[i])])
worst = max(range(len(x)), key=lambda i: abs(y[i] - g[i]))
print("wrote %s (%d rows)" % (out, len(x)))
print("worst sample by |error|: %d  (error %.6e)" % (worst, y[worst] - g[worst]))
