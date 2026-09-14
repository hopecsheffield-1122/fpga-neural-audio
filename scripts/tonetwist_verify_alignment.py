#!/usr/bin/env python3
"""
tonetwist_verify_alignment.py
=============================
Verify sample-level clean<->wet alignment for ToneTwist AFx pairs using the
built-in synchronization markers (impulses at the start and end of every file).

ToneTwist's contribution spec requires wet files to be cropped to the exact
sample length of the dry inputs and synchronized via the markers, so this
script VERIFIES alignment rather than correcting it. Cross-correlation is the
fallback diagnostic only for pairs that fail.

Per pair it checks:
  1. Length      -- len(dry) == len(wet), exactly
  2. Start marker-- impulse peak index matches between dry and wet
  3. End marker  -- same at the end (confirms no dropped samples in between)
  4. Consistency -- start offset == end offset (a consistent nonzero offset is
                    a fixed latency you may shift out; inconsistent offsets
                    mean drift/data loss and the pair is BAD)

Also reports suggested interior trim points (past the markers + guard), i.e.
the region safe to use as training material.

USAGE
    python3 tonetwist_verify_alignment.py \
        --clean /path/to/dry \
        --wet   /path/to/Rodent \
        --out   ./alignment_report

Pairing logic (match_key) is identical to tonetwist_noise_floor.py.
"""

import argparse
import os
import sys
import csv
import re
from glob import glob
from collections import defaultdict

import numpy as np
import soundfile as sf


# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
MARKER_REGION_S = 2.0   # search window at each end of the file for the impulse
GUARD_S = 0.1           # extra guard past each marker when suggesting trims
TOL_SAMPLES = 0         # start/end offset tolerance for PASS (0 = exact)
JITTER_TOL = 2          # |start_off - end_off| <= this counts as consistent
                        # (peak-picking jitter on a smeared analog impulse)
PEAK_REL_HEIGHT = 0.3   # impulse candidates: peaks >= this fraction of window max
PEAK_MIN_DIST_S = 0.005 # minimum spacing between candidate impulses (5 ms)
GROUP_GAP_S = 0.10      # candidates closer than this belong to one marker event
ANCHOR_WIN_S = 0.05     # wet marker searched within +/- this of the dry anchor
TRIM_AFTER_S = 0.25     # content trim: this far past the last start-marker event
EPS = 1e-12


def match_key(path):
    """Same pairing as tonetwist_noise_floor.py (incl. double-dot fix)."""
    name = os.path.splitext(os.path.basename(path))[0].lower()
    parts = name.split(".")
    # drop role tags AND empty parts (double dots in filenames)
    parts = [p for p in parts if p and p not in ("input", "target")]
    if parts and re.match(r"^[a-z]\d+(_[a-z]\d+)+", parts[0]):
        parts = parts[1:]
    return ".".join(parts).strip(" _-")


