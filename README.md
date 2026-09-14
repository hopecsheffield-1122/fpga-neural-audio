# fpga-neural-audio

Companion repository for

> **Energy-Based vs Masking-Based Word-Length Selection for Fixed-Point Recurrent Audio Effect Models on FPGA**
> Hope Sheffield and Radhika S. Grover, Santa Clara University — submitted to ICASSP 2027.

**Submission state:** git tag `icassp-2027-submission` is the artifact the manuscript refers to (`git rev-parse icassp-2027-submission` prints its commit; the GitHub release page lists the SHA). Anything after that tag is post-submission work.

Six single-layer GRU virtual-analog models (three guitar pedals × two gain settings) are deployed on one Vitis HLS kernel on the xc7z020 (PYNQ-Z2), swept over fixed-point word-length W = 8…24 ("one kernel" means one HLS source and architecture, `hls/src/gru_va_col_fused_mac3.cpp`, compiled separately for each of the 102 (weight set, W) builds with the weights as constants — not one runtime-switchable bitstream), and scored against their float32 references under ESR, NMR and PEAQ ODG. This repository holds everything a reader needs to check the numbers in the paper: the kernel and models, every raw score, every synthesis/implementation report for the 102 builds, the board-side notebooks, the bitstreams, and scripts that re-derive the paper's tables and figures from the raw files.

## Layout

```
hls/          Vitis HLS kernel (gru_va_col_fused_mac3.cpp), headers, per-model weights.h, testbench
models/       six PyTorch checkpoints (best.pt) with their training and evaluation logs
scripts/      training, weight export, HLS/Vivado batch drivers, board harnesses, scorers, analysis, figures, verifiers
board/        PYNQ notebooks (outputs cleared), chunk-size sweep, board cleanup script
reports/
  csynth/         Vitis HLS synthesis reports, 5 per build x 102 builds
  impl/           Vivado placed-utilization + timing-summary reports, deployed arm, 102 builds
  impl_nondeployed/  same reports for the 18 non-deployed arms (see "Arms" below)
  csim/           golden-mode C-sim logs, 102 builds (Lenny)
  csim_filemode/  file-mode C-sim logs, rodent_max x 5 trainval sources x 17 W (Elle)
  csim_wext/      W = 28 / 32 probe C-sim logs (sweep-top justification)
results/
  metrics/raw/    board ESR / NMR / PEAQ scores, trainval (510) and test-segregated (204)
  metrics/matrices/  per-(model, source, W) matrices built from raw
  analysis/       Table 1 gap grid, per-source spans, held-out spans, Fig. 2 inputs
  hardware/       resources by width, placed utilization, campaign timing results, bitstreams zip
  hardware/records/  hash manifests, board/session manifests, verification verdicts, provenance
  training/grid_search/  train logs of the Sec. 3.1 hyperparameter grid (rodent 'moderate')
repro/        one-command golden-mode reproduction pack (Vitis HLS 2025.2)
docs/         design notes
MANIFEST.csv  path + MD5 for every tracked file
```

## Where each number in the paper comes from

