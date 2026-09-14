#!/usr/bin/env python
"""hls_metrics.py - score HLS file-mode outputs (raw float32 files). v4
Sentinel: HLSMETRICS-V4-REV1

Modes:
  --ref     : compare two raw f32 files with the SAME math as the HLS TB
              (cosine, plain ESR dB, RMSE, NRMSE, mean error). For the
              golden cross-check and for HLS<->HLS / float<->HLS pairs.
  --target  : target-referenced scoring; adds MR-STFT imported from
              eval_diag (batched-2D adapter; failure is non-fatal and can
              never suppress the windowed report). Use --skip 1024.
  --window-sec S : per-window ESR + mean-err table after --skip (drift /
              localization instrument; prints even if MR-STFT fails).
  --lag-check    : xcorr lag + peak correlation on 1M-sample slices.
  --csv     : append 'label,esr_db,mrstft' row (matches per_source_metrics.csv).
              SCHEMA UNCHANGED from v3.

v4 additions (C4 descriptor extension; all non-fatal, all additive):
  --c4          : print C4 descriptor block (MSE/MAE, envelope corr + env-ESR,
                  LUFS ref/out/delta [BS.1770-4 integrated, K-weighted, gated],
                  spectral flux ref/out/delta%, crest factor ref/out/delta,
                  drift slope from the windowed rows).
  --desc-csv P  : append full descriptor row to a SEPARATE csv P (own header,
                  22 columns). Implies --c4. If --window-sec is not given,
                  defaults to 30 so drift columns populate.
  --selftest    : run internal validation (sine crest exact 3.01 dB, K-filter
                  997 Hz gain ~0 dB, LUFS of -20 dBFS 997 Hz sine, flat-env and
                  near-zero-flux sanity on stationary sine) and exit.

v3 code paths are untouched: --ref/--target/--csv output is digit-identical
to v3 (reproduction gate: rerun a known row, digits must match).

LUFS note: BS.1770 coefficient set for 48 kHz hardcoded below; validate
against a reference meter before citing absolute LUFS (Thursday dry-run).
Deltas (out minus ref) are robust even if absolute calibration is off.
"""

import argparse
import os
import sys
import numpy as np

SAMPLE_RATE = 48000  # all project material is 48 kHz

MRSTFT_FN = None
try:
    from eval_diag import mr_stft as MRSTFT_FN
except Exception:
    MRSTFT_FN = None

# BS.1770-4 K-weighting, 48 kHz coefficient set (stage 1 shelf, stage 2 RLB HP)
K_SHELF_B = [1.53512485958697, -2.69169618940638, 1.19839281085285]
K_SHELF_A = [1.0, -1.69065929318241, 0.73248077421585]
K_HP_B = [1.0, -2.0, 1.0]
K_HP_A = [1.0, -1.99004745483398, 0.99007225036621]


def read_f32(path):
    a = np.fromfile(path, dtype=np.float32)
    if a.size == 0:
        sys.exit(f"FATAL: {path} is empty or unreadable")
    return a.astype(np.float64)


def basic_metrics(ref, out):
    dot = float(np.dot(ref, out))
    na = float(np.dot(ref, ref))
    nb = float(np.dot(out, out))
    err = out - ref
    sum_sq_err = float(np.dot(err, err))
    cosine = dot / (np.sqrt(na) * np.sqrt(nb) + 1e-30)
    esr_db = 10.0 * np.log10(sum_sq_err / (na + 1e-30) + 1e-30)
    n = ref.size
    rmse = np.sqrt(sum_sq_err / n)
    nrmse = rmse / (np.sqrt(na / n) + 1e-30)
    mean_err = float(np.mean(err))
    i = int(np.argmax(np.abs(err)))
    return dict(cosine=cosine, esr_db=esr_db, rmse=rmse, nrmse=nrmse,
                mean_err=mean_err, max_err=float(abs(err[i])), max_err_idx=i)


