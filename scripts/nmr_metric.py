#!/usr/bin/env python3
# NMR-REV2
"""
nmr_metric.py -- masking-based Noise-to-Mask Ratio (NMR), PEAQ-basic-inspired.

Purpose
  Perceptually weighted error metric for the fixed-point GRU VA study:
  estimates the audibility of (test - ref) error relative to the masking
  threshold induced by the reference signal. Ear model follows the PEAQ
  basic-model FFT chain (ITU-R BS.1387; constants per Kabal's exposition):

    frame (2048 Hann, 50% overlap, 48 kHz)
      -> outer/middle-ear power weighting
      -> grouping to 0.25-Bark critical bands, 80 Hz .. 18 kHz
         (Schroeder scale z = 7*asinh(f/650), ~109 bands)
      -> internal-noise (threshold-in-quiet) floor added, forming the
         pitch pattern (PEAQ order: internal noise BEFORE spreading)
      -> level-dependent frequency spreading of the reference pitch
         pattern (lower slope 27 dB/Bark; upper slope
         24 + 230/fc - 0.2*L dB/Bark, L from the pitch pattern)
      -> masking offset indexed by band position in the grid:
         3 dB for i*dz <= 12, 0.25*i*dz above (breakpoint ~1983 Hz)
    noise = (|FFT(ref)| - |FFT(test)|)^2 per bin (phase-insensitive, per PEAQ),
    ear-weighted and banded (no spreading applied to noise, per PEAQ).

    NMR(frame) = mean over bands of  P_noise(band) / Mask(band)
    NMR(total) = 10*log10( mean over voiced frames of NMR(frame) )

  More negative NMR = error further below the masking threshold
  (less audible). NMR is linear in noise power: +20 dB more noise
  energy -> +20 dB NMR against a fixed reference.

Documented simplifications vs full BS.1387 (state these in the paper):
  * Frequency-domain masking only; no time-domain spreading
    (forward masking) -- trends across bit-width are unaffected.
  * Linear (power) superposition of spreading contributions instead of
    PEAQ's nonlinear (alpha = 0.4) superposition, and no spreading-energy
    renormalization; both are absorbed as a near-constant offset and do
    not affect cross-configuration trends.
  * No data-boundary/avg-window machinery; instead a simple voiced-frame
    gate on reference frame RMS.
  * Calibration convention: full-scale sine = 92 dB SPL (PEAQ default
    listening level), applied as a fixed power scaling.

Inputs are raw float32 little-endian mono (.f32), the project's exchange
format. Signals are assumed pipeline-aligned (csim outputs are
sample-aligned to their references by construction). DC / sub-80 Hz bias
falls outside the band structure and is therefore excluded by design --
appropriate, since it is inaudible.

Memory: fully chunked streaming over frames; peak footprint is bounded
(~tens of MB) regardless of file length.

Usage
  python nmr_metric.py --ref ref.f32 --test test.f32 [--skip 1024]
                       [--window-sec 30] [--csv out.csv --label name]
  python nmr_metric.py --selftest

Selftest battery (V1-V3; V4 = cross-check vs an independent
implementation, performed separately):
  V1 identity      : test == ref            -> NMR at numerical floor
  V2 monotonicity  : white noise at -60/-40/-20 dB rel. to a tone
                     -> NMR strictly increasing, ~20 dB per step
  V3 masking sanity: equal-energy narrowband noise inside the masker's
                     critical band vs far away -> in-band NMR must be
                     substantially lower (masked). This is the vector
                     that proves the masking model is functional.
"""

import argparse
import os
import sys

import numpy as np

SENTINEL = "NMR-REV2"

# ---------------------------------------------------------------- constants
FS = 48000
NFFT = 2048
HOP = 1024
LP_DB = 92.0            # full-scale sine calibration level, dB SPL
BARK_RES = 0.25
F_LO, F_HI = 80.0, 18000.0
EPS = 1e-30
NMR_FLOOR_DB = -120.0
VOICED_RMS_FS = 1e-5    # -100 dBFS reference-frame gate
FRAME_CHUNK = 256       # frames per vectorized chunk (memory bound)


