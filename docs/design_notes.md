# Design Notes

Dated record of the design decisions behind the paper. Entries between April and July were not journaled at the time; the decisions they produced are listed under the first entry below.

## 2026-04-18 — Project kickoff

Started as the ECEN 529 lab project: a small GRU modeling a nonlinear audio effect in Vitis HLS on the PYNQ-Z2. Open at the time: target effect, hidden size, dataset, quantization strategy.

**Where those landed (by July):**
- Dataset: ToneTwist AFX (Comunità et al., 2025) — paired dry/wet recordings with impulse markers for sample-level alignment.
- Effects: three pedals (Harley Benton Rodent, Green Tint, Fuzzy Logic) × two gain settings = six weight sets on one kernel.
- Model: single-layer GRU, PyTorch form (reset gate applied after the candidate's recurrent product), H = 40 from the grid search, affine output layer. Loss ESR + DC with A-weighting pre-emphasis.
- Quantization strategy: not INT8 post-training — a fixed-point word-length sweep, `ap_fixed<W,I>` with W = 8…24 and I fixed (5 for weights/biases/output layer, 2 for inputs/states/activations). The question became "which metric picks W".

## 2026-07-10 — Models of record

The `v2` runs (`rodent_max_v2`, `rodent_mod_v2c`, `greentint_max_v2`, `greentint_low_v2`, `fuzzylogic_max_v2`, `fuzzylogic_mod_v2`) are the six checkpoints in `models/`. Rodent 'moderate' trained on four of five sources (gtr2 excluded, time-base discontinuity). Green Tint 'moderate' uses the zero-drive setting because the dataset's mid-gain setting is within −27.9 dB of maximum.

## 2026-08-03 — Kernel of record

`gru_va_col_fused_mac3.cpp`: the three recurrent matrix-vector products split across P = H = 40 columns, each with its own accumulator; PIPELINE on the inner loop, cyclic ARRAY_PARTITION on the recurrent weights, complete partition of the hidden state; output accumulation merged into the hidden-state loop. Activations by a 1025-entry LUT over |v| ∈ [0, 8] in 1/128 steps with linear interpolation; sigmoid via tanh. Accumulator, output sum and gate arithmetic fixed at `<32,12>` and never swept — the ACC-40 probe (`reports/csim_wext/rodent_max_w28_acc40_csim.log`) showed `<40,20>` is byte-identical to `<32,12>` at W = 28, so the accumulator is not the limiting width.

## 2026-08-09 — 102 bitstreams, 100 MHz

All 6 × 17 builds closed timing. Eighteen needed a second placement arm (`_dsp` / `_dsp_best`) — see the README's "Arms" section. The deployed arm per build is recorded in `resources_by_width_REV1.csv`.

## 2026-08-10 … 08-15 — Board campaigns

- 08-10: nam campaign, 102 builds × nam (`gru_campaign_102_REV1.ipynb`); kernel timing window measured here (DMA send-channel transfer → wait).
- 08-13: golden-mode gate — every bitstream reproduces its C-sim output byte-identically (102/102).
- 08-14/15: Sessions 1–4 — four music sources + signal battery, 918 captures, all hash-attested. Session 4 added rodent 'maximum' at full scope by decision, so all six cells went through the identical capture pipeline.
- 08-15: rodent 'maximum' board outputs vs Elle C-sim, byte-identical, four music sources × 17 W (68/68); nam 17/17 via the campaign hashes. The two test-segregated sources (added 09-05/06) were scored on silicon only.

## 2026-08-13 — Metrics of record

- ESR scored without pre-emphasis, following the reporting convention of Wright et al. 2020; A-weighting only in the training loss.
- NMR: own implementation (NMR-REV2: 2048 Hann, 50 % overlap, outer/middle-ear weighting, 0.25-Bark bands 80 Hz–18 kHz, 92 dB SPL calibration). Validated against GstPEAQ's total-NMR output: r = 0.997 over 510 points, −1.7 dB offset.
- PEAQ: GstPEAQ 0.6.1 basic model at 48 kHz, both signals low-passed at 20 kHz. NMR and ODG share PEAQ's front end and are reported as two masking-based metrics, not as independent evidence.
- Selection rule: smallest W whose five-source mean meets the bar (ESR ≤ −20 dB; ODG ≥ −0.5), both literature-motivated operating points, not listening criteria. Table 1 sweeps both bars to show the direction of the gap does not depend on the pair chosen (14 of 15 cells positive).

## 2026-08-16 — ARM A9 baseline

RTNeural on the PYNQ's Cortex-A9 (Eigen/NEON and STL backends), float32, rodent 'maximum' on nam: 0.571× and 0.331× real-time; neither reaches real-time. Rerun 2026-09-13 with console captured: outputs byte-identical, Eigen 0.534×, STL 0.331×.

## 2026-08-21 — Sweep top

W = 28 and 32 probed in C-sim on rodent 'maximum': ESR vs golden −87.42 (W = 23), −87.88 (24), −90.71 (28), −89.96 (32). Improvement per bit flattens after W = 23; W = 24 adopted as the top of the sweep.

## 2026-09-05/06 — Test-segregated sources

idmt-bass and idmt-gtr4-ib, never used in training, captured for all 102 builds (204 outputs) and scored under the same rule: 12/12 model–source pairs defined, per-model spans {+2,+3,+4,+3,+4,+3}, mean +3.2 bits.

## 2026-09-13 — Public repository

- Personal paths scrubbed to placeholders; the two DSP-binding csynth reports, `errlevel_T5_REV2_510.csv` and `float_refs_md5.txt` were affected, so raw and scrubbed hashes are both recorded (README, Conventions → Hashes) and the raw copies are held offline. The published history starts from a single clean commit; no earlier revision is public.
- Evidence trees stored byte-exact (`.gitattributes -text`) so clone hashes match the hashes of record.
- The internal analysis workbook is not published; the raw CSVs and matrices are the public record and `verify_paper_claims_REV4.py` re-derives and asserts the paper's numbers from them.
- Bitstreams published as one zip (102 `.bit` + `.hwh`, 59 MB) with per-file MD5s; board captures published as hash lists only.
