# SENTINEL: REPRO-TDCSV-REV1
# One-time exporter: writes testdata/golden_testdata.csv -- the golden dry
# stimulus and the FP32 reference output, sample by sample, in readable
# form. These are the exact values inside golden_input.bin (the 4,096-
# sample synthetic dry test vector, MD5 607F8F6F..., exported from the
# rodent_max_v2 checkpoint's export contract) and golden_output.bin (the
# PyTorch FP32 reference through the same model, MD5 0B2625DD...). The
# binary files are the hashed artifacts of record; this CSV is the same
# data in spreadsheet form. Stdlib only. Run once from the pack dir:
#   python export_testdata_csv.py
import csv, os, struct, sys
pack = os.path.dirname(os.path.abspath(__file__))
tdd = os.path.join(pack, "testdata")
out = os.path.join(tdd, "golden_testdata.csv")
print("REPRO-TDCSV-REV1")
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
if len(x) != len(g):
    sys.exit("FATAL: length mismatch input=%d golden=%d" % (len(x), len(g)))
with open(out, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["sample", "dry_input", "golden_fp32_output"])
    for i in range(len(x)):
        w.writerow([i, "%.9g" % x[i], "%.9g" % g[i]])
print("wrote %s (%d rows)" % (out, len(x)))
print("dry input:  %d samples, min %.6g max %.6g" % (len(x), min(x), max(x)))
print("fp32 ref :  min %.6g max %.6g" % (min(g), max(g)))
