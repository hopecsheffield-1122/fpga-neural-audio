#!/usr/bin/env python
r"""
gtr2_characterize.py — characterization of the gtr2 D050 time-base-wander
exclusion (Rodent / ToneTwist AFx).

Produces one multi-panel figure + CSVs + a text report:

  Panel 1  Lag-vs-position profiles. Independently re-derived here with TWO
           estimators (plain normalized xcorr + GCC-PHAT), overlaid with the
           saved dense-probe CSV from tonetwist_verify_alignment.py. The fresh
           derivation is MARKER-FREE (base alignment from one global content
           cross-correlation), so agreement across all three rules out both
           marker-detection and probe-code defects.
  Panel 2  Residual wander after best constant and best linear (drift)
           detrend, per capture — shows no static/linear correction fixes it.
  Panel 3  Metric-specificity (optional, from --metrics-csv): per-source ESR
           vs MR-STFT with the subject highlighted.
  Panel 4  Synthetic wander injection (optional, --inject-audio): applies the
           MEASURED gtr2 lag trajectory to a clean capture via windowed-sinc
           fractional delay; reports the ESR floor wander alone imposes, the
           ESR after the best static shift (wander survives it), and the
           MR-STFT (which barely moves) — causal closure of the
           metric-specific-floor claim. A constant-delay calibration control
           reports the interpolation machinery's own floor for honesty.

Conventions: positive lag = wet later than dry. Plain (un-pre-emphasized) ESR,
reported in dB. MR-STFT = spectral convergence + log-magnitude L1 over FFT
sizes {512, 1024, 2048}, hop = FFT/4, Hann — cross-check against eval_diag.py
on one pair before quoting numbers side by side.

Example (Windows, conda base):

  python gtr2_characterize.py ^
    --pair gtr2_D050  "...\dry\gtr2.wav"  "...\V100_F050_D050_M000\gtr2.wav" ^
    --pair gtr2_F000  "...\dry\gtr2.wav"  "...\V100_F000_D050_M000\gtr2.wav" ^
    --pair nam_D050   "...\dry\nam.wav"   "...\V100_F050_D050_M000\nam.wav" ^
    --probe-csv alignment_probes.csv gtr2_D050 ^
    --marker-offsets 13 18 ^
    --metrics-csv per_source_metrics.csv ^
    --inject-audio "...\V100_F050_D050_M000\nam.wav" ^
    --out gtr2_char

The FIRST --pair is the subject (highlighted); the rest are controls. Use both
control directions: same dry at another setting (isolates the wet capture) and
another source at the same setting (isolates the dry).

metrics CSV format (hand-fed from the workbook / eval_diag output):
  label,esr_db,mrstft
  gtr2,-7.1,4.39
  nam,-16.2,5.41
  ...
"""

import argparse
import sys
from pathlib import Path

import numpy as np

try:
    import soundfile as sf
except ImportError:
    sys.exit("needs soundfile:  pip install soundfile")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

EPS = 1e-12


# ----------------------------------------------------------------- audio io

def load_audio(path):
    x, sr = sf.read(str(path), always_2d=True)
    return x.mean(axis=1).astype(np.float64), sr


def rms_db(x):
    return 10.0 * np.log10(np.mean(x * x) + EPS)


# ------------------------------------------------------- lag estimation core

def parabolic_offset(y_m1, y_0, y_p1):
    denom = (y_m1 - 2.0 * y_0 + y_p1)
    if abs(denom) < EPS:
        return 0.0
    off = 0.5 * (y_m1 - y_p1) / denom
    return float(np.clip(off, -1.0, 1.0))


