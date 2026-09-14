# SCORE-PEAQ-REV2
# REV2: adds --lowpass <hz> (audiocheblimit low-pass, 8 poles, both pads) to
# enforce the 2026-08-13 validated envelope ("input band-limited <~21 kHz,
# quiet top octave") at the true 48 kHz clock -- guards gstpeaq 0.6.1's
# unguarded bandwidth-MOV 0/0 on near-Nyquist content (deep-collapse
# quantization noise). REV1 relied on the 44.1k declaration's resampling
# side effect for the same guard.
# Fleet PEAQ scorer (gstpeaq via gst-launch-1.0), manifest-driven.
# Pairs manifest CSV columns: cell,src,width,ref,test  (absolute paths).
# Output CSV: cell,src,width,odg,total_nmr,rate,sentinel  (fresh lineage).
# - Incremental on (cell,src,width); --limit N smoke gate; parse failures
#   logged to warn log (annotate-never-delete), row NOT written.
# - --rate 48000 (corrected clock) or 44100 (reproduces banked REV1 lineage).
# Pipeline reproduced from the banked 2026-08-13 record, rate parameterized.
import argparse, csv, os, re, subprocess, sys, time
SENTINEL = "SCORE-PEAQ-REV2"
ap = argparse.ArgumentParser()
ap.add_argument("--pairs", required=True)
ap.add_argument("--csv", required=True)
ap.add_argument("--warnlog", default=None)
ap.add_argument("--rate", type=int, default=48000)
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--gst", default="gst-launch-1.0")
ap.add_argument("--lowpass", type=int, default=0)
a = ap.parse_args()
warnlog = a.warnlog or (os.path.splitext(a.csv)[0] + "_warns.log")
print(SENTINEL, "rate=%d lowpass=%s" % (a.rate, a.lowpass or "off"))
done = set()
if os.path.exists(a.csv):
    for r in csv.DictReader(open(a.csv, newline="")):
        done.add((r["cell"], r["src"], int(r["width"])))
pairs = list(csv.DictReader(open(a.pairs, newline="")))
def pipeline(ref, test):
    lp = ("audiocheblimit mode=low-pass cutoff=%d poles=8 ! " % a.lowpass) if a.lowpass else ""
    seg = ("filesrc location=%s ! rawaudioparse format=pcm pcm-format=f32le "
           "sample-rate=%d num-channels=1 ! audioconvert ! audioresample ! "
           "audio/x-raw,format=F32LE,rate=48000 ! " + lp + "%s")
    return ([a.gst, "peaq", "name=p", "console-output=true"]
            + (seg % (ref,  a.rate, "p.ref")).split()
            + (seg % (test, a.rate, "p.test")).split())
n_run = n_done = n_miss = n_fail = 0
t0 = time.time()
new = not os.path.exists(a.csv)
fh = open(a.csv, "a", newline="")
w = csv.writer(fh)
if new: w.writerow(["cell", "src", "width", "odg", "total_nmr", "rate", "lowpass", "sentinel"])
for pr in pairs:
    key = (pr["cell"], pr["src"], int(pr["width"]))
    if key in done:
        n_done += 1; continue
    if not (os.path.exists(pr["ref"]) and os.path.exists(pr["test"])):
        n_miss += 1; continue
    if a.limit and n_run >= a.limit:
        print("limit %d reached -- smoke gate; rerun without --limit to continue" % a.limit)
        break
    p = subprocess.run(pipeline(pr["ref"], pr["test"]), capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    modg = re.search(r"Objective Difference Grade:\s*(-?[0-9.]+)", out)
    mnmr = re.search(r"Total NMRB:\s*(-?[0-9.]+)", out)
    n_run += 1
    if not modg or not mnmr or "nan" in (modg.group(1) if modg else "") :
        n_fail += 1
        with open(warnlog, "a") as f:
            f.write("PARSE-FAIL %s_%s_w%s rc=%d tail=%s\n"
                    % (pr["cell"], pr["src"], pr["width"], p.returncode,
                       out.strip().replace("\n", " | ")[-300:]))
        print("PARSE-FAIL %-10s %-8s w%-3s (logged)" % (pr["cell"], pr["src"], pr["width"]))
        continue
    w.writerow([pr["cell"], pr["src"], pr["width"], modg.group(1), mnmr.group(1), a.rate, a.lowpass, SENTINEL])
    fh.flush()
    print("scored  %-10s %-8s w%-3s ODG %s  TotalNMRB %s  [%.0fs]"
          % (pr["cell"], pr["src"], pr["width"], modg.group(1), mnmr.group(1), time.time() - t0))
fh.close()
print("%s done: scored=%d skipped-done=%d missing=%d parse-fail=%d elapsed=%.0fs"
      % (SENTINEL, n_run - n_fail, n_done, n_miss, n_fail, time.time() - t0))