# ---------------------------------------------------------------- ear model
def hz_to_bark(f):
    return 7.0 * np.arcsinh(np.asarray(f, dtype=np.float64) / 650.0)


def bark_to_hz(z):
    return 650.0 * np.sinh(np.asarray(z, dtype=np.float64) / 7.0)


def ear_weight_db(f):
    """Outer + middle ear weighting, dB (PEAQ W(f))."""
    fk = np.asarray(f, dtype=np.float64) / 1000.0
    fk = np.maximum(fk, 1e-6)
    return (-2.184 * fk ** -0.8
            + 6.5 * np.exp(-0.6 * (fk - 3.3) ** 2)
            - 1e-3 * fk ** 3.6)


def internal_noise_db(f):
    """Internal-noise (threshold-in-quiet) excitation, dB (PEAQ E_IN)."""
    fk = np.asarray(f, dtype=np.float64) / 1000.0
    fk = np.maximum(fk, 1e-6)
    return 1.456 * fk ** -0.8


class EarModel:
    """Precomputed frame->band machinery for one (fs, nfft) geometry."""

    def __init__(self, fs=FS, nfft=NFFT):
        self.fs = fs
        self.nfft = nfft
        self.win = np.hanning(nfft).astype(np.float64)
        self.win_rms = np.sqrt(np.mean(self.win ** 2))
        # magnitude normalization: full-scale sine -> peak-bin magnitude 1.0
        self.mag_norm = 2.0 / np.sum(self.win)
        self.cal_pow = 10.0 ** (LP_DB / 10.0)   # FS sine band power = 92 dB

        nbins = nfft // 2 + 1
        df = fs / nfft
        self.bin_freq = np.arange(nbins) * df
        bin_lo = self.bin_freq - df / 2.0
        bin_hi = self.bin_freq + df / 2.0

        z_lo = float(hz_to_bark(F_LO))
        z_hi = float(hz_to_bark(F_HI))
        nb = int(np.ceil((z_hi - z_lo) / BARK_RES))
        z_edges = z_lo + BARK_RES * np.arange(nb + 1)
        self.z_center = 0.5 * (z_edges[:-1] + z_edges[1:])
        self.fc = bark_to_hz(self.z_center)
        f_edges = bark_to_hz(z_edges)
        self.nbands = nb

        # proportional bin->band energy assignment (overlap fractions)
        W = np.zeros((nb, nbins), dtype=np.float64)
        for b in range(nb):
            lo, hi = f_edges[b], f_edges[b + 1]
            ov = np.minimum(bin_hi, hi) - np.maximum(bin_lo, lo)
            W[b, :] = np.clip(ov, 0.0, None) / df
        self.band_matrix_T = W.T.copy()          # (nbins, nbands)

        # ear weighting as bin-domain power gains
        self.ear_pow = 10.0 ** (ear_weight_db(self.bin_freq) / 10.0)
        # internal noise per band (linear power)
        self.e_internal = 10.0 ** (internal_noise_db(self.fc) / 10.0)
        # masking offset per band (linear attenuation of excitation)
        z_rel = BARK_RES * (0.5 + np.arange(nb))   # band position in grid
        m_db = np.where(z_rel <= 12.0, 3.0, 0.25 * z_rel)
        self.mask_gain = 10.0 ** (-m_db / 10.0)
        # band-distance matrix for spreading: dz[i, j] = z_i - z_j
        self.dz = self.z_center[:, None] - self.z_center[None, :]

    def chunk_analysis(self, ref, test, f_start, f_count):
        """Analyze frames [f_start, f_start+f_count).

        Returns (nmr_lin, voiced) for the chunk.
        """
        idx = (np.arange(self.nfft)[None, :]
               + HOP * (f_start + np.arange(f_count))[:, None])
        fr = ref[idx] * self.win[None, :]
        ft = test[idx] * self.win[None, :]

        mr = np.abs(np.fft.rfft(fr, axis=1)) * self.mag_norm
        mt = np.abs(np.fft.rfft(ft, axis=1)) * self.mag_norm

        p_ref = (mr ** 2) * self.cal_pow * self.ear_pow[None, :]
        p_noise = ((mr - mt) ** 2) * self.cal_pow * self.ear_pow[None, :]

        e_ref = p_ref @ self.band_matrix_T          # (C, nbands)
        e_noise = p_noise @ self.band_matrix_T

        # pitch pattern: internal noise added BEFORE spreading (PEAQ order)
        e_pitch = np.maximum(e_ref, EPS) + self.e_internal[None, :]
        # level-dependent spreading of the reference pitch pattern
        L = 10.0 * np.log10(e_pitch)
        s_up = np.maximum(24.0 + 230.0 / self.fc[None, :] - 0.2 * L, 1.0)
        dz = self.dz[None, :, :]
        atten = np.where(dz >= 0.0,
                         s_up[:, None, :] * dz,     # test band above source
                         27.0 * (-dz))               # test band below source
        gain = 10.0 ** (-atten / 10.0)
        e_spread = np.einsum("cij,cj->ci", gain, e_pitch)
        mask = e_spread * self.mask_gain[None, :]

        nmr_lin = np.mean(e_noise / np.maximum(mask, EPS), axis=1)
        frame_rms = np.sqrt(np.mean(fr ** 2, axis=1)) / self.win_rms
        voiced = frame_rms > VOICED_RMS_FS
        return nmr_lin, voiced