def windowed_report(ref, out, win_sec, skip_offset):
    """v3-identical printed output; v4 additionally RETURNS the row list
    (k, esr_db, mean_err, cosine, t0_sec) for the drift columns."""
    w = int(win_sec * SAMPLE_RATE)
    nwin = ref.size // w
    if nwin < 2:
        print(f"window report   : skipped (only {nwin} full "
              f"{win_sec:g}s window(s))")
        return []
    print(f"---- windowed ({win_sec:g}s x {nwin} windows) ----")
    print(f"{'win':>4s} {'t-start':>9s} {'cosine':>8s} {'ESR dB':>8s} {'mean err':>12s}")
    rows = []
    for k in range(nwin):
        r = ref[k * w:(k + 1) * w]
        o = out[k * w:(k + 1) * w]
        m = basic_metrics(r, o)
        t0 = (skip_offset + k * w) / SAMPLE_RATE
        rows.append((k, m['esr_db'], m['mean_err'], m['cosine'], t0))
        print(f"{k:>4d} {t0:>8.1f}s {m['cosine']:>8.4f} {m['esr_db']:>8.2f} {m['mean_err']:>12.4e}")
    worst = max(rows, key=lambda r: r[1])
    best = min(rows, key=lambda r: r[1])
    print(f"best window     : #{best[0]} at ESR {best[1]:.2f} dB")
    print(f"worst window    : #{worst[0]} at ESR {worst[1]:.2f} dB")
    print(f"drift check     : mean err first {rows[0][2]:.4e} -> "
          f"last {rows[-1][2]:.4e}")
    return rows


def lag_check(ref, out, skip_offset):
    """xcorr lag at early/middle/late 1M-sample slices, search +/-4096."""
    try:
        from scipy.signal import correlate
    except Exception as e:
        print(f"lag check       : SKIPPED (scipy import failed: {e})")
        return
    n = ref.size
    L = min(1 << 20, n // 4)
    MAXLAG = 4096
    positions = [("early", L), ("middle", n // 2), ("late", n - 2 * L)]
    print("---- lag check (xcorr on 1M-sample slices, search +/-4096) ----")
    for name, c in positions:
        a = ref[c:c + L]
        b = out[c - MAXLAG:c + L + MAXLAG]
        if a.size < L or b.size < L + 2 * MAXLAG:
            print(f"{name:>7s}: slice out of range, skipped")
            continue
        xc = correlate(b, a, mode="valid", method="fft")
        k = int(np.argmax(np.abs(xc)))
        lag = k - MAXLAG  # >0: out is DELAYED relative to ref
        aa = a - a.mean()
        bb = b[k:k + L] - b[k:k + L].mean()
        denom = (np.linalg.norm(aa) * np.linalg.norm(bb) + 1e-30)
        pk = float(np.dot(aa, bb) / denom)
        t0 = (skip_offset + c) / SAMPLE_RATE
        print(f"{name:>7s} (t={t0:7.1f}s): lag {lag:+d} samples, peak corr {pk:.4f}")
    print("(healthy: lag 0 at all three, peak corr ~ aggregate cosine;")
    print(" constant nonzero lag = static desync; growing lag = accumulating desync)")


def call_mrstft(ref, out):
    """eval_diag's _stft_mag expects batched (N, T); adapt, torch fallback."""
    r2 = ref.astype(np.float32).reshape(1, -1)
    o2 = out.astype(np.float32).reshape(1, -1)
    try:
        return float(MRSTFT_FN(r2, o2))
    except Exception:
        import torch
        tr = torch.from_numpy(np.ascontiguousarray(r2))
        to = torch.from_numpy(np.ascontiguousarray(o2))
        with torch.no_grad():
            v = MRSTFT_FN(tr, to)
        return float(v)


# ======================= v4: C4 descriptor block =======================

def frame_rms_envelope(x, win=2048, hop=1024):
    """Per-frame RMS envelope via cumulative sums (O(n), no big copies)."""
    if x.size < win:
        return None
    cs = np.concatenate(([0.0], np.cumsum(x * x)))
    starts = np.arange(0, x.size - win + 1, hop)
    return np.sqrt((cs[starts + win] - cs[starts]) / win)


def envelope_metrics(ref, out, win=2048, hop=1024):
    er = frame_rms_envelope(ref, win, hop)
    eo = frame_rms_envelope(out, win, hop)
    if er is None or eo is None:
        return None, None
    n = min(er.size, eo.size)
    er, eo = er[:n], eo[:n]
    a = er - er.mean()
    b = eo - eo.mean()
    corr = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-30))
    env_esr_db = float(10.0 * np.log10(
        np.dot(eo - er, eo - er) / (np.dot(er, er) + 1e-30) + 1e-30))
    return corr, env_esr_db


def lufs_integrated(x):
    """BS.1770-4 integrated loudness, mono, 48 kHz: K-weighting, 400 ms
    blocks / 100 ms hop, -70 LUFS absolute gate, -10 relative gate."""
    from scipy.signal import lfilter
    y = lfilter(K_SHELF_B, K_SHELF_A, x)
    y = lfilter(K_HP_B, K_HP_A, y)
    blk = int(0.400 * SAMPLE_RATE)
    hop = int(0.100 * SAMPLE_RATE)
    if y.size < blk:
        return None
    cs = np.concatenate(([0.0], np.cumsum(y * y)))
    starts = np.arange(0, y.size - blk + 1, hop)
    ms = (cs[starts + blk] - cs[starts]) / blk
    lb = -0.691 + 10.0 * np.log10(ms + 1e-30)
    mask = lb > -70.0
    if not mask.any():
        return None
    rel_gate = (-0.691 + 10.0 * np.log10(ms[mask].mean() + 1e-30)) - 10.0
    mask2 = mask & (lb > rel_gate)
    if not mask2.any():
        return None
    return float(-0.691 + 10.0 * np.log10(ms[mask2].mean() + 1e-30))


def spectral_flux(x, win=2048, hop=1024, chunk_frames=4096):
    """Mean normalized positive spectral flux, chunked to bound memory."""
    n = x.size
    nf = 1 + (n - win) // hop
    if nf < 3:
        return None
    w = np.hanning(win).astype(np.float32)
    prev = None
    total, cnt = 0.0, 0
    for f0 in range(0, nf, chunk_frames):
        f1 = min(f0 + chunk_frames, nf)
        idx = (f0 * hop
               + (np.arange(f1 - f0) * hop)[:, None]
               + np.arange(win)[None, :])
        frames = x[idx].astype(np.float32) * w
        mag = np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32)
        if prev is not None:
            mags = np.vstack([prev[None, :], mag])
        else:
            mags = mag
        d = mags[1:] - mags[:-1]
        pos = np.maximum(d, 0.0).sum(axis=1)
        norm = mags[:-1].sum(axis=1) + 1e-12
        total += float((pos / norm).sum())
        cnt += int(pos.shape[0])
        prev = mag[-1]
    return total / max(cnt, 1)