def global_base_lag(dry, wet, sr, probe_dur=20.0, search_s=0.05, skip_s=3.0):
    """Marker-free base alignment: pick the highest-energy probe_dur chunk of
    the dry (skipping the marker region at the ends), cross-correlate against
    the wet in a +/- search_s window. Returns integer base lag (wet - dry)."""
    from scipy.signal import fftconvolve

    W = int(probe_dur * sr)
    skip = int(skip_s * sr)
    search = int(search_s * sr)
    n = len(dry)
    if n < W + 2 * skip:
        skip = 0
        W = min(W, n)
    # candidate starts, strided; choose max-RMS chunk
    starts = np.arange(skip, n - W - skip, max(1, W // 2))
    if len(starts) == 0:
        starts = np.array([0])
    rms = [np.sqrt(np.mean(dry[s:s + W] ** 2)) for s in starts]
    s0 = int(starts[int(np.argmax(rms))])

    d = dry[s0:s0 + W]
    lo = max(0, s0 - search)
    hi = min(len(wet), s0 + W + search)
    w = wet[lo:hi]
    if len(w) <= len(d):
        return 0, s0
    r = fftconvolve(w, d[::-1], mode="valid")  # r[k] = sum d[n] * w[n+k]
    k = int(np.argmax(r))
    base = (lo - s0) + k  # positive = wet later
    return base, s0


def sliding_norms(w, W):
    c = np.concatenate(([0.0], np.cumsum(w * w)))
    return np.sqrt(np.maximum(c[W:] - c[:-W], EPS))


def window_lags(dry, wet, sr, base, win_s=1.0, hop_s=2.0, search=64,
                gate_dbfs=-45.0, min_corr=0.0, phat_band=(60.0, 8000.0)):
    """Per-window lag via plain normalized xcorr AND GCC-PHAT.
    Returns dict of arrays: t, lag_xc, lag_ph, corr, dry_rms_db."""
    from scipy.signal import fftconvolve

    W = int(win_s * sr)
    H = int(hop_s * sr)
    n = len(dry)
    out = {k: [] for k in ("t", "lag_xc", "lag_ph", "corr", "rms")}

    L = 1
    while L < W + 2 * search:
        L <<= 1

    for t0 in range(0, n - W, H):
        d = dry[t0:t0 + W]
        r_db = rms_db(d)
        if r_db < gate_dbfs:
            continue
        wlo = t0 + base - search
        whi = t0 + base + W + search
        if wlo < 0 or whi > len(wet):
            continue
        w = wet[wlo:whi]

        # --- plain normalized cross-correlation ---
        r = fftconvolve(w, d[::-1], mode="valid")  # length 2*search+1
        norms = sliding_norms(w, W)
        rn = r / (np.linalg.norm(d) * norms + EPS)
        k = int(np.argmax(rn))
        off = parabolic_offset(*rn[max(k - 1, 0):k + 2]) if 0 < k < len(rn) - 1 else 0.0
        lag_xc = base + (k - search) + off
        corr = float(rn[k])
        if corr < min_corr:
            continue

        # --- GCC-PHAT (band-limited: only bins with plausible coherence) ---
        D = np.fft.rfft(d, L)
        Wf = np.fft.rfft(w, L)
        R = Wf * np.conj(D)
        R /= (np.abs(R) + EPS)
        freqs = np.fft.rfftfreq(L, 1.0 / sr)
        R[(freqs < phat_band[0]) | (freqs > phat_band[1])] = 0.0
        cc = np.fft.irfft(R, L)[: 2 * search + 1]
        kp = int(np.argmax(cc))
        offp = parabolic_offset(*cc[max(kp - 1, 0):kp + 2]) if 0 < kp < len(cc) - 1 else 0.0
        lag_ph = base + (kp - search) + offp

        out["t"].append((t0 + W / 2) / sr)
        out["lag_xc"].append(lag_xc)
        out["lag_ph"].append(lag_ph)
        out["corr"].append(corr)
        out["rms"].append(r_db)

    return {k: np.asarray(v) for k, v in out.items()}


def detrend_stats(t, lags):
    """Peak-to-peak / RMS residual after constant and linear detrend."""
    if len(lags) < 3:
        return None
    res_c = lags - np.mean(lags)
    p = np.polyfit(t, lags, 1)
    res_l = lags - np.polyval(p, t)
    return {
        "pp_raw": float(np.ptp(lags)),
        "pp_const": float(np.ptp(res_c)),
        "pp_lin": float(np.ptp(res_l)),
        "rms_lin": float(np.sqrt(np.mean(res_l ** 2))),
        "slope_per_min": float(p[0] * 60.0),
    }


# ------------------------------------------------------------------- metrics

def esr_db(y, yhat):
    e = np.sum((y - yhat) ** 2) / (np.sum(y ** 2) + EPS)
    return 10.0 * np.log10(e + EPS)


def mrstft(y, yhat, ffts=(512, 1024, 2048)):
    total = 0.0
    for nfft in ffts:
        hop = nfft // 4
        win = np.hanning(nfft)
        def spec(x):
            nfrm = 1 + (len(x) - nfft) // hop
            idx = np.arange(nfft)[None, :] + hop * np.arange(nfrm)[:, None]
            return np.abs(np.fft.rfft(x[idx] * win, axis=1))
        Y, Yh = spec(y), spec(yhat)
        sc = np.linalg.norm(Y - Yh) / (np.linalg.norm(Y) + EPS)
        mag = np.mean(np.abs(np.log(Y + EPS) - np.log(Yh + EPS)))
        total += sc + mag
    return float(total)


# ----------------------------------------------------- wander injection panel

def make_sinc_table(taps=32, nfrac=1024, beta=8.0):
    half = taps // 2
    j = np.arange(-half + 1, half + 1, dtype=np.float64)  # taps offsets
    fr = np.arange(nfrac) / nfrac
    x = j[None, :] - fr[:, None]                          # (nfrac, taps)
    s = np.sinc(x)
    arg = 1.0 - (x / half) ** 2
    w = np.where(arg > 0, np.i0(beta * np.sqrt(np.maximum(arg, 0))) / np.i0(beta), 0.0)
    tbl = s * w
    tbl /= tbl.sum(axis=1, keepdims=True)                 # unity DC gain
    return tbl, half


def fractional_delay_varying(y, d, taps=32, chunk=1 << 18):
    """y_w[n] = y(n - d[n]), windowed-sinc (polyphase table)."""
    tbl, half = make_sinc_table(taps=taps)
    nfrac = tbl.shape[0]
    n = len(y)
    pad = half + int(np.ceil(np.max(np.abs(d)))) + 2
    ypad = np.pad(y, (pad, pad))
    out = np.empty(n)
    for c0 in range(0, n, chunk):
        c1 = min(n, c0 + chunk)
        idx = np.arange(c0, c1)
        pos = idx - d[c0:c1]
        base = np.floor(pos).astype(np.int64)
        frac = pos - base
        q = np.minimum((frac * nfrac).astype(np.int64), nfrac - 1)
        gather = (base[:, None] + pad) + np.arange(-half + 1, half + 1)[None, :]
        out[c0:c1] = np.sum(ypad[gather] * tbl[q], axis=1)
    return out


def best_static_shift_esr(y, y_w, max_shift=12):
    """min over integer shifts of ESR(y, shift(y_w)) on the overlap."""
    best = np.inf
    best_s = 0
    n = len(y)
    for s in range(-max_shift, max_shift + 1):
        if s >= 0:
            a, b = y[s:], y_w[: n - s]
        else:
            a, b = y[:n + s], y_w[-s:]
        m = min(len(a), len(b))
        e = esr_db(a[:m], b[:m])
        if e < best:
            best, best_s = e, s
    return best, best_s


# ---------------------------------------------------------------------- main

def read_probe_csv(path, pos_col, lag_col):
    import csv
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"probe CSV {path} is empty")
    cols = list(rows[0].keys())

    def pick(want, candidates):
        if want:
            if want in cols:
                return want
            sys.exit(f"column '{want}' not in {path}; columns found: {cols}")
        for c in candidates:
            if c in cols:
                return c
        sys.exit(f"could not guess {'position' if candidates[0]=='frac' else 'lag'} "
                 f"column in {path}; columns found: {cols} — "
                 f"pass --probe-pos-col / --probe-lag-col")

    pc = pick(pos_col, ["frac", "position", "pos", "t", "time", "time_s"])
    lc = pick(lag_col, ["lag", "lag_samples", "offset", "offset_samples", "shift"])
    pos = np.array([float(r[pc]) for r in rows if r[pc] not in ("", None)])
    lag = np.array([float(r[lc]) for r in rows if r[lc] not in ("", None)])
    is_frac = np.nanmax(pos) <= 1.001
    return pos, lag, is_frac, (pc, lc)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pair", nargs=3, action="append", metavar=("LABEL", "DRY", "WET"),
                    required=True, help="first pair = subject; rest = controls")
    ap.add_argument("--probe-csv", nargs=2, action="append", metavar=("PATH", "LABEL"),
                    default=[], help="verify_alignment dense-probe CSV to overlay")
    ap.add_argument("--probe-pos-col", default=None)
    ap.add_argument("--probe-lag-col", default=None)
    ap.add_argument("--metrics-csv", default=None,
                    help="CSV: label,esr_db,mrstft (per-source model metrics)")
    ap.add_argument("--highlight", default=None,
                    help="metrics row substring to highlight (default: subject label)")
    ap.add_argument("--inject-audio", default=None,
                    help="clean wet capture for the wander-injection panel")
    ap.add_argument("--marker-offsets", nargs=2, type=float, default=None,
                    metavar=("START", "END"), help="annotate marker start/end offsets")
    ap.add_argument("--win", type=float, default=1.0, help="window length s")
    ap.add_argument("--hop", type=float, default=2.0, help="hop s")
    ap.add_argument("--search", type=int, default=64, help="lag search +/- samples")
    ap.add_argument("--gate-dbfs", type=float, default=-45.0)
    ap.add_argument("--min-corr", type=float, default=0.0,
                    help="drop windows whose normalized peak corr is below this")
    ap.add_argument("--phat-band", nargs=2, type=float, default=(60.0, 8000.0),
                    metavar=("LO_HZ", "HI_HZ"),
                    help="frequency band used for PHAT whitening")
    ap.add_argument("--tolerance", type=float, default=2.0,
                    help="jitter tolerance band +/- samples (frozen criterion)")
    ap.add_argument("--out", default="gtr2_characterization")
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    report = []

    def log(s=""):
        print(s)
        report.append(s)

    # ---------------- lag profiles ----------------
    profiles = {}
    for label, dpath, wpath in args.pair:
        dry, srd = load_audio(dpath)
        wet, srw = load_audio(wpath)
        if srd != srw:
            sys.exit(f"[{label}] sample-rate mismatch: {srd} vs {srw}")
        base, anchor = global_base_lag(dry, wet, srd)
        prof = window_lags(dry, wet, srd, base, win_s=args.win, hop_s=args.hop,
                           search=args.search, gate_dbfs=args.gate_dbfs,
                           min_corr=args.min_corr,
                           phat_band=tuple(args.phat_band))
        prof["sr"] = srd
        prof["base"] = base
        prof["dur"] = len(dry) / srd
        profiles[label] = prof
        st = detrend_stats(prof["t"], prof["lag_xc"])
        log(f"[{label}] base lag {base:+d} (marker-free anchor @ {anchor/srd:.1f}s), "
            f"{len(prof['t'])} windows, median peak corr "
            f"{np.median(prof['corr']):.3f}" if len(prof['t']) else
            f"[{label}] base lag {base:+d} — NO windows passed the gates")
        if st:
            log(f"  wander pp raw {st['pp_raw']:.2f} | after const {st['pp_const']:.2f} "
                f"| after linear {st['pp_lin']:.2f} (rms {st['rms_lin']:.2f}) "
                f"| drift {st['slope_per_min']:+.2f} smp/min")
        # xcorr vs PHAT internal agreement
        dd = np.abs(prof["lag_xc"] - prof["lag_ph"])
        log(f"  estimator agreement (xcorr vs PHAT): max |Δ| {dd.max():.2f}, "
            f"median {np.median(dd):.2f} samples")
        np.savetxt(outdir / f"lag_profile_{label}.csv",
                   np.column_stack([prof["t"], prof["lag_xc"], prof["lag_ph"],
                                    prof["corr"], prof["rms"]]),
                   delimiter=",", header="t_s,lag_xcorr,lag_phat,peak_corr,dry_rms_db",
                   comments="")
    subject = args.pair[0][0]

    # ---------------- probe-CSV cross-validation ----------------
    probe_data = {}
    for path, label in args.probe_csv:
        pos, lag, is_frac, cols = read_probe_csv(path, args.probe_pos_col,
                                                 args.probe_lag_col)
        if label not in profiles:
            log(f"[probe-csv {path}] label '{label}' has no --pair; overlay only")
        t = pos * profiles.get(label, profiles[subject])["dur"] if is_frac else pos
        probe_data[label] = (t, lag)
        log(f"[probe-csv {label}] {len(t)} probes (cols {cols[0]}/{cols[1]}, "
            f"{'frac' if is_frac else 'seconds'})")
        if label in profiles:
            prof = profiles[label]
            for name, key in (("xcorr", "lag_xc"), ("PHAT", "lag_ph")):
                interp = np.interp(t, prof["t"], prof[key])
                dd = np.abs(interp - lag)
                log(f"  CSV vs fresh {name}: max |Δ| {dd.max():.2f}, "
                    f"median {np.median(dd):.2f} samples")
            agree = max(np.abs(np.interp(t, prof["t"], prof["lag_xc"]) - lag).max(),
                        np.abs(np.interp(t, prof["t"], prof["lag_ph"]) - lag).max())
            verdict = ("INSTRUMENT-CONFIRMED: three independent estimates agree — "
                       "the wander is a property of the capture, not the alignment "
                       "tooling." if agree <= 1.5 else
                       "DISAGREEMENT above ±1.5 samples — investigate the alignment "
                       "pipeline before trusting either profile.")
            log(f"  >>> {verdict}")

    # ---------------- injection panel ----------------
    inj = None
    if args.inject_audio:
        y, sri = load_audio(args.inject_audio)
        prof = profiles[subject]
        # stretch the measured trajectory onto the injected file's timeline
        tt = prof["t"] / prof["dur"] * (len(y) / sri)
        traj = prof["lag_xc"] - np.mean(prof["lag_xc"])  # wander only, no base
        d = np.interp(np.arange(len(y)) / sri, tt, traj)
        y_w = fractional_delay_varying(y, d)
        e_raw = esr_db(y, y_w)
        e_best, s_best = best_static_shift_esr(y, y_w)
        m_w = mrstft(y, y_w)
        # calibration control: constant delay, then corrected → machinery floor
        y_c = fractional_delay_varying(y, np.full(len(y), 4.0))
        e_cal, _ = best_static_shift_esr(y, y_c)
        inj = dict(e_raw=e_raw, e_best=e_best, s_best=s_best, m=m_w, e_cal=e_cal)
        log(f"[injection] measured-wander trajectory applied to "
            f"{Path(args.inject_audio).name}:")
        log(f"  ESR raw {e_raw:.2f} dB | after best static shift ({s_best:+d}) "
            f"{e_best:.2f} dB | MR-STFT {m_w:.3f}")
        log(f"  machinery floor (const 4.0-sample delay, shift-corrected): "
            f"{e_cal:.2f} dB — wander floor is real if far above this")

    # ---------------- metrics panel data ----------------
    metrics = None
    if args.metrics_csv:
        if not Path(args.metrics_csv).exists():
            log(f"WARNING: metrics CSV '{args.metrics_csv}' not found — "
                f"skipping the metric-specificity panel")
        else:
            import csv
            with open(args.metrics_csv, newline="") as f:
                rows = list(csv.DictReader(f))
            metrics = [(r["label"], float(r["esr_db"]), float(r["mrstft"]))
                       for r in rows]

    # ---------------- figure ----------------
    n_panels = 2 + (metrics is not None) + (inj is not None)
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    ax1, ax2, ax3, ax4 = axes.ravel()

    colors = plt.cm.Greys(np.linspace(0.45, 0.7, max(len(profiles) - 1, 1)))
    ci = 0
    for label, prof in profiles.items():
        lag_rel = None
        if label == subject:
            ax1.plot(prof["t"], prof["lag_xc"], "-", color="#c0392b", lw=1.6,
                     label=f"{label} (xcorr)")
            ax1.plot(prof["t"], prof["lag_ph"], "--", color="#e67e22", lw=1.2,
                     label=f"{label} (GCC-PHAT)")
        else:
            ax1.plot(prof["t"], prof["lag_xc"], "-", color=colors[ci], lw=1.0,
                     label=f"{label} (control)")
            ci += 1
    for label, (t, lag) in probe_data.items():
        ax1.plot(t, lag, "o", ms=4, mfc="none", mec="#2c3e50",
                 label=f"{label} verify_alignment probes")
    med = np.median(profiles[subject]["lag_xc"])
    ax1.axhspan(med - args.tolerance, med + args.tolerance, color="#2ecc71",
                alpha=0.15, label=f"±{args.tolerance:g} tolerance")
    if args.marker_offsets:
        s, e = args.marker_offsets
        ax1.axhline(s, color="#8e44ad", ls=":", lw=1)
        ax1.axhline(e, color="#8e44ad", ls=":", lw=1)
        ax1.text(0.99, s, f"marker start {s:+g}", ha="right", va="bottom",
                 transform=ax1.get_yaxis_transform(), fontsize=8, color="#8e44ad")
        ax1.text(0.99, e, f"marker end {e:+g}", ha="right", va="bottom",
                 transform=ax1.get_yaxis_transform(), fontsize=8, color="#8e44ad")
    ax1.set_xlabel("position (s)")
    ax1.set_ylabel("lag, wet − dry (samples)")
    ax1.set_title("Time-base error — independent derivation vs saved probes")
    ax1.legend(fontsize=7, ncol=2)

    labels = list(profiles.keys())
    x = np.arange(len(labels))
    for i, key, name, col in ((0, "pp_raw", "raw", "#95a5a6"),
                              (1, "pp_const", "const-detrended", "#3498db"),
                              (2, "pp_lin", "linear-detrended", "#c0392b")):
        vals = [detrend_stats(profiles[l]["t"], profiles[l]["lag_xc"])[key]
                for l in labels]
        ax2.bar(x + (i - 1) * 0.26, vals, 0.26, label=name, color=col)
    ax2.axhline(2 * args.tolerance, color="#2ecc71", ls="--",
                label=f"pp tolerance ({2 * args.tolerance:g})")
    ax2.set_xticks(x, labels, rotation=15, fontsize=8)
    ax2.set_ylabel("lag peak-to-peak (samples)")
    ax2.set_title("No static or linear correction removes it")
    ax2.legend(fontsize=8)

    if metrics:
        ml, me, mm = zip(*metrics)
        hi = args.highlight or subject
        cols_ = ["#c0392b" if hi.split("_")[0] in l else "#7f8c8d" for l in ml]
        xm = np.arange(len(ml))
        ax3.bar(xm - 0.18, me, 0.36, color=cols_, label="ESR (dB)")
        ax3.set_ylabel("model ESR (dB)  ↓ better", color="#c0392b")
        ax3b = ax3.twinx()
        ax3b.plot(xm + 0.18, mm, "D", color="#2c3e50", ms=7, label="MR-STFT")
        ax3b.set_ylabel("MR-STFT  ↓ better", color="#2c3e50")
        ax3.set_xticks(xm, ml, rotation=15, fontsize=8)
        ax3.set_title("Metric-specific floor: ESR pinned, MR-STFT unharmed")
    else:
        ax3.axis("off")
        ax3.text(0.5, 0.5, "(--metrics-csv not given)", ha="center", va="center")

    if inj:
        bars = [inj["e_raw"], inj["e_best"], inj["e_cal"]]
        names = ["wander\n(raw)", f"wander after best\nstatic shift ({inj['s_best']:+d})",
                 "machinery floor\n(const delay, corrected)"]
        ax4.bar(names, bars, color=["#c0392b", "#e67e22", "#95a5a6"])
        for i, v in enumerate(bars):
            ax4.text(i, v, f"{v:.1f} dB", ha="center",
                     va="bottom" if v < 0 else "top", fontsize=9)
        ax4.set_ylabel("ESR (dB) vs original")
        ax4.set_title(f"Injected measured lag trajectory → ESR floor "
                      f"(MR-STFT = {inj['m']:.2f})")
    else:
        ax4.axis("off")
        ax4.text(0.5, 0.5, "(--inject-audio not given)", ha="center", va="center")

    fig.suptitle("gtr2 D050 exclusion characterization", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    for ext in ("png", "pdf"):
        try:
            fig.savefig(outdir / f"gtr2_characterization.{ext}", dpi=150)
        except (PermissionError, OSError) as e:
            log(f"WARNING: could not write gtr2_characterization.{ext} "
                f"({e}) — is it open in a viewer?")
    (outdir / "report.txt").write_text("\n".join(report), encoding="utf-8")
    log(f"\nwrote {outdir}/gtr2_characterization.png (+.pdf), lag_profile_*.csv, "
        f"report.txt")


if __name__ == "__main__":
    main()
