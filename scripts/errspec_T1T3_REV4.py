#!/usr/bin/env python3
# SENTINEL: ERRSPEC-T1T3-REV4-2026-09-04
# T1: spectral flatness, coherence, LF/HF tilt of e = y_W - y_f32 per (cell, source, width)
# T3 (option B): valley fraction = share of error energy in third-octave bands where the
#     reference band energy is below its own median.
# Inputs: one or more pairs CSVs (ref/test f32 paths, as used for PEAQ scoring).
# REV4 (supersedes REV3; provenance clean-up, METRIC CODE UNCHANGED): (a) cell/src/width are taken
# from the pairs CSV columns when present (label parsing is the fallback) - closes the anchor85
# blank-cell defect at source; (b) coverage gate BEFORE scoring: the union of all pairs files must be
# exactly the 6x5x17 = 510 grid (override with --allow-partial); (c) coverage gate AFTER scoring:
# every row status OK or no CSV is written; (d) rows written sorted cell->src->width with a
# pairs_file provenance column; (e) byte count printed with the MD5. Pre-registered expectation:
# every sf/coh/tilt_db/valley_frac/esr_int_db digit equals errspec_T1T3_510_MERGED_REV1.csv
# (MD5 675ECF0A64B3C5C14B9AEC2D6C3D49F9); see compare_errspec_REV4_vs_MERGED.py.
# REV3 (supersedes REV2 after one field run): REV2's --pairs used nargs="*", which OVERWRITES on
# repeated flags - a three-flag invocation silently loaded only the last file. REV2's field run is
# therefore a valid music-340 partial (annotated, kept). REV3 uses action="extend" (repeated flags
# AND space-separated lists both accumulate) and prints a per-file loaded count; a pairs file
# contributing zero rows is now FATAL.
# REV2 change history (kept): adds --resolve-root DIR (repeatable). Paths that do not
# exist after --path-sub are re-tried as ROOT\<parentdir>\<file>, then ROOT\<file>. The
# parent-qualified form is tried FIRST because float-ref basenames repeat across cellrefs_<cell>
# dirs with different bytes. If a candidate resolves in more than one root, the run FAILS
# (ambiguity is never silently picked).
# Outputs: tidy CSV (fail-if-exists) + NPZ of error/reference PSDs for Fig. 2 panel (iii).
# Diagnostic-exhibit class: digits never comparable to certified metric rows.
import argparse, csv, hashlib, os, re, sys, time
import numpy as np
from scipy.signal import welch, coherence
from multiprocessing import Pool

SENTINEL = "ERRSPEC-T1T3-REV4-2026-09-04"
CELLS = ["rodent_max", "rodent_mod", "gt_max", "gt_mod", "fl_max", "fl_mod"]
SRCS = ["nam", "gtr2", "gtr4sg", "prvtgtr", "ytbass"]

def self_md5():
    with open(os.path.abspath(__file__), "rb") as f:
        return hashlib.md5(f.read()).hexdigest().upper()

def file_md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()

def parse_label(s):
    cell = next((c for c in CELLS if c in s), "")
    src = next((x for x in SRCS if re.search(r"(^|[_\-/\\])" + x + r"([_\-.]|$)", s)), "")
    m = re.search(r"_w(\d+)(?:[_.\-]|$)", s)
    w = int(m.group(1)) if m else -1
    return cell, src, w

def third_octave_edges(fmin=100.0, fmax=16000.0):
    edges = [fmin]
    while edges[-1] * 2 ** (1 / 3) <= fmax:
        edges.append(edges[-1] * 2 ** (1 / 3))
    return np.array(edges)

def band_energy(f, P, edges):
    out = np.zeros(len(edges) - 1)
    for i in range(len(edges) - 1):
        m = (f >= edges[i]) & (f < edges[i + 1])
        out[i] = P[m].sum() if m.any() else 0.0
    return out

def error_stats(y_w, y_ref, fs, nfft, skip):
    e = y_w[skip:].astype(np.float64) - y_ref[skip:].astype(np.float64)
    r = y_ref[skip:].astype(np.float64)
    f, Pe = welch(e, fs=fs, nperseg=nfft, window="hann")
    _, Pr = welch(r, fs=fs, nperseg=nfft, window="hann")
    band = (f >= 100) & (f <= 16000)
    fb, Peb, Prb = f[band], Pe[band] + 1e-30, Pr[band] + 1e-30
    sf = float(np.exp(np.mean(np.log(Peb))) / np.mean(Peb))
    fc, C = coherence(e, r, fs=fs, nperseg=nfft)
    coh = float(np.mean(C[(fc >= 100) & (fc <= 16000)]))
    lf = Peb[fb < 500].sum(); hf = Peb[fb > 5000].sum()
    tilt = float(10 * np.log10((lf + 1e-30) / (hf + 1e-30)))
    edges = third_octave_edges()
    Eb = band_energy(fb, Peb, edges); Rb = band_energy(fb, Prb, edges)
    valley = Rb < np.median(Rb)
    valley_frac = float(Eb[valley].sum() / (Eb.sum() + 1e-30))
    err_db = float(10 * np.log10(np.mean(e ** 2) + 1e-30) - 10 * np.log10(np.mean(r ** 2) + 1e-30))
    return dict(sf=sf, coh=coh, tilt_db=tilt, valley_frac=valley_frac, esr_int_db=err_db,
                n=len(e)), fb, 10 * np.log10(Peb), 10 * np.log10(Prb)