def crest_db(x):
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(x * x)))
    return 20.0 * np.log10(peak / (rms + 1e-30) + 1e-30)


def drift_columns(win_rows):
    """From windowed_report rows -> (best_esr, worst_esr, meanerr_first,
    meanerr_last, slope_per_min, nwin). Blank-safe when <2 windows."""
    if not win_rows or len(win_rows) < 2:
        return ("", "", "", "", "", len(win_rows) if win_rows else 0)
    esrs = [r[1] for r in win_rows]
    merrs = np.array([r[2] for r in win_rows])
    t_min = np.array([r[4] for r in win_rows]) / 60.0
    slope = float(np.polyfit(t_min, merrs, 1)[0])
    return (f"{min(esrs):.2f}", f"{max(esrs):.2f}",
            f"{merrs[0]:.4e}", f"{merrs[-1]:.4e}",
            f"{slope:.4e}", len(win_rows))


DESC_HEADER = ("label,esr_db,mrstft,mse,mae,env_corr,env_esr_db,"
               "lufs_ref,lufs_out,lufs_delta_db,flux_ref,flux_out,"
               "flux_delta_pct,crest_ref_db,crest_out_db,crest_delta_db,"
               "win_best_esr_db,win_worst_esr_db,meanerr_first,meanerr_last,"
               "meanerr_slope_per_min,nwin")