| Paper item | Digits | Source of record in this repo | Re-derive with |
|---|---|---|---|
| Table 1 (mean span grid), per-model spans {+3,+4,+5,+3,+6,+4}, mean 4.2 | Sec. 4.1 | `results/analysis/check1_gap_grid.csv` | `scripts/gap_grid_REV2.py`; `scripts/verify_paper_claims_REV4.py` block [4b] |
| Per-source spans +2…+6, 29 of 30 defined | Sec. 4.1 | `results/analysis/check1_transparency_gap.csv` | `scripts/span_persource_REV6.py`; verifier block [4] |
| Test-segregated spans {+2,+3,+4,+3,+4,+3}, mean 3.2 | Sec. 4.1 | `results/analysis/heldout_srcmean_span_REV1.csv`, `span_heldout_REV5.csv` | `scripts/heldout_srcmean_span_REV1.py` |
| NMR vs GstPEAQ NMR, r = 0.997, −1.7 dB | Sec. 3.3 | `results/metrics/matrices/nmr_510.csv`, `results/metrics/raw/peaq_fleet_REV3.csv` (`total_nmr`) | verifier block [5] |
| Fig. 1 | Sec. 4.1 | `results/metrics/matrices/esr_510.csv`, `nmr_510.csv`, `odg_510.csv` | `scripts/make_fig1_public_REV1.py` |
| Fig. 2 (coherence, flatness, level correlation) | Sec. 4.2 | `results/analysis/errspec_T1T3_REV4_510.csv`, `errlevel_T5_REV2_510.csv` | `scripts/make_fig2_REV20.py` (MD5-gated inputs); verifier block [6] |
| Coherence < 0.5 at the NMR maximum; ESR ≥ −4 dB | Sec. 4.2 | same two CSVs + `esr_510.csv` | verifier block [6] |
| W = 24 as sweep top ("flattened at 23 bits") | Sec. 3.2 | `reports/csim/rodent_max_w2{1,2,3,4}_gru_va_csim.log`, `reports/csim_wext/` (W = 28, 32) | grep `ESR vs golden` |
| Golden-mode C-sim ≡ board, 102/102 | Sec. 3.3 | `results/hardware/records/b1_gate_results.csv`, `reports/csim/` | `scripts/b1_compare.py` |
| File-mode board ≡ C-sim, rodent_max, 5 trainval sources × 17 W = 85/85 | Sec. 3.3 | `records/anchor_filemode_equiv_music_REV2.csv` (68/68), `records/anchor_filemode_equiv_nam_REV1.csv` (17/17), `reports/csim_filemode/` | — |
| Kernel 140.5–142.5 cycles/sample, 14.6–14.8× RT; end-to-end 14.0–14.2× (Table 2 xRT) | Sec. 4.3 | `results/hardware/campaign_results.csv` (`cyc_hw`, `x_rt`, `fl_x_rt`) | `scripts/gen_grover_table_REV3.py` |
| Table 2 BRAM/FF/LUT/DSP | Sec. 4.3 | `results/hardware/resources_placed_by_width_REV1.csv`, `placed_util_per_build_REV1.csv`; per-build `reports/impl/*_utilization_placed.rpt` | `scripts/harvest_placed_util_REV2.py`; `scripts/verify_resources_REV2.py` (102/102 vs reports) |
| FuzzyLogic 'maximum' W = 19 → 20: +5k LUT, −5 DSP; W = 14 → 20: +6.6k LUT (12 % of device), −2 DSP, +1 BRAM | Sec. 4.3 | `results/hardware/resources_by_width_REV1.csv`; `reports/csynth/fl_max_w19_csynth.rpt`, `fl_max_w20_csynth.rpt` (Bind Op: 1 vs 2 DSP per multiply); `reports/impl/gru_L20_fl_max_w19_*`, `_w20_*` | — |
| ARM A9 RTNeural baseline 0.571× (Eigen) / 0.331× (STL) | Sec. 4.3 | `scripts/rtneural_arm_baseline_REV3.cpp`, `results/hardware/records/rtneural_arm_baseline_md5.txt`, `rtneural_c9_*_rerun_20260913.log` | on the board only |
| Training recipe (H = 40, lr 3e-3, TBPTT 2048, washout 1024, A-weighting pre-emphasis) | Sec. 3.1 | `models/<cell>/train_log.txt` (lr, pre-emphasis, TBPTT/washout in the cache tag); checkpoint shapes for H | `scripts/train_spike.py` |

`scripts/verify_paper_claims_REV4.py` runs blocks [1]–[6] from the CSVs above, then block [7] asserts every computed value against the submitted digits hard-coded at the top of the script (exit 1 on any mismatch). `verify_all.py` runs it as step 5 of the one-command repository check, together with the MANIFEST, report-count, artifact-MD5, bitstream-zip and Table 2 checks; its exit code is 0 only if all six steps pass:

```
python verify_all.py
python scripts/verify_paper_claims_REV4.py .
```

## Reproducing

* **Golden-mode C-sim (any machine with Vitis HLS 2025.2):** `repro/README.md`. Streams 4,096 synthetic samples through the kernel and compares against the PyTorch float32 golden; expected outputs and their hashes are in `repro/expected_golden.csv`.
* **Figures:** `make_fig1_public_REV1.py` (from `esr_510.csv`, `nmr_510.csv`, `odg_510.csv`) and `make_fig2_REV20.py` take their inputs as arguments, refuse to overwrite, and print the MD5 of each input against the artifact of record. The submitted Fig. 1 was rendered from the internal workbook by the same plot code; `make_fig1_public_REV1.py` carries that code verbatim over the released matrices and reproduces the same six selection gaps.
* **Table 2 from the reports:** `harvest_placed_util_REV2.py` reads `reports/impl/*_utilization_placed.rpt`; `verify_resources_REV2.py` checks the CSV against the reports.
* **Scores from board captures:** `hls_metrics.py` (ESR), `nmr_metric.py` + `score_xcell_nmr_REV2.ps1` (NMR-REV2), `score_peaq.py` (GstPEAQ 0.6.1, basic model), `score_heldout_esr_REV1.py` / `score_heldout_nmr_REV1.ps1` (test-segregated set). The board captures themselves (714 × ~36–116 MB) are not in the repository; every one is hash-listed (see "Not in this repository").
* **Float32 references:** `gen_cell_refs_REV2.py` (trainval refs) and `gen_cell_refs_REV3.py` (test-segregated refs) generate the y_f32 references from `models/<cell>/best.pt`; their hashes are in `results/hardware/records/float_refs_md5.txt`.
* **Weights → kernel:** `export_gru_weights.py` + `make_weights_header.py` turn `best.pt` into `hls/src/<cell>/weights.h`.

