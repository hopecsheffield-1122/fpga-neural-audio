# SCORE-HELDOUT-ESR-REV1  (derived from SCORE-XCELL-ESR-REV1, D2D723A8...)
# Held-out float-ref ESR scorer: board outputs vs per-cell float refs, via
# certified hls_metrics.py (HLSMETRICS-V4-REV1), --hls/--ref pass, --skip 1024.
# Changes vs SCORE-XCELL-ESR-REV1 (configuration only; scoring path identical):
#   - cells: all six (rodent_max included); stims: bass, gtr4ib; NAS dir + CSV names
#   - refs are FLAT-NAMED: <refroot>\anchor_<stim>_ref32_<cell>.f32 (GENCELLREFS-REV3
#     output) instead of cellrefs_<cell>\anchor_<stim>_ref32.f32
#   - manifest gate: board file MD5 must match verified_manifest.csv (PULL-HO-REV1)
#     before scoring; no manifest row -> skipped, counted, not scored
#   - length gate: board bytes == ref bytes, else row skipped as LEN_MISMATCH
# Incremental + rerun-safe; --limit N smoke gate; WARN lines -> warn log.
#
# Machine: LENNY, GRU dir, gru venv:
#   python score_heldout_esr_REV1.py --limit 2      (smoke)
#   python score_heldout_esr_REV1.py                (full 204)
import argparse, csv, hashlib, os, subprocess, sys, time
SENTINEL = "SCORE-HELDOUT-ESR-REV1"
CELLS = ["rodent_max", "rodent_mod", "gt_max", "gt_mod", "fl_max", "fl_mod"]
STIMS = ["bass", "gtr4ib"]
ap = argparse.ArgumentParser()
ap.add_argument("--nas",     default=r"<NAS>\board_heldout_2026-09-06")
ap.add_argument("--manifest",default=r"<NAS>\board_heldout_2026-09-06\verified_manifest.csv")
ap.add_argument("--refroot", default=r"<HLS_IO_HELDOUT>")
ap.add_argument("--csv",     default="heldout_esr_REV1.csv")
ap.add_argument("--warnlog", default="heldout_esr_REV1_warns.log")
ap.add_argument("--scorer",  default="hls_metrics.py")
ap.add_argument("--scorer-md5", default="018B15ADF8458AD29EC59D242A9A273B")  # HLSMETRICS-V4-REV1
ap.add_argument("--limit",   type=int, default=0)
ap.add_argument("--skip",    type=int, default=1024)
ap.add_argument("--cells",   default=",".join(CELLS))
ap.add_argument("--stims",   default=",".join(STIMS))
ap.add_argument("--widths",  default=",".join(str(w) for w in range(8, 25)))
a = ap.parse_args()
def md5f(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""): h.update(ch)
    return h.hexdigest().upper()
print(SENTINEL, "self-MD5", md5f(os.path.abspath(__file__)))
sm = md5f(a.scorer)
if sm != a.scorer_md5.upper():
    sys.exit("FATAL: %s MD5 %s != certified %s" % (a.scorer, sm, a.scorer_md5))
print("scorer gate PASS: %s %s" % (a.scorer, sm))
if not os.path.exists(a.manifest):
    sys.exit("FATAL: verified manifest missing: %s (run pull_heldout_REV1.ps1 first)" % a.manifest)
vman = {r["file"]: r["md5"].upper() for r in csv.DictReader(open(a.manifest, newline=""))}
print("verified manifest: %d files" % len(vman))
done = set()
if os.path.exists(a.csv):
    with open(a.csv, newline="") as f:
        for r in csv.DictReader(f):
            done.add(r["label"])
cells  = a.cells.split(","); stims = a.stims.split(","); widths = [int(w) for w in a.widths.split(",")]
n_run = n_skip_done = n_skip_missing = n_unverified = n_vfail = n_len = n_warn = n_err = 0
t0 = time.time()
for cell in cells:
    for w in widths:
        for stim in stims:
            label = "board_%s_%s_w%d" % (stim, cell, w)
            if label in done:
                n_skip_done += 1; continue
            fn = label + ".f32"
            test = os.path.join(a.nas, fn)
            ref  = os.path.join(a.refroot, "anchor_%s_ref32_%s.f32" % (stim, cell))
            if not os.path.exists(test):
                n_skip_missing += 1; continue
            if not os.path.exists(ref):
                print("ERROR missing ref: %s" % ref); sys.exit(1)
            if fn not in vman:
                n_unverified += 1; print("UNVERIFIED (no manifest row, not scored): %s" % fn); continue
            if md5f(test) != vman[fn]:
                n_vfail += 1; print("VERIFY FAIL (not scored): %s" % fn); continue
            if os.path.getsize(test) != os.path.getsize(ref):
                n_len += 1; print("LEN_MISMATCH (not scored): %s %d vs ref %d" % (fn, os.path.getsize(test), os.path.getsize(ref))); continue
            if a.limit and n_run >= a.limit:
                print("limit %d reached -- smoke gate; rerun without --limit to continue" % a.limit)
                print("%s done: scored=%d skipped-done=%d missing=%d unverified=%d verify-fail=%d len-mismatch=%d warns=%d errors=%d elapsed=%.0fs"
                      % (SENTINEL, n_run, n_skip_done, n_skip_missing, n_unverified, n_vfail, n_len, n_warn, n_err, time.time() - t0))
                sys.exit(0)
            p = subprocess.run([sys.executable, a.scorer, "--hls", test,
                                "--ref", ref, "--skip", str(a.skip),
                                "--csv", a.csv, "--label", label],
                               capture_output=True, text=True)
            out = (p.stdout or "") + (p.stderr or "")
            if p.returncode != 0:
                n_err += 1
                print("SCORER ERROR %s (rc=%d): %s" % (label, p.returncode, out.strip()[:200]))
                continue
            if "WARN" in out:
                n_warn += 1
                wl = [l for l in out.splitlines() if "WARN" in l]
                with open(a.warnlog, "a") as f:
                    for l in wl:
                        f.write("%s  %s\n" % (label, l))
                print("WARN    %s: %s" % (label, "; ".join(wl)))
            n_run += 1
            nl = [l for l in out.splitlines() if "ESR" in l.upper()]
            print("scored  %-34s %s  [%.1fs]" % (label,
                  nl[0].strip()[:80] if nl else "(row appended)", time.time() - t0))
print("%s done: scored=%d skipped-done=%d missing=%d unverified=%d verify-fail=%d len-mismatch=%d warns=%d errors=%d elapsed=%.0fs"
      % (SENTINEL, n_run, n_skip_done, n_skip_missing, n_unverified, n_vfail, n_len, n_warn, n_err, time.time() - t0))