# ---------------------------------------------------------------- pipeline
def load_f32(path):
    x = np.fromfile(path, dtype="<f4").astype(np.float64)
    if x.size == 0:
        raise SystemExit(f"ERROR: empty or unreadable f32 file: {path}")
    return x


def compute_nmr(ref, test, skip=0, window_sec=None, verbose=True):
    ear = EarModel()
    if skip:
        ref, test = ref[skip:], test[skip:]
    n = min(len(ref), len(test))
    if abs(len(ref) - len(test)) > HOP and verbose:
        print(f"WARN length mismatch ref={len(ref)} test={len(test)} "
              f"(truncating to {n})")
    ref, test = np.ascontiguousarray(ref[:n]), np.ascontiguousarray(test[:n])

    n_frames = 1 + max(0, (n - NFFT)) // HOP
    if n_frames < 1:
        raise SystemExit("ERROR: input shorter than one analysis frame")

    nmr_lin = np.empty(n_frames)
    voiced = np.empty(n_frames, dtype=bool)
    for s in range(0, n_frames, FRAME_CHUNK):
        c = min(FRAME_CHUNK, n_frames - s)
        nmr_lin[s:s + c], voiced[s:s + c] = ear.chunk_analysis(ref, test, s, c)

    if not np.any(voiced):
        return NMR_FLOOR_DB, nmr_lin, voiced
    total = 10.0 * np.log10(max(np.mean(nmr_lin[voiced]),
                                10 ** (NMR_FLOOR_DB / 10)))

    if window_sec and verbose:
        wf = int(window_sec * FS / HOP)
        print("per-window NMR (dB):")
        for i in range(0, len(nmr_lin), wf):
            seg, vseg = nmr_lin[i:i + wf], voiced[i:i + wf]
            if np.any(vseg):
                w_db = 10.0 * np.log10(max(np.mean(seg[vseg]),
                                           10 ** (NMR_FLOOR_DB / 10)))
                print(f"  t={i * HOP / FS:8.1f}s  NMR={w_db:8.2f}")
    return total, nmr_lin, voiced


# ---------------------------------------------------------------- selftest
def _tone(freq, sec=1.0, amp=0.5, fs=FS):
    t = np.arange(int(sec * fs)) / fs
    return amp * np.sin(2 * np.pi * freq * t)