def load_f32(p):
    return np.fromfile(p, dtype="<f4")

def work(job):
    label, ref, test, fs, nfft, skip, meta = job
    t0 = time.time()
    try:
        r = load_f32(ref); y = load_f32(test)
        n = min(len(r), len(y)); trunc = int(len(r) != len(y))
        st, fb, pe, pr = error_stats(y[:n], r[:n], fs, nfft, skip)
        cell, src, w = parse_label(os.path.basename(test))
        if meta.get("cell"): cell = meta["cell"]
        if meta.get("src"): src = meta["src"]
        if meta.get("width") not in (None, ""): w = int(meta["width"])
        row = dict(label=label, cell=cell, src=src, width=w, **st, truncated=trunc,
                   pairs_file=meta.get("pairs_file", ""),
                   ref_len=len(r), test_len=len(y), test_md5=file_md5(test), ref_md5=file_md5(ref),
                   sec=round(time.time() - t0, 1), sentinel=SENTINEL, status="OK")
        return row, (label, fb, pe, pr)
    except Exception as ex:
        return dict(label=label, cell=meta.get("cell",""), src=meta.get("src",""),
                    width=meta.get("width",-1), pairs_file=meta.get("pairs_file",""),
                    status="FAIL:" + repr(ex), sentinel=SENTINEL), None

def resolve(path, roots):
    if os.path.exists(path):
        return path, None
    parts = re.split(r"[\\/]+", path)
    for comps in (parts[-2:], parts[-1:]):
        hits = []
        for root in roots:
            cand = os.path.join(root, *comps)
            if os.path.exists(cand):
                hits.append(cand)
        if len(hits) > 1:
            return None, f"AMBIGUOUS {'/'.join(comps)} in {hits}"
        if len(hits) == 1:
            return hits[0], None
    return path, None

def read_pairs(paths, subs, roots):
    jobs = []
    for p in paths:
        with open(p, newline="") as f:
            rd = csv.DictReader(f)
            cols = [c for c in rd.fieldnames]
            refc = next((c for c in cols if "ref" in c.lower()), None)
            tstc = next((c for c in cols if any(k in c.lower() for k in ("test", "deg", "out", "sub"))), None)
            if refc is None or tstc is None:
                sys.exit(f"FAIL pairs CSV {p}: cannot find ref/test columns in header {cols}")
            labc = next((c for c in cols if c.lower() in ("label", "name", "key")), None)
            n_before = len(jobs)
            for row in rd:
                ref, tst = row[refc], row[tstc]
                for old, new in subs:
                    ref = ref.replace(old, new); tst = tst.replace(old, new)
                ref, e1 = resolve(ref, roots); tst, e2 = resolve(tst, roots)
                if e1 or e2:
                    sys.exit("FAIL " + (e1 or e2))
                lab = row[labc] if labc else os.path.splitext(os.path.basename(tst))[0]
                meta = dict(cell=row.get("cell", ""), src=row.get("src", ""),
                            width=row.get("width", ""), pairs_file=os.path.basename(p))
                jobs.append((lab, ref, tst, meta))
            print(f"  {p}: loaded {len(jobs) - n_before} pairs (MD5 {file_md5(p)})")
            if len(jobs) == n_before:
                sys.exit(f"FAIL {p}: contributed zero pairs - schema or content problem")
    return jobs