def c4_block(ref, out, win_rows):
    """Compute + print C4 descriptors; every piece individually non-fatal.
    Returns dict of csv-ready strings."""
    d = {k: "" for k in ("mse", "mae", "env_corr", "env_esr_db",
                         "lufs_ref", "lufs_out", "lufs_delta_db",
                         "flux_ref", "flux_out", "flux_delta_pct",
                         "crest_ref_db", "crest_out_db", "crest_delta_db")}
    print("---- C4 descriptors ----")
    try:
        err = out - ref
        mse = float(np.mean(err * err))
        mae = float(np.mean(np.abs(err)))
        d["mse"], d["mae"] = f"{mse:.6e}", f"{mae:.6e}"
        print(f"MSE               : {mse:.6e}")
        print(f"MAE               : {mae:.6e}")
    except Exception as e:
        print(f"MSE/MAE           : FAILED non-fatally ({type(e).__name__}: {e})")
    try:
        corr, env_esr = envelope_metrics(ref, out)
        if corr is not None:
            d["env_corr"], d["env_esr_db"] = f"{corr:.6f}", f"{env_esr:.2f}"
            print(f"envelope corr     : {corr:.6f}")
            print(f"envelope ESR      : {env_esr:.2f} dB")
        else:
            print("envelope          : skipped (signal shorter than one frame)")
    except Exception as e:
        print(f"envelope          : FAILED non-fatally ({type(e).__name__}: {e})")
    try:
        lr = lufs_integrated(ref)
        lo = lufs_integrated(out)
        if lr is not None and lo is not None:
            d["lufs_ref"], d["lufs_out"] = f"{lr:.2f}", f"{lo:.2f}"
            d["lufs_delta_db"] = f"{lo - lr:+.2f}"
            print(f"LUFS ref/out      : {lr:.2f} / {lo:.2f}  (delta {lo - lr:+.2f})")
        else:
            print("LUFS              : skipped (all blocks below absolute gate)")
    except Exception as e:
        print(f"LUFS              : FAILED non-fatally ({type(e).__name__}: {e})")
    try:
        fr = spectral_flux(ref)
        fo = spectral_flux(out)
        if fr is not None and fo is not None:
            dpct = 100.0 * (fo - fr) / (fr + 1e-30)
            d["flux_ref"], d["flux_out"] = f"{fr:.5f}", f"{fo:.5f}"
            d["flux_delta_pct"] = f"{dpct:+.2f}"
            print(f"spectral flux r/o : {fr:.5f} / {fo:.5f}  (delta {dpct:+.2f}%)")
        else:
            print("spectral flux     : skipped (too few frames)")
    except Exception as e:
        print(f"spectral flux     : FAILED non-fatally ({type(e).__name__}: {e})")
    try:
        cr, co = crest_db(ref), crest_db(out)
        d["crest_ref_db"], d["crest_out_db"] = f"{cr:.2f}", f"{co:.2f}"
        d["crest_delta_db"] = f"{co - cr:+.2f}"
        print(f"crest ref/out     : {cr:.2f} / {co:.2f} dB  (delta {co - cr:+.2f})")
    except Exception as e:
        print(f"crest             : FAILED non-fatally ({type(e).__name__}: {e})")
    try:
        bc = drift_columns(win_rows)
        if bc[5] and bc[5] >= 2:
            print(f"drift slope       : {bc[4]} mean-err/min over {bc[5]} windows")
        else:
            print("drift slope       : skipped (<2 windows; pass --window-sec)")
    except Exception as e:
        print(f"drift slope       : FAILED non-fatally ({type(e).__name__}: {e})")
    return d


def write_desc_csv(path, label, esr_db, mrstft_val, d, win_rows):
    bc = drift_columns(win_rows)
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write(DESC_HEADER + "\n")
        row = [label, f"{esr_db:.2f}", str(mrstft_val),
               d["mse"], d["mae"], d["env_corr"], d["env_esr_db"],
               d["lufs_ref"], d["lufs_out"], d["lufs_delta_db"],
               d["flux_ref"], d["flux_out"], d["flux_delta_pct"],
               d["crest_ref_db"], d["crest_out_db"], d["crest_delta_db"],
               bc[0], bc[1], bc[2], bc[3], bc[4], str(bc[5])]
        f.write(",".join(row) + "\n")
    print(f"appended descriptor row '{label}' -> {path}")


# ============================ v4: selftest =============================

def selftest():
    """Internal validation. Exact anchors where math permits; LUFS absolute
    value FLAGGED pending reference-meter validation (Thursday dry-run)."""
    print("HLSMETRICS-V4-REV1 selftest")
    ok = True

    t = np.arange(10 * SAMPLE_RATE, dtype=np.float64) / SAMPLE_RATE
    sine = 0.1 * np.sin(2 * np.pi * 997.0 * t)

    c = crest_db(sine)
    p = abs(c - 3.0103) <= 0.05
    ok &= p
    print(f"[{'PASS' if p else 'FAIL'}] sine crest factor : {c:.4f} dB "
          f"(exact 3.0103 +/- 0.05)")

    try:
        from scipy.signal import freqz
        w1, h1 = freqz(K_SHELF_B, K_SHELF_A,
                       worN=[2 * np.pi * 997.0 / SAMPLE_RATE])
        w2, h2 = freqz(K_HP_B, K_HP_A,
                       worN=[2 * np.pi * 997.0 / SAMPLE_RATE])
        g = 20.0 * np.log10(abs(h1[0] * h2[0]))
        # +0.691 dB at 997 Hz is the standard's design value; the -0.691
        # offset in the loudness formula exists to cancel exactly this.
        p = abs(g - 0.691) <= 0.05
        ok &= p
        print(f"[{'PASS' if p else 'FAIL'}] K-filter @997 Hz  : {g:+.4f} dB "
              f"(expect +0.691 +/- 0.05; cancelled by the -0.691 offset)")
    except Exception as e:
        ok = False
        print(f"[FAIL] K-filter freqz    : {type(e).__name__}: {e}")

    try:
        l = lufs_integrated(sine)
        # BS.1770 calibration anchor: a 997 Hz sine reads its RMS dBFS as
        # LUFS (K-gain +0.691 cancelled by the -0.691 offset).
        # -20 dBFS sine -> RMS -23.01 dBFS -> expect -23.01 LUFS.
        expect = -23.01
        p = l is not None and abs(l - expect) <= 0.10
        ok &= p
        print(f"[{'PASS' if p else 'FAIL'}] LUFS -20dBFS sine : "
              f"{l if l is not None else 'None':.2f} "
              f"(expect {expect} +/- 0.10, the standard's 997 Hz anchor)")
    except Exception as e:
        ok = False
        print(f"[FAIL] LUFS              : {type(e).__name__}: {e}")

    env = frame_rms_envelope(sine)
    p = env is not None and (env.std() / env.mean()) < 0.01
    ok &= p
    print(f"[{'PASS' if p else 'FAIL'}] flat sine envelope: "
          f"std/mean {env.std() / env.mean():.5f} (< 0.01)")

    fx = spectral_flux(sine)
    p = fx is not None and fx < 0.01
    ok &= p
    print(f"[{'PASS' if p else 'FAIL'}] stationary flux   : {fx:.6f} (< 0.01)")

    print(f"selftest result   : {'ALL PASS' if ok else 'FAILURES PRESENT'}")
    sys.exit(0 if ok else 1)