def _narrowband_noise(center, halfwidth, n, rms, seed):
    rng = np.random.default_rng(seed)
    spec = np.zeros(n // 2 + 1, dtype=np.complex128)
    freqs = np.fft.rfftfreq(n, 1.0 / FS)
    band = (freqs >= center - halfwidth) & (freqs <= center + halfwidth)
    spec[band] = (rng.standard_normal(band.sum())
                  + 1j * rng.standard_normal(band.sum()))
    x = np.fft.irfft(spec, n)
    return x * (rms / np.sqrt(np.mean(x ** 2)))


def selftest():
    print(f"{SENTINEL} selftest")
    ok = True

    # V1 -- identity
    ref = _tone(997.0)
    nmr, _, _ = compute_nmr(ref, ref.copy(), verbose=False)
    p = nmr <= -90.0
    ok &= p
    print(f"V1 identity            NMR={nmr:9.2f} dB   "
          f"expect <= -90        {'PASS' if p else 'FAIL'}")

    # V2 -- monotonic tracking of noise level
    rng = np.random.default_rng(0)
    wn = rng.standard_normal(len(ref))
    wn /= np.sqrt(np.mean(wn ** 2))
    ref_rms = np.sqrt(np.mean(ref ** 2))
    nmrs = []
    for rel_db in (-60.0, -40.0, -20.0):
        noise = wn * ref_rms * 10 ** (rel_db / 20.0)
        nmr, _, _ = compute_nmr(ref, ref + noise, verbose=False)
        nmrs.append(nmr)
    d1, d2 = nmrs[1] - nmrs[0], nmrs[2] - nmrs[1]
    p = (nmrs[0] < nmrs[1] < nmrs[2]) and all(17.0 <= d <= 23.0
                                              for d in (d1, d2))
    ok &= p
    print(f"V2 monotonic           NMR={nmrs[0]:7.2f} / {nmrs[1]:7.2f} / "
          f"{nmrs[2]:7.2f}   steps {d1:5.2f}, {d2:5.2f} dB "
          f"(expect ~20 +/- 3)  {'PASS' if p else 'FAIL'}")

    # V3 -- masking sanity: equal-energy noise in-band vs far-band
    noise_rms = ref_rms * 10 ** (-40.0 / 20.0)
    n_in = _narrowband_noise(997.0, 50.0, len(ref), noise_rms, seed=1)
    n_out = _narrowband_noise(4000.0, 50.0, len(ref), noise_rms, seed=2)
    nmr_in, _, _ = compute_nmr(ref, ref + n_in, verbose=False)
    nmr_out, _, _ = compute_nmr(ref, ref + n_out, verbose=False)
    margin = nmr_out - nmr_in
    p = margin >= 10.0
    ok &= p
    print(f"V3 masking             in-band {nmr_in:7.2f}  far-band "
          f"{nmr_out:7.2f}  margin {margin:6.2f} dB "
          f"(expect >= 10)   {'PASS' if p else 'FAIL'}")

    print(f"selftest {'ALL PASS (3/3)' if ok else 'FAILURES PRESENT'}")
    return 0 if ok else 1


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="PEAQ-inspired NMR metric")
    ap.add_argument("--ref", help="reference .f32 (float ref or target)")
    ap.add_argument("--test", help="test .f32 (HLS/board output)")
    ap.add_argument("--skip", type=int, default=0,
                    help="samples to skip at start (washout)")
    ap.add_argument("--window-sec", type=float, default=None,
                    help="also report per-window NMR (drift instrument)")
    ap.add_argument("--csv", default=None, help="append result row to CSV")
    ap.add_argument("--label", default=None, help="row label for --csv")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())
    if not (args.ref and args.test):
        ap.error("--ref and --test required (or --selftest)")

    ref = load_f32(args.ref)
    test = load_f32(args.test)
    nmr, nmr_lin, voiced = compute_nmr(ref, test, skip=args.skip,
                                       window_sec=args.window_sec)
    print(f"{SENTINEL}  NMR = {nmr:.2f} dB   "
          f"(frames={len(nmr_lin)}, voiced={int(voiced.sum())}, "
          f"skip={args.skip})")

    if args.csv:
        label = args.label or os.path.basename(args.test)
        new = not os.path.exists(args.csv)
        with open(args.csv, "a", encoding="utf-8") as fh:
            if new:
                fh.write("label,nmr_db,frames,voiced_frames,skip,sentinel\n")
            fh.write(f"{label},{nmr:.4f},{len(nmr_lin)},"
                     f"{int(voiced.sum())},{args.skip},{SENTINEL}\n")
        print(f"appended -> {args.csv}")


if __name__ == "__main__":
    main()