## Models

Six checkpoints of record, each with the run's `train_log.csv`, `train_log.txt` and `eval_log.txt`:

| repo | training run | pedal / setting |
|---|---|---|
| `rodent_max` | `rodent_max_v2` | Harley Benton Rodent, maximum |
| `rodent_mod` | `rodent_mod_v2c` | Rodent, moderate (trained on four of five sources; gtr2 excluded — time-base discontinuity) |
| `gt_max` | `greentint_max_v2` | Green Tint, maximum |
| `gt_mod` | `greentint_low_v2` | Green Tint, moderate (zero-drive setting) |
| `fl_max` | `fuzzylogic_max_v2` | Fuzzy Logic, maximum |
| `fl_mod` | `fuzzylogic_mod_v2` | Fuzzy Logic, moderate |

Checkpoints store a NumPy scalar alongside the state dict; on PyTorch ≥ 2.6 load with `torch.load(path, map_location='cpu', weights_only=False)`. Shapes: `gru.weight_hh_l0 (120, 40)` → H = 40; 5,201 parameters, matching `N_WEIGHTS` in `hls/src/gru_va.h`.

`train_spike.py`'s defaults are not the paper recipe; the recipe was passed on the command line: `--hidden 40 --lr 3e-3 --tbptt 2048 --washout 1024 --preemph aw`. Training used PyTorch 2.11.0 / CUDA 12.8. The `results/training/grid_search/` logs are the hyperparameter sweep on rodent 'moderate' (lr, hidden size, TBPTT, washout) that fixed those values.

## Arms (why `reports/impl_nondeployed` exists)

Every build was first implemented with default Vivado settings. Eighteen builds (all at W = 8, 21 or 22) failed timing at 100 MHz; each got a second placement arm with DSP-directed settings (`_dsp`, and where two were tried, `_dsp_best`). The arm that closed timing is the deployed one — column `arm` / `report_dir` of `results/hardware/resources_by_width_REV1.csv` — and its reports are in `reports/impl`. The failed base arms are kept in `reports/impl_nondeployed` for the record; no paper digit depends on them. Table 2's non-monotone LUT/DSP columns at W = 22 reflect this: from W = 22 the multipliers are implemented on two DSP48E1s each (DSP ≈ 130–135) and the fabric partial products disappear.

## Conventions