def load_mono(path):
    x, sr = sf.read(path, always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return x.astype(np.float64), sr


def impulse_candidates(x, sr, region_s, from_end=False):
    """All impulse-like peaks in the search region: local maxima of |x| at or
    above PEAK_REL_HEIGHT of the region max, spaced >= PEAK_MIN_DIST_S apart.
    Returns list of (absolute_sample_index, amplitude), earliest first."""
    from scipy.signal import find_peaks
    region = min(len(x), max(1, int(sr * region_s)))
    seg = np.abs(x[-region:] if from_end else x[:region])
    base = len(x) - region if from_end else 0
    hmax = float(seg.max())
    if hmax <= EPS:
        return []
    dist = max(1, int(sr * PEAK_MIN_DIST_S))
    peaks, _ = find_peaks(seg, height=PEAK_REL_HEIGHT * hmax, distance=dist)
    return [(base + int(p), float(seg[p])) for p in peaks]


def group_first_peaks(cands, sr):
    """Cluster candidates into marker EVENTS (main peak + any ringing within
    GROUP_GAP_S); return the first peak (idx, amp) of each event."""
    if not cands:
        return []
    gap = int(sr * GROUP_GAP_S)
    firsts = [cands[0]]
    prev = cands[0][0]
    for idx, amp in cands[1:]:
        if idx - prev > gap:
            firsts.append((idx, amp))
        prev = idx
    return firsts


def dry_markers(x, sr, region_s):
    """Locate markers on the clean side (unambiguous 0.99 impulses).
    ToneTwist geometry: two impulses at the start (0.5 s, 1.5 s), marker(s)
    ~1.5 s before the end; content lies between the LAST start impulse and
    the FIRST end impulse.
    Returns (start_anchor, start_amp, last_start_event, end_anchor, end_amp)
    or None if either region has no impulse candidates."""
    sf_ = group_first_peaks(impulse_candidates(x, sr, region_s, False), sr)
    ef_ = group_first_peaks(impulse_candidates(x, sr, region_s, True), sr)
    if not sf_ or not ef_:
        return None
    return sf_[0][0], sf_[0][1], sf_[-1][0], ef_[0][0], ef_[0][1]


def wet_marker_near(x, sr, anchor):
    """Wet-side marker: FIRST impulse candidate within +/- ANCHOR_WIN_S of the
    dry anchor. The wet impulse response has a main peak followed by louder
    ringing ~15-35 ms later; anchoring + first-peak selection pins the same
    physical feature on both sides instead of whichever ring peak is tallest.
    Returns (index, amplitude)."""
    from scipy.signal import find_peaks
    win = int(sr * ANCHOR_WIN_S)
    lo, hi = max(0, anchor - win), min(len(x), anchor + win)
    seg = np.abs(x[lo:hi])
    hmax = float(seg.max())
    if hmax <= EPS:
        return -1, 0.0
    dist = max(1, int(sr * PEAK_MIN_DIST_S))
    peaks, _ = find_peaks(seg, height=PEAK_REL_HEIGHT * hmax, distance=dist)
    if len(peaks) == 0:
        p = int(np.argmax(seg))
        return lo + p, hmax
    return lo + int(peaks[0]), float(seg[peaks[0]])


def inspect_pair(cpath, wpath, region_s):
    """Dump the impulse-candidate structure of one pair so the marker
    geometry can be read directly off the data."""
    for label, path in (("DRY", cpath), ("WET", wpath)):
        x, sr = load_mono(path)
        print(f"\n{label}: {os.path.basename(path)}  "
              f"(len {len(x)} samples, {len(x)/sr:.2f} s, sr {sr})")
        for end, tag in ((False, f"first {region_s:.1f} s"),
                         (True, f"last {region_s:.1f} s")):
            cands = impulse_candidates(x, sr, region_s, from_end=end)
            print(f"  [{tag}] {len(cands)} candidate(s):")
            for i, (idx, amp) in enumerate(cands[:12]):
                t = idx / sr
                pos = f"{t:.4f} s" if not end else f"{t:.4f} s ({len(x)-idx} from end)"
                print(f"    #{i}: sample {idx:>10d}  ({pos})  amp {amp:.3f}")
            if len(cands) > 12:
                print(f"    ... {len(cands)-12} more")


def xcorr_lags(a, b, max_lag_s, sr, chunk_s=15.0, fracs=(0.25, 0.5, 0.75)):
    """Diagnostic: delay of b relative to a (positive = b late), measured on
    short content chunks at several positions through the file, via GCC-PHAT
    (phase-transform-whitened cross-correlation). PHAT gives a sharp peak at
    the true delay even on quasi-periodic musical content, where plain
    cross-correlation is ambiguous at multiples of the pitch period.
    Identical lags at all positions = constant offset; differing lags
    localize drift."""
    from scipy.fft import rfft, irfft, next_fast_len
    max_lag = int(sr * max_lag_s)
    n = min(len(a), len(b))
    chunk = min(max(1, n - 2 * max_lag - 1), int(sr * chunk_s))
    lags = []
    for frac in fracs:
        start = int((n - chunk) * frac)
        start = min(max(start, max_lag), max(0, n - chunk - max_lag))
        a_seg = a[start:start + chunk]
        b_seg = b[start:start + chunk]
        a_seg = a_seg - a_seg.mean()
        b_seg = b_seg - b_seg.mean()
        nfft = next_fast_len(chunk + 2 * max_lag)
        R = rfft(b_seg, nfft) * np.conj(rfft(a_seg, nfft))
        R /= (np.abs(R) + EPS)
        cc = irfft(R, nfft)
        cc = np.concatenate([cc[-max_lag:], cc[:max_lag + 1]])
        lags.append(int(np.argmax(cc) - max_lag))
    return lags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", required=True, help="dir of dry .wav files")
    ap.add_argument("--wet", required=True, help="dir of wet .wav files")
    ap.add_argument("--out", default="./alignment_report", help="output dir")
    ap.add_argument("--ext", default="wav", help="audio extension")
    ap.add_argument("--xcorr-on-fail", action="store_true",
                    help="run a cross-correlation diagnostic on failing pairs")
    ap.add_argument("--xcorr-all", action="store_true",
                    help="measure content lag (GCC-PHAT, 3 positions) on EVERY "
                         "pair and summarize per setting -- decides whether "
                         "trims should be offset-corrected or unshifted")
    ap.add_argument("--region", type=float, default=MARKER_REGION_S,
                    help="marker search window in seconds at each file end")
    ap.add_argument("--inspect", metavar="SUBSTR", default=None,
                    help="dump impulse-candidate structure for the first pair "
                         "whose wet filename contains SUBSTR (use '' for the "
                         "first pair), then exit")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    clean_files = sorted(glob(os.path.join(args.clean, f"**/*.{args.ext}"),
                              recursive=True))
    wet_files = sorted(glob(os.path.join(args.wet, f"**/*.{args.ext}"),
                            recursive=True))
    if not clean_files or not wet_files:
        sys.exit(f"No .{args.ext} files found. Check --clean / --wet paths.")

    wet_by_key = defaultdict(list)
    for w in wet_files:
        wet_by_key[match_key(w)].append(w)
    pairs = [(c, w)
             for c in clean_files
             for w in wet_by_key.get(match_key(c), [])]
    if not pairs:
        sys.exit("No pairs matched -- run tonetwist_noise_floor.py for the "
                 "key diagnostic dump.")

    if args.inspect is not None:
        sel = [(c, w) for c, w in pairs
               if args.inspect.lower() in os.path.basename(w).lower()]
        if not sel:
            sys.exit(f"--inspect: no wet filename contains {args.inspect!r}")
        inspect_pair(*sel[0], region_s=args.region)
        print("\n(inspect mode: no verification run)")
        return

    print(f"Verifying {len(pairs)} pairs "
          f"(of {len(clean_files)} clean, {len(wet_files)} wet)\n")

    rows, n_pass, n_latency, n_fail = [], 0, 0, 0
    setting_lags = {}
    # cache dry analyses; each dry file pairs with many wet files
    dry_cache = {}

    for cpath, wpath in pairs:
        if cpath not in dry_cache:
            xc, src = load_mono(cpath)
            dm = dry_markers(xc, src, args.region)
            dry_cache[cpath] = (xc, src, dm)
        xc, src, dm = dry_cache[cpath]
        xw, srw = load_mono(wpath)

        if dm is None:
            cs = ce = cs_last = -1
            ca = cea = 0.0
            ws, wa = -1, 0.0
            we, wea = -1, 0.0
        else:
            cs, ca, cs_last, ce, cea = dm
            ws, wa = wet_marker_near(xw, srw, cs)
            we, wea = wet_marker_near(xw, srw, ce)

        sr_ok = (src == srw)
        len_ok = (len(xc) == len(xw)) and sr_ok
        markers_ok = (dm is not None) and (ws >= 0) and (we >= 0)
        start_off = ws - cs
        end_off = we - ce
        jitter = end_off - start_off
        consistent = markers_ok and (abs(jitter) <= JITTER_TOL)

        # content region: past the LAST start-marker event (+ring), before the
        # end marker. Wet trims carry the measured offset, so slicing each side
        # at its own columns yields sample-ALIGNED, equal-length segments.
        # (Computed before the verdict so the tail-shortfall check can use it.)
        tf_c = (cs_last + int(src * TRIM_AFTER_S)) if markers_ok else -1
        tt_c = (ce - int(src * GUARD_S)) if markers_ok else -1

        # tail-shortfall tolerance: lengths differ, but the markers agree at
        # BOTH ends (so no samples were dropped inside the program material)
        # and the trim window fits inside both files -- the length difference
        # therefore lies entirely PAST the end marker's guard region, outside
        # every sample the pipeline uses. Verdict is annotated, not silent.
        tail_diff = len(xw) - len(xc)
        tail_ok = ((not len_ok) and sr_ok and consistent
                   and tf_c >= 0 and tt_c > tf_c
                   and tt_c <= len(xc)
                   and (tt_c + start_off) <= len(xw))

        if len_ok and consistent and start_off == 0 and jitter == 0:
            verdict = "PASS"
            n_pass += 1
        elif len_ok and consistent:
            verdict = f"LATENCY({start_off:+d})"   # fixed offset: shiftable
            if jitter:
                verdict += f"~j{jitter:+d}"        # within peak jitter tolerance
            n_latency += 1
        elif tail_ok:
            if start_off == 0 and jitter == 0:
                verdict = f"PASS~tail({tail_diff:+d})"
                n_pass += 1
            else:
                verdict = f"LATENCY({start_off:+d})~tail({tail_diff:+d})"
                if jitter:
                    verdict += f"~j{jitter:+d}"
                n_latency += 1
        else:
            verdict = "FAIL"
            n_fail += 1

        row = {
            "clean_file": os.path.basename(cpath),
            "wet_file": os.path.basename(wpath),
            "len_clean": len(xc),
            "len_wet": len(xw),
            "sr": src,
            "start_idx_clean": cs, "start_idx_wet": ws,
            "end_idx_clean": ce, "end_idx_wet": we,
            "start_offset": start_off,
            "end_offset": end_off,
            "start_peak_clean": round(ca, 4), "start_peak_wet": round(wa, 4),
            "end_peak_clean": round(cea, 4), "end_peak_wet": round(wea, 4),
            "trim_from_clean": tf_c, "trim_to_clean": tt_c,
            "trim_from_wet": (tf_c + start_off) if consistent else -1,
            "trim_to_wet": (tt_c + start_off) if consistent else -1,
            "verdict": verdict,
        }

        if args.xcorr_all or (verdict == "FAIL" and args.xcorr_on_fail):
            lags = xcorr_lags(xc, xw, 0.05, src)
            row["content_lag_25_50_75"] = "/".join(f"{l:+d}" for l in lags)
            setting = os.path.basename(wpath).split(".")[0].upper()
            setting_lags.setdefault(setting, []).extend(lags)

        rows.append(row)

        if verdict != "PASS":
            print(f"  {verdict:14s} {os.path.basename(wpath)}")
            print(f"    len {len(xc)} vs {len(xw)}   "
                  f"start {cs} vs {ws} ({start_off:+d})   "
                  f"end {ce} vs {we} ({end_off:+d})")
            if "content_lag_25_50_75" in row:
                print(f"    content xcorr lag at 25/50/75%: "
                      f"{row['content_lag_25_50_75']} samples")

    # ---- summary ----
    print("=" * 68)
    print(f"PASS: {n_pass}   fixed-LATENCY: {n_latency}   FAIL: {n_fail}   "
          f"(of {len(pairs)})")
    print("=" * 68)
    if n_pass == len(pairs):
        print("All pairs sample-aligned. No shifting needed; slice each side at")
        print("its trim_from/to columns and the interior is training-ready.")
    elif n_fail == 0:
        print("No drift/data loss. LATENCY pairs have a consistent fixed offset")
        print("(capture-chain latency). The trim_from/to columns are already")
        print("offset-corrected per side: slice clean at its columns and wet at")
        print("its columns and the segments come out sample-aligned.")
    else:
        print("FAIL pairs have inconsistent start/end offsets -> possible")
        print("dropped samples or bad markers. Inspect before training;")
        print("re-run with --xcorr-on-fail for a lag diagnostic.")

    # marker sanity note
    missing = [r for r in rows if -1 in (r["start_idx_clean"],
                                         r["start_idx_wet"],
                                         r["end_idx_clean"],
                                         r["end_idx_wet"])]
    if missing:
        print(f"\nNote: {len(missing)} pair(s) had NO impulse candidate in a "
              "search region (silent window);")
        print("widen --region, or run --inspect '' to see the actual marker "
              "geometry.")
    weak = [r for r in rows
            if min(r["start_peak_clean"], r["end_peak_clean"]) < 0.1]
    if weak:
        print(f"\nNote: {len(weak)} pair(s) have a weak dry marker peak (<0.1);")
        print("the 'marker' found may not be the impulse -- check with "
              "--inspect.")

    if setting_lags:
        print("\n" + "-" * 68)
        print("CONTENT LAG vs MARKER OFFSET per setting "
              "(median over probes / pairs)")
        print("-" * 68)
        moff = {}
        for r in rows:
            s = r["wet_file"].split(".")[0].upper()
            moff.setdefault(s, []).append(r["start_offset"])
        for s in sorted(setting_lags):
            cl = int(np.median(setting_lags[s]))
            mo = int(np.median(moff[s]))
            print(f"  {s:26s} content lag {cl:+4d}   marker offset {mo:+4d}")
        print("If content lags are ~0 while marker offsets are not, the offset")
        print("is the pedal filter's group-delay PEAK shift, not transport")
        print("delay: align content UNSHIFTED (ignore trim_from/to_wet's")
        print("offset; use the clean columns for both sides).")

    csv_path = os.path.join(args.out, "alignment_report.csv")
    fieldnames = list(rows[0].keys())
    for r in rows:                      # FAIL rows carry extra diagnostic cols
        for k in r:
            if k not in fieldnames:
                fieldnames.append(k)
    with open(csv_path, "w", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=fieldnames, restval="")
        wtr.writeheader()
        wtr.writerows(rows)
    print(f"\nWrote: {csv_path}")


if __name__ == "__main__":
    main()
