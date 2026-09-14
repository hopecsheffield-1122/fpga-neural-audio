# Golden Reproduction Pack — Fixed-Point GRU Audio Effect Kernel

**Purpose:** reproduce, on your own machine, the fixed-point C-simulation
result for any bit-width (8–24) of the anchor model (Harley Benton Rodent,
maximum gain) and verify it byte-for-byte against the recorded output. The
recorded hash is simultaneously the campaign's C-simulation export **and**
the FPGA board capture: the two were verified identical for all 102
(model, width) builds on 2026-08-10.

## Requirements
- Vitis HLS 2025.2 (Windows). Default path assumed:
  `C:\AMDDesignTools\2025.2\Vitis\bin\vitis-run.bat` — if yours differs,
  edit the `$VitisRun` line at the top of `run_repro.ps1`.
- Python 3 on PATH (standard library only; no packages).
- **Clone or extract to a path without spaces** (e.g. `C:\repro_pack`).
  Vitis HLS rejects project paths containing spaces.
- **Downloaded zip only:** right-click → Properties → **Unblock** before
  extracting, or run `Get-ChildItem <pack> -Recurse -File | Unblock-File`
  on the extracted folder. Not needed for a git clone.

## Run (one command)
From PowerShell, in this pack's directory:

    .\run_repro.ps1 -Width 20

Any width 8–24. Runtime ~2–3 minutes (C simulation of the deployed kernel
on the 4,096-sample golden test vector, then automatic verification). The
runner refuses to start if `out\golden_repro_w<W>.f32` already exists, and
refuses to verify if the simulation did not complete.

## What you will see
1. The compile line is printed — the same flags as the 102-build campaign
   (`-DP_COLS=40 -DALLOC_MAC3_LIMIT=20`, W-bit weights `<W,5>`, activations
   `<W,2>`, accumulators `<32,12>`, convergent rounding).
2. `repro_verify.py` prints:
   - **MD5 this run** — hash of the output your machine just produced
   - **MD5 certified** — the recorded hash (C-simulation export = board capture)
   - **VERDICT: MATCH / MISMATCH**
   - the recorded digits for that width (cosine, error-vs-reference in dB)
     and the testbench's own metric lines from this run, for comparison.
3. `testdata\golden_testdata.csv` lists the dry stimulus and the float32
   reference sample-by-sample — the same values as the two `.bin` files.
4. `out\golden_repro_w<W>.csv` is written beside the binary output: one row
   per sample with `sample, input, golden_fp32, fixed_output, error`.

**Interpretation:** a MATCH means the output generated on this machine is
byte-identical to what the deployed FPGA produced for this width.

## Expected results
`expected_golden.csv` lists all 17 widths with recorded cosine, ESR (dB vs.
the float32 reference), RMSE, testbench gate verdict, and the certified
hash. At widths below 14 the testbench's cosine gate reports FAIL by
design — the degradation is the measurement — and those runs still MATCH
their recorded hashes.

Verified from this pack:

| Date | Width | Kernel MD5 | Dump MD5 | Verdict |
|---|---|---|---|---|
| 2026-08-21 | 20 | A0CC9D7C72869F6E112A6BD5013229FC | 8d0489e52ed4eb0fa86ccf516965a720 | MATCH |
| 2026-09-10 | 19 | 018DADB53BD63BE08CF4E938F4049616 | e2838d05dbb213bf09bf6b0296bbbe19 | MATCH |
| 2026-09-10 | 11 | 018DADB53BD63BE08CF4E938F4049616 | b57cd20d71a300033b2c1d7892a27ded | MATCH |

## Scope note
This pack reproduces the golden-vector (4,096-sample) result end-to-end in
minutes; the golden-vector C-sim/FPGA identity holds for all 102 builds.
The full-length program-source results reported in the paper are a
different, larger set: 510 trainval points (6 models × 5 sources × 17
widths) plus 204 test-segregated points. Their coverage is narrower than
this pack's, and is stated exactly:

- **Full-length C-sim ≡ FPGA, demonstrated:** rodent 'maximum' only, five
  trainval sources × 17 widths = 85 captures, byte-identical to the Elle
  file-mode C-sims (9–14 h per run). Records:
  `results/hardware/records/anchor_filemode_equiv_music_REV2.csv` (68/68)
  and `anchor_filemode_equiv_nam_REV1.csv` (17/17); logs in
  `reports/csim_filemode/`.
- **Silicon captures only:** the remaining 425 trainval points and all 204
  test-segregated points were scored from board outputs. They are tied to
  this pack through the campaign/provenance chain (bitstream hashes,
  per-capture MD5 manifests, session manifests in
  `results/hardware/records/`), not through a full-length C-sim twin. The
  two test-segregated sources have no C-sim twin at all.

## Pack contents & provenance
| File | Role | MD5 |
|---|---|---|
| src/gru_va_col_fused_mac3.cpp | deployed kernel | 018DADB53BD63BE08CF4E938F4049616 — differs from the synthesized source (A0CC9D7C72869F6E112A6BD5013229FC) only in comments and in the `P_COLS` default (20 → 40, unused because the build passes `-DP_COLS=40`); identical after preprocessing under the campaign flags; MATCH at W=19 and W=11 above |
| src/gru_va.h | fixed-point type declarations | 77C589842851D672496C39BBB450A315 |
| src/gru_load.cpp | weight loader (mode 0) | 4505FFD7BF6BFF304ACFB38E6C8322A2 |
| src/gru_weights.h | weight declarations | 817B0A7716AA5A733D6B8859E698EEC3 |
| src/weights.h | compiled weights, rodent_max_v2 checkpoint | A83A81382D4506322AA31E241AD2DC30 |
| src/tanh_table.h | 1025-entry tanh table | 8179555888E29B34A6688DF519FF312E |
| src/gru_va_tb_fm2.cpp | testbench (golden + file modes) | 4E52E54C828614F70AB40CF3C60FCC81 |
| testdata/golden_input.bin | golden dry stimulus, 4,096 samples float32 | 607F8F6FBF8D191B8B35C264A665A829 |
| testdata/golden_output.bin | float32 model reference | 0B2625DD8252AA87417179E40798B2A5 |
| testdata/golden_testdata.csv | the same two files in readable form | generated by export_testdata_csv.py |
| expected_golden.csv | recorded digits + hashes, 17 widths | — |
| repro_golden.tcl | build + csim script (REPRO-GOLDEN-REV2) | — |
| run_repro.ps1 | one-command runner (REPRO-RUN-REV3) | — |
| repro_verify.py | verifier (REPRO-VERIFY-REV1) | — |
| dump_csv.py | per-sample CSV exporter (REPRO-CSV-REV1) | — |
| export_testdata_csv.py | testdata CSV exporter (REPRO-TDCSV-REV1) | — |
| build_expected.py | builds expected_golden.csv from the campaign records (run once on the authors' machine; kept for provenance, not runnable elsewhere) | — |

The testbench's checks (cosine gate, error-vs-reference, worst-sample
tracking) are unchanged since 2026-07-15; the current revision added a
file-streaming transport path with the scoring logic carried verbatim.