def selftest(fs=48000, nfft=4096):
    rng = np.random.default_rng(1)
    t = np.arange(fs * 10) / fs
    r = 0.3 * np.sin(2 * np.pi * 220 * t) + 0.1 * np.sin(2 * np.pi * 1760 * t) + 0.02 * rng.standard_normal(len(t))
    r = r.astype(np.float32)
    white = (r + 0.01 * rng.standard_normal(len(t))).astype(np.float32)
    corr = (r * 1.05).astype(np.float32)
    s_w, *_ = error_stats(white, r, fs, nfft, 1024)
    s_c, *_ = error_stats(corr, r, fs, nfft, 1024)
    ok = s_w["sf"] > 0.8 and s_w["coh"] < 0.2 and s_c["sf"] < 0.3 and s_c["coh"] > 0.9 and s_w["valley_frac"] > s_c["valley_frac"]
    print(f"selftest white: sf={s_w['sf']:.3f} coh={s_w['coh']:.3f} valley={s_w['valley_frac']:.3f}")
    print(f"selftest corr : sf={s_c['sf']:.3f} coh={s_c['coh']:.3f} valley={s_c['valley_frac']:.3f}")
    print("selftest", "PASS" if ok else "FAIL")
    return ok

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", action="extend", nargs="+", default=[])
    ap.add_argument("--out", help="tidy CSV (fail-if-exists)")
    ap.add_argument("--psd-npz", help="NPZ of per-pair error/ref PSD in dB (fail-if-exists)")
    ap.add_argument("--fs", type=int, default=48000)
    ap.add_argument("--nfft", type=int, default=4096)
    ap.add_argument("--skip", type=int, default=1024)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--path-sub", action="append", default=[], help="OLD::NEW substring replace on every path")
    ap.add_argument("--resolve-root", action="append", default=[], help="directory to search for unresolved files (repeatable; parent-qualified first; ambiguity is fatal)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--allow-partial", action="store_true", help="skip the 510-grid coverage gate")
    a = ap.parse_args()
    print(f"{SENTINEL} self-MD5 {self_md5()}")
    if a.selftest:
        sys.exit(0 if selftest(a.fs, a.nfft) else 2)
    if not a.pairs or not a.out:
        sys.exit("need --pairs and --out")
    for p in (a.out, a.psd_npz):
        if p and os.path.exists(p):
            sys.exit(f"FAIL fail-if-exists: {p}")
    subs = [tuple(s.split("::", 1)) for s in a.path_sub]
    jobs = read_pairs(a.pairs, subs, a.resolve_root)
    missing = [j for j in jobs if not (os.path.exists(j[1]) and os.path.exists(j[2]))]
    if missing:
        for j in missing[:10]:
            print("MISSING", j)
        sys.exit(f"FAIL {len(missing)}/{len(jobs)} pairs have unreadable paths (first 10 shown); use --path-sub")
    print(f"{len(jobs)} pairs, {a.workers} workers")
    keys = [(j[3]["cell"], j[3]["src"], int(j[3]["width"])) for j in jobs if j[3]["cell"] and j[3]["src"] and j[3]["width"] != ""]
    grid = {(c, s, w) for c in CELLS for s in SRCS for w in range(8, 25)}
    if not a.allow_partial:
        if len(keys) != len(jobs):
            sys.exit(f"FAIL coverage: {len(jobs) - len(keys)} pairs lack cell/src/width columns; --allow-partial to bypass")
        dup = len(keys) - len(set(keys))
        if dup or set(keys) != grid or len(keys) != 510:
            sys.exit(f"FAIL coverage: {len(keys)} pairs, {dup} duplicates, missing {len(grid-set(keys))}, extra {len(set(keys)-grid)}")
        print("coverage gate PASS 510/510 before scoring")
    fields = ["label", "cell", "src", "width", "sf", "coh", "tilt_db", "valley_frac", "esr_int_db", "n",
              "truncated", "ref_len", "test_len", "test_md5", "ref_md5", "sec", "sentinel", "status", "pairs_file"]
    psd = {}
    rows = []
    with Pool(a.workers) as pool:
        for i, (row, p) in enumerate(pool.imap_unordered(work, [(j[0], j[1], j[2], a.fs, a.nfft, a.skip, j[3]) for j in jobs])):
            rows.append(row)
            if p is not None:
                psd[p[0]] = (p[1], p[2], p[3])
            if (i + 1) % 25 == 0:
                print(f"  {i+1}/{len(jobs)} done")
    bad = [r for r in rows if r["status"] != "OK"]
    if bad:
        for r in bad[:10]:
            print("  ", r["label"], r["status"])
        sys.exit(f"FAIL {len(bad)}/{len(rows)} pairs did not score; no CSV written")
    def sk(r):
        return (CELLS.index(r["cell"]) if r["cell"] in CELLS else 99,
                SRCS.index(r["src"]) if r["src"] in SRCS else 99, int(r["width"]))
    rows.sort(key=sk)
    with open(a.out, "x", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); wr.writeheader(); wr.writerows(rows)
    if a.psd_npz:
        fb = next(iter(psd.values()))[0]
        np.savez_compressed(a.psd_npz, f=fb, labels=np.array(list(psd.keys())),
                            err_db=np.array([v[1] for v in psd.values()]),
                            ref_db=np.array([v[2] for v in psd.values()]))
    print(f"wrote {a.out} bytes {os.path.getsize(a.out)} MD5 {file_md5(a.out)} rows {len(rows)}")
    if a.psd_npz:
        print(f"wrote {a.psd_npz} bytes {os.path.getsize(a.psd_npz)} MD5 {file_md5(a.psd_npz)}")

if __name__ == "__main__":
    main()