# ================================ main =================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hls", help="HLS/model output (.f32)")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--ref", help="reference .f32/.bin (golden / HLS<->HLS / float<->HLS)")
    grp.add_argument("--target", help="wet target .f32 (target-referenced mode)")
    ap.add_argument("--skip", type=int, default=0)
    ap.add_argument("--window-sec", type=float, default=None)
    ap.add_argument("--lag-check", action="store_true")
    ap.add_argument("--label", default=None)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--c4", action="store_true",
                    help="print C4 descriptor block")
    ap.add_argument("--desc-csv", default=None,
                    help="append descriptor row to separate csv (implies --c4)")
    ap.add_argument("--selftest", action="store_true",
                    help="run internal validation and exit")
    args = ap.parse_args()

    if args.selftest:
        selftest()

    if not args.hls or not (args.ref or args.target):
        ap.error("--hls and one of --ref/--target are required "
                 "(unless --selftest)")

    if args.desc_csv:
        args.c4 = True
        if args.window_sec is None:
            args.window_sec = 30.0

    hls = read_f32(args.hls)
    ref_path = args.ref if args.ref else args.target
    ref = read_f32(ref_path)

    if hls.size != ref.size:
        sys.exit(f"FATAL: length mismatch: {args.hls} has {hls.size}, "
                 f"{ref_path} has {ref.size}")

    if args.skip > 0:
        hls = hls[args.skip:]
        ref = ref[args.skip:]

    m = basic_metrics(ref, hls)
    print(f"scored samples    : {ref.size} (skip={args.skip})")
    print(f"cosine similarity : {m['cosine']:.6f}")
    print(f"ESR               : {m['esr_db']:.2f} dB")
    print(f"max abs error     : {m['max_err']:.6e} at sample {m['max_err_idx'] + args.skip}")
    print(f"RMSE              : {m['rmse']:.6e}")
    print(f"normalized RMSE   : {m['nrmse']:.6e}")
    print(f"mean error        : {m['mean_err']:.6e}")

    win_rows = []
    if args.window_sec:
        win_rows = windowed_report(ref, hls, args.window_sec, args.skip)

    if args.lag_check:
        lag_check(ref, hls, args.skip)

    desc = None
    if args.c4:
        desc = c4_block(ref, hls, win_rows)

    mrstft_val = ""
    if args.target:
        if MRSTFT_FN is None:
            print("MR-STFT           : SKIPPED (eval_diag import failed)")
        else:
            try:
                mrstft_val = call_mrstft(ref, hls)
                print(f"MR-STFT           : {mrstft_val:.3f}")
            except Exception as e:
                print(f"MR-STFT           : FAILED non-fatally ({type(e).__name__}: {e})")
                mrstft_val = ""

    if args.csv:
        label = args.label or os.path.basename(args.hls)
        new = not os.path.exists(args.csv)
        with open(args.csv, "a", encoding="utf-8") as f:
            if new:
                f.write("label,esr_db,mrstft\n")
            f.write(f"{label},{m['esr_db']:.2f},{mrstft_val}\n")
        print(f"appended row '{label}' -> {args.csv}")

    if args.desc_csv:
        label = args.label or os.path.basename(args.hls)
        write_desc_csv(args.desc_csv, label, m['esr_db'], mrstft_val,
                       desc, win_rows)


if __name__ == "__main__":
    main()