* **Paths.** Absolute paths from the development machines were replaced with placeholders before publication: `<REPO>`, `<GRU_DIR>`, `<EVIDENCE>`, `<NAS>`, `<BITGEN>`, `<HLS_SRC>`, `<HLS_IO>`, `<HLS_IO_HELDOUT>`, `<ELLE_HB>`, `<ELLE_HOME>`, `<VENV>`, `<USER_HOME>`, `<CODE_DIR>`. Tool project folders (`C:\hb\…`) and the PYNQ's own paths (`/home/xilinx/…`, `192.168.2.99`) were left as they are. Scripts that carried a hard-coded root now show the placeholder where it was; substitute your own.
* **Hashes.** `MANIFEST.csv` lists every tracked file with its MD5, computed by `make_manifest.py` on CRLF→LF-normalised bytes for files git treats as text and on raw bytes for the evidence trees; `verify_all.py` checks it the same way, so the check passes on Windows and Linux checkouts alike. Evidence trees (`reports/`, `results/`, `repro/`) are stored byte-exact (`.gitattributes` `-text`), so hashes computed on a clone equal the hashes of record. Four evidence files were path-scrubbed before publication and therefore hash differently from the raw field outputs: the two csynth reports the paper's DSP-binding sentence rests on (raw MD5 `1E050A47…` for W = 19, `494EDD6E…` for W = 20; scrubbed copies `2265BFD7…` / `AEB2A589…`), `results/analysis/errlevel_T5_REV2_510.csv` (raw `35A3CE3A…`, the value in the `errlevel_T5_REV2.py` header; scrubbed `5373026B…`, the value `verify_all.py` and `make_fig2_REV20.py` gate on) and `results/hardware/records/float_refs_md5.txt` (Elle reference paths replaced with `<ELLE_HB>`). Only the path columns changed; the raw copies are held offline with the evidence archive and are not in any commit of this repository.
* **REVs and sentinels.** Scripts carry a `_REVn` suffix and a sentinel line in their header; each output records the sentinel of the script that produced it. Only the REV that produced the submitted artifact is in this repository.
* **Machines.** `Lenny` = Windows workstation (training, HLS, Vivado, scoring); `Elle` = Linux box (file-mode C-sims, GstPEAQ); the PYNQ-Z2 is the board. Its clock was not NTP-synced, so timestamps inside `campaign_results.csv` and `session1_results.csv` (2025-05-…) are wrong; the campaign ran 2026-08-10 to 2026-08-15 and the test-segregated session 2026-09-05/06.
* **Sources.** Trainval program sources: gtr2, gtr4sg, prvtgtr, ytbass, nam. Test-segregated (never used in training): idmt-bass, idmt-gtr4-ib (`bass`, `gtr4ib` in filenames). nam was captured in its own board campaign (`board/gru_campaign_102_REV1.ipynb`); the four music sources plus the signal battery in Sessions 1–4 (`board/gru_board_session1_REV1.ipynb`).

## Verification chain (Sec. 3.3)

1. **Golden mode.** All 102 bitstreams reproduce the C-sim output of their build byte-identically on the board: `results/hardware/records/b1_gate_results.csv` (102/102).
2. **File mode.** For rodent 'maximum', full-length board outputs equal the Elle C-sim outputs byte-identically for the five trainval sources × 17 word-lengths (85/85): `anchor_filemode_equiv_music_REV2.csv` + `anchor_filemode_equiv_nam_REV1.csv`. The two test-segregated sources have no C-sim twin; they were scored on silicon only.
3. **Repeatability.** The nam captures of 2026-08-10 and the Session-4 captures of 2026-08-15 were hashed against each other (85/85, recorded in the session summaries); the RTNeural ARM baseline rerun of 2026-09-13 reproduced the 2026-08-17 outputs byte-identically.

## Not in this repository

* The 714 board output captures and the 42 float32 references (~30 GB). Hash lists: `session1_results.csv` (`out_md5`, 408 music rows), `campaign102_nam_verified_manifest.csv` (102 nam), `heldout_md5.txt` + `verified_manifest.csv` (204), `float_refs_md5.txt` (42 refs).
* The internal test workbook the analysis was banked in. The public record is the raw CSVs and matrices; nothing in the paper depends on the workbook.
* The RTNeural library source used for the ARM baseline (`rtneural_src.tgz`, 11 MB) — see the harness header for the version and build line.
* The ToneTwist AFX dataset (Comunità, Steinmetz, Reiss, 2025; MIT license) — obtain it from its authors.

## Toolchain

Vitis HLS 2025.2, Vivado 2025.2, PYNQ-Z2 (xc7z020, PYNQ image), PyTorch 2.11.0 / CUDA 12.8, GstPEAQ 0.6.1, Python ≥ 3.11.

* **Python for the verifiers and figures:** `pip install -e ".[repro]"` (numpy, matplotlib, openpyxl; `verify_all.py` and `verify_paper_claims_REV4.py` need only numpy). Training and weight export additionally need the base dependencies (torch, scipy, soundfile): `pip install -e .`.
* **GstPEAQ 0.6.1** is a system dependency (GStreamer plugin), not a Python package. `score_peaq.py` drives `gst-launch-1.0 peaq` with `--rate 48000 --lowpass 20000` (8-pole `audiocheblimit` low-pass on both pads, basic model); every row of `results/metrics/raw/peaq_fleet_REV3.csv` records `rate=48000, lowpass=20000` and the scorer sentinel.

## License

The code and data in this repository are released under the MIT License (see `LICENSE`, © 2026 Hope Sheffield). The ToneTwist AFX dataset is © 2025 Marco Comunità, MIT License. RTNeural is © Jatin Chowdhury, BSD-3-Clause.
