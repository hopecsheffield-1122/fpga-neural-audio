import hashlib, os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.utils import get_column_letter

SENTINEL = "TRACK-REVCHG-20260905-REV4"
OUT = "/mnt/user-data/outputs/change_tracker_REVCHG-20260905_REV4.xlsx"
if os.path.exists(OUT):
    raise SystemExit("fail-if-exists: " + OUT)

# id, source, section, type, status, item, facts/notes, artifact/record, gate, sub-status detail
# Sources: REVCHG = change list 9/5; RP = Remaining-pass notes; R4 = ICASSP-style review (48e2b816)
# Types: Writing / Verify / Compute / Decision / Mechanical / Reference
rows = [
# --- REVCHG 1 : III-D PEAQ/NMR implementation
("1.1","REVCHG 1","III-D","Writing","Landed","GstPEAQ 0.6.1 [29], Basic, 48 kHz mono, raw-f32, 20 kHz LP; NMR frame/band parameters","Present in draft","SCORE-PEAQ-REV2; NMR-REV2 nmr_metric.py 3098CB25",""),
("1.2","REVCHG 1","III-D","Writing","Open","Reason for 20 kHz LP","0.6.1 bandwidth MOV divides by zero when the top octave is not quiet","SCORE-PEAQ-REV2",""),
("1.3","REVCHG 1","III-D","Writing","Open","Noise pattern not spread (design choice)","noise pattern = (|R|-|T|)^2 per band, not spread; state as design choice","NMR-REV2",""),
("1.4","REVCHG 1","III-D","Writing","Open","NMR validation digits","identity -120 dB; linearity 20.02/20.00 dB steps; masking margin 72 dB; vs GstPEAQ Total NMR: rank order 5/5, hump width 5/5, offsets +/-3 dB width-constant","NMR-REV2 validation record",""),
("1.5","REVCHG 1","III-D","Reference","Open","Cite [12] on parameter sentence, [11] on NMR concept","Neither cited in III-D currently; [29] now cited","",""),
("1.6","REVCHG 1","III-D","Writing","Open","'20 kHz LP on both pads' - typo","Record: both reference and test signals low-passed","",""),
("1.7","REVCHG 1","III-D","Writing","Open","'Basic' as BS.1387 model name (capitalized)","","",""),
# --- REVCHG 2 : III-D reference = float32
("2.1","REVCHG 2","III-D","Writing","Landed","Same dry input; Rodent mod vs held-out gtr2","Present in draft","",""),
("2.2","REVCHG 2","III-D","Writing","Open","Wet recording (training target) never enters the metric","e_W[n] = y_W[n] - y_f32[n]","",""),
("2.3","REVCHG 2","III-D","Writing","Open","All six models scored on the same five inputs","Cross-model comparisons on identical content","",""),
("2.4","REVCHG 2","III-D","Writing","Open","gtr2 out-of-training evidence","Rodent mod span on gtr2 = +4; training sources +4,+4,+4 (ytbass +5); coherence within 0.03, flatness within 0.05 at every width","FIG2-RMOD4SRC-REV1 R1/R2 PASS",""),
("2.5","REVCHG 2","III-D","Writing","Open","'wet outputs y_W[n]' wording","y_W is the quantized output; 'wet' = training-target recording in III-A. Two meanings for one word","",""),
# --- REVCHG 3 : IV-A
("3.1","REVCHG 3a","IV-A","Writing","Open","Per-source span sentence (after 4.2 sentence, before table)","30 (model,source) pairs; 29 defined, all positive; +2 to +6; mean +3.9; within-model spread 1-3 bits; ytbass widest in 4/6","span_persource_REV1.csv 789 B 59BB9B44",""),
("3.2","REVCHG 3a","IV-A","Writing","Open","Undefined pair: FuzzyLogic max / nam","ESR passes W=15; ODG max -0.54 at W=24; span > +9; source mean crosses at W=20 only because other four do","span_persource_REV1.csv",""),
("3.3","REVCHG 3b","IV-A","Writing","Open","'Operating point' wording on the (tau, theta) sentence","Literature-motivated operating point; not a transparency threshold; nothing reads as 'we established the perceptual threshold'","",""),
("3.4","REVCHG 3c","IV-A","Writing","Open","[4]/[27] context clause","[4]: model vs device; here quantized vs float32. [27]: DAB+ codec context. One clause: both values carried from original contexts; the sweep is the response","",""),
("3.5","REVCHG 3","IV-A","Writing","Open","Paragraph reorder","definitions > literature ranges > operating point + context clause > six spans and 4.2 > per-source > table as sensitivity > 14/15. Draft currently has table before spans","",""),
# --- REVCHG 4 : IV-B
("4.1","REVCHG 4","IV-B","Writing","Open","Finding 1 -> coherence only","Drop 'temporal placement': GreenTint rho_L crosses zero at W=10/12 with no hump","ERRSPEC-T1T3-REV4; T1 verdict",""),
("4.2","REVCHG 4","IV-B","Writing","Open","Finding 2 -> 'level placement'","Draft says 'temporal placement'; record says spectral structure and level placement in addition to energy","",""),
("4.3","REVCHG 4","IV-B","Writing","Open","Spectral parameters","Welch 4096-point Hann, 50% overlap; coherence and flatness averaged 100 Hz-16 kHz; source mean = mean of five per-source scalars; rho_L frames 2048, no window (already stated)","ERRSPEC-T1T3-REV4 errspec_T1T3_REV4_510.csv 6DB94D68",""),
("4.4","REVCHG 4","IV-B","Writing","Open","'Coincident' - never 'causes' or 'precedes'","T1: transition at or 1-2 bits above the hump; no re-correlation at ceiling","T1 verdict",""),
("4.5","REVCHG 4","IV-B","Reference","Open","Unnumbered citations in IV-B","Welch 1967; Carter 1973; Gray & Markel 1974; Bosi & Goldberg - none in the 32-entry list","",""),
# --- REVCHG 5 : IV-C
("5.1","REVCHG 5","IV-C","Writing","Open","DSP48E1 operand width","Draft: '18-bit operand exceeds'. Record: 20-bit operand exceeds 18-bit port at W=20; one DSP per multiply retained; partial product in fabric","",""),
("5.2","REVCHG 5","IV-C","Verify","Open","W=19 LUT/DSP pair in the sentence","Draft: 'W=19 ~19.7k LUT DSP 76'. csv: W=19 = 19,618/75 (Rodent max), 19,605/73 (FL mod); DSP 76 is GreenTint mod W=16","resources_by_width_REV1.csv",""),
("5.3","REVCHG 5","IV-C","Writing","Open","Latency unit and population","Cycles per sample, golden run; csynth SAMPLE_LOOP latency - 2.48 = 140.5-142.5 cycles at 100 MHz; throughput = file mode incl. DMA/host (~149 cycles/sample, 14.0-14.2x)","",""),
("5.4","REVCHG 5","IV-C","Writing","Open","Resource-cost join w_ESR -> w_ODG (per cell)","Rmax 16>19 +1.1k LUT; Rmod 14>18 +1.0k; GTmax 13>18 +1.7k; GTmod 13>16 +1.2k; FLmax 14>20 +6.6k (12%), BRAM 5>6; FLmod 15>19 +1.4k. Throughput 14.0-14.2x at both; none reach w21-22 cascade","resources_by_width_REV1.csv",""),
("5.4a","R4 sec.7 / REVCHG 5","IV-C","Decision","Open","Table II format: replace max columns / add second table / text only","Table II currently reports LUT (max) and DSP (max) across models per width (cross-model maxima); R4 sec.7 says selection consequence must use per-model build results. Any of the three formats satisfies it if numbers are per-model. Note: current 6-row Table II is the Grover-accepted row culling - replacing it touches a merge-log item","resources_by_width_REV1.csv",""),
("5.5","REVCHG 5","IV-C","Writing","Open","ARM baseline to two sentences","'on-device Cortex-A9 (Zynq PS) baseline'; 0.571x Eigen/NEON, 0.331x STL; Grover-accepted, keep","",""),
("5.6","REVCHG 5","IV-C","Mechanical","Open","Throughput table spacer rows","Empty rows between 8/12/16/20 in the docx table","",""),
# --- REVCHG 6 : III-C
("6.1","REVCHG 6","III-C","Writing","Open","'Per-bit gain' defined; 'observed plateau' not 'verified'","ESR improvement per bit; ladder w20 -73.70 / w21 -80.66 / w22 -82.13 / w23 -87.42 / w24 -87.88 / w28 -90.71 / w32 -89.96 dB; <1 dB/bit beyond W=23","csim golden vector rodent_max","GATE: WEXT-ACC40-REV2 rows banked"),
("6.2","REVCHG 6","III-C","Writing","Open","'Bit-identical' scope","Golden-run output stream 16,384 B MD5 4C8CD0F5 at W=28, <32,12> vs <40,20>; integer headroom only (same 20 fractional bits); not exoneration of the accumulator","golden_wext_w28_acc40_REV2.f32","GATE: WEXT-ACC40-REV2 rows banked"),
("6.3","REVCHG 6","III-C","Verify","Open","Confirm WEXT-ACC40-REV2 workbook rows banked before 6.1/6.2 digits enter III-C","","workbook",""),
# --- REVCHG 7 : II
("7.1","REVCHG 7","II","Writing","Open","Gate dependency chain","r_t and z_t independent (concurrent); n_t depends on r_t; h_t depends on z_t and n_t. Draft has the three U*h products independent and no cross-sample overlap - chain missing","",""),
# --- REVCHG 8 : Intro
("8.1","REVCHG 8","I","Writing","Open","GRU waveform sentence attribution","Property of sample-wise recurrent models on the waveform (no explicit time-frequency decomposition) [6],[7], not 'the GRU'","",""),
("8.2","REVCHG 8","I","Writing","Open","MUSHRA sentence","Scaling argument: BS.1534-3 <=12 stimuli/trial incl. hidden ref and anchors, ~10 s items; sweep does not scale to exhaustive listening. 'stimuli' not 'samples'. Drop 'cannot practically precede'","[31]",""),
# --- REVCHG 9 : Contributions / abstract
("9.1","REVCHG 9","I","Writing","Open","Contribution order and content","(1) direct comparison of energy- and masking-based criteria for fixed-point bit-width selection across six models; (2) 4.2 at operating point, 14/15 threshold pairs, 29/29 per-source; (3) on-silicon: all 102 builds reproduce golden C-sim byte-identically; full-program identity all widths/sources for Rodent max only; >=14.0x","",""),
("9.2","REVCHG 9","Abstract","Writing","Open","Abstract fixes","'evaluated six times at different weights' (also Intro para 6) -> six independently trained weight sets; drop 'calibration configuration'; state operating point and 4.2 with 14/15","",""),
("9.3","REVCHG 9","Abstract","Writing","Open","'+4.2 bits below' sign/direction","Direction correct (ESR below ODG); '+' is the IV-A span convention, not a direction","",""),
# --- REVCHG 10
("10.1","REVCHG 10","Fig. 1","Mechanical","Open","Re-render Fig. 1","make_results_figs_REV2.py 90160EA6; A4 suptitle removed; replace fig1.pdf in LaTeX build","FIGGEN-VA-VB-VC-REV2",""),
# --- Remaining-pass notes
("RP.1","RP 1","IV-C","Writing","Open","FuzzyLogic max worked example (exception, not rule)","+6 span; 14>20; +6.6k LUT (12%); DSP 72>70; BRAM 5>6; nam never reaches -0.5. Keep 'ODG-demanding', not 'masking-demanding'. 5/6 cost 1.0-1.7k LUT and <=7 DSP","span_persource_REV1.csv; resources_by_width_REV1.csv",""),
("RP.1a","RP 1","IV-C","Verify","Open","Pull four defined FL max per-source spans","So the sentence can give the range, not just the undefined pair","span_persource_REV1.csv",""),
("RP.2","RP 2","III-D","Writing","Open","PEAQ domain-validity clause","PEAQ validated on codec artifacts; cite BS.1387 [12] own scope. Do NOT write 'NMR and PEAQ agree on divergence direction' (not banked). Record supports: NMR re-violates inside ESR pass band; NMR divergence is structural","evaluation_methodology.md sec.1",""),
("RP.2a","RP 2","Refs","Decision","Open","Add Torcoli, Kastner & Herre 2021 (TASLP, arXiv:2110.11438) as [33]?","NMR near top in cross-domain correlation with listening scores. New reference; page budget","",""),
("RP.3","RP 3","IV-A or III-D","Writing","Superseded","Selection uses plain ESR -- SUPERSEDED by AW decision 2026-09-06","Decision 2026-09-06: A-weighted ESR drives selection (consistency with training loss and [4]); plain ESR reported in one sentence only. See AW block","",""),
("RP.3a","RP 3","Workbook","Verify","Closed","Confirm ESR column in scoring workbook / board_nam_metrics.csv is plain ESR","hls_metrics.py basic_metrics line 72: plain 10log10(sum err^2/sum ref^2), no filter on ESR path; K-weighting only in lufs_integrated. 510 ESR of record = plain (2026-09-06)","board_nam_metrics.csv F6368AE6",""),
("RP.4","RP 4","IV-C","Verify","Open","W=19 vs W=20 DSP48E1 mechanism","Both multiplicands are W bits; 19-bit already exceeds 18-bit port, so port width alone does not explain no jump at W=19. Read Vivado synth/utilization reports for W=19 and W=20 builds; else keep sentence empirical and drop causal clause","M:\\hope\\bitgen\\reports\\",""),
# --- R4 (ICASSP-style review) - writing items
("R4.B1","R4 B1","Abstract / V","Writing","Open","Reference condition (float32 output, not pedal) in abstract and conclusion","Currently III-D only","",""),
("R4.B2","R4 B2","III-A/III-D","Writing","Open","Training/evaluation partition stated","Segment-level split; source identities overlap training except Rodent mod/gtr2; scope = six trained instances x five sources; held-out arm reported separately","HELDOUT-PREREG-REV1 0DCC6B52",""),
("R4.B3","R4 B3","IV-B","Writing","Open","Fig. 2 residual != NMR noise pattern","Fig. 2 analyzes waveform e_W = y_W - y_f32; NMR-REV2 uses (|R|-|T|)^2 per band; (|R|-|T|)^2 != |R-T|^2. One clause","",""),
("R4.B4","R4 B4","II or III-D","Decision","Open","ODG is a multi-MOV composite, not a masking measurement","PEAQ Basic ODG maps eleven MOVs (Total NMR is one) through a NN [12]. Option a: keep title, add one clause; option b: retitle (reopens 9/3 decision)","[12]",""),
("R4.B5","R4 B5","III-D","Writing","Open","GstPEAQ conformance clause","[12] = BS.1387-2 (May 2023); GstPEAQ docs state non-conformance to standard tolerances; scores are implementation-specific (GstPEAQ 0.6.1 Basic)","[12],[29]",""),
("R4.B6","R4 B6","IV-C","Writing","Open","Line 154 'attributes each quality change to bit-width alone' + latency inference","Controls of record: fixed weights per sweep; specified numerical changes; HW = C-sim byte identity. Sweep changes weights, datapath, table-value precision together; table structure + accumulator fixed -> 'plateau under the evaluated numerical configuration'","",""),
("R4.B7","R4 B7","III-D / IV-A","Writing","Open","ESR dB formula stated; aggregation order stated","Mean of five per-source dB scalars vs pooled energies differ; name which","","GATE: R4.B7a"),
("R4.B7a","R4 B7","Workbook","Verify","Open","Confirm aggregation used for ESR/ODG/NMR source-mean curves","ERRSPEC uses mean-of-scalars; confirm same for the Fig. 1 source means","scoring workbook 5C8F32BE",""),
("R4.B8","R4 B8","IV-A","Writing","Open","Two-estimand statement","Source-mean crossing ({+3,+4,+5,+3,+6,+4}, 4.2) vs mean of per-source crossings (+3.9, 29/29). Name which is which; 4.2 != 3.9 is the demonstration","span_persource_REV1.csv",""),
("R4.B9","R4 B9","IV-B","Writing","Open","Flatness and rho_L wording","'how flat or concentrated the spectrum is' not 'noisy or tonal' (line 138); negative rho_L = inverse level association, no audibility inference","",""),
("R4.B10","R4 B10","Fig. 1 caption","Writing","Open","Fig. 1 caption clarification","ESR and NMR share a dB axis but are differently normalized; intersections carry no meaning; shading = threshold-crossing widths, not vertical separation. Optional ESR guide line = FIGGEN REV3","",""),
("R4.B11","R4 B11","Refs","Reference","Open","[29] author line","DAFx-15 proceedings: Holters and Zolzer, not Ahrens. Verify against the PDF at the dafx.de link, then fix","[29]",""),
# --- R4 compute / decision items
("R4.C1","R4 C1","IV-A","Decision","Open","6x5 D_{m,s} table or heatmap","Data exists. Cost: figure/table gen + ~1/3 column. Include W_ODG and W_ESR per cell at least in accompanying data. Two reviewers asked","span_persource_REV1.csv",""),
("R4.C2","R4 C2","IV-B","Decision","Open","Adjacent-width trend disagreement intervals","dESR<0 and dNMR>0 per (model,source) with disclosed tolerance. New script ~1 h; inputs = existing 510-row ESR + NMR-REV2. No leakage into deferred BGEXT adjudication. Two reviewers asked","scoring workbook",""),
("R4.C3","R4 C3","IV-A","Decision","Open","Leave-one-source-out sensitivity on source-mean crossing","6 models x 5 drops = 30 recomputations; same script family as SPAN-PERSRC; ~1 h","scoring workbook",""),
("R4.C4","R4 C4","IV-B","Decision","Open","Gain/collapse diagnostic","a_W = <y_W,y_f32>/<y_f32,y_f32> over 510 captures; coherence of gain-removed residual. Gives 'collapse' an operational definition. Needs board captures (NAS); ~half day incl. banking","board captures (NAS archive)",""),
("R4.C5","R4 C5","III-C","Decision","Open","Fractional-precision accumulator csim <40,12> at W=28","This is the 'fraction arm' currently post-submission. One csim, one solution dir, typedef line recorded. Without it plateau claim narrowed per R4.B6. Pre- or post-submission","golden vector rodent_max",""),
# --- AW block: A-weighted ESR decision 2026-09-06
("AW.0","Decision 9/6","IV-A","Verify","Open","[4] anchor: is the -20 dB 'excellent' band on A-weighted or plain ESR?","Record (evaluation_methodology.md) says [4] reports plain and pre-emphasizes only the loss; Hope's read is A-weighted. Check the [4] results table / metric definition. If plain: tau on AW-ESR needs its own justification or [4] drops from that sentence","[4] PDF",""),
("AW.1","Decision 9/6","Data","Compute","Open","Run esr_aw_rescore_REV2.py --selftest on Lenny","FIR 511 taps md5 415A9DE2 (IEC 61672 checks 100/1k/4k/10k Hz OK; conv1d equivalence 0 diff)","esr_aw_rescore_REV2.py D1DFBA28 11,784 B (REV1 AA6FBB87 superseded after code review)",""),
("AW.2","Decision 9/6","Data","Compute","Open","Build manifest CSV cell,source,width,out_path,ref_path for all 510 pairs","Needs the (cell,source,width) -> capture path map and the f32 reference per (cell,source). Directory listing of M:\\hope\\gru_full_20260822 / board_* / cellrefs_pull pending","M:\\hope\\","GATE: AW.1"),
("AW.3","Decision 9/6","Data","Compute","Open","Export workbook plain ESR column to CSV cell,source,width,esr_db (reconciliation input)","From week_test_book_20260829_REV1.xlsx (68A895F0)","workbook of record",""),
("AW.4","Decision 9/6","Data","Compute","Open","Run rescore -> esr_aw_510_REV1.csv; reconciliation gate PASS","REV2 gates: unique keys; key set == workbook set; --expect-rows 510; missing file fatal; equal lengths; finite inputs/results; CSV written only after all gates. Values at 6 decimals. Record bytes+MD5","esr_aw_510_REV1.csv","GATE: AW.2, AW.3"),
("AW.5","Decision 9/6","Workbook","Mechanical","Open","Bank esr_aw_db as new sheet; annotate plain sheet 'superseded for selection 2026-09-06'; new workbook REV","Annotate-never-delete. Log as post-registration metric change (reason: training-loss consistency)","workbook REV2","GATE: AW.4"),
("AW.6","Decision 9/6","Held-out","Compute","Open","Rescore held-out arm (204 captures) A-weighted; re-adjudicate H1-H5","H1-H4 were pre-registered on plain ESR. Log verdict changes as findings","HELDOUT-PREREG-REV1; board_heldout_2026-09-06","GATE: AW.4"),
("AW.7","Decision 9/6","IV-A","Compute","Open","Rerun SPAN-PERSRC on AW column -> spans, 4.2 digit, 29/29, Table I (15 cells)","All ESR-derived digits move; new values unknown until AW.4","span_persource_REV5.py (or REV6 with AW input)","GATE: AW.5"),
("AW.8","Decision 9/6","Fig. 1","Mechanical","Open","Regenerate Fig. 1 with AW-ESR curves (FIGGEN REV3)","Six panels; ESR curve, shading, labels all move","make_results_figs_REV2.py -> REV3","GATE: AW.5"),
("AW.9","Decision 9/6","IV-C","Compute","Open","Recompute resource-cost join w_ESR -> w_ODG with AW-selected w_ESR (5.4)","w_ODG unchanged; w_ESR per cell changes","resources_by_width_REV1.csv","GATE: AW.7"),
("AW.10","Decision 9/6","Prose","Writing","Open","Prose that moves: abstract, contributions 2-3, IV-A spans/4.2/Table I text, IV-C join, V conclusion, held-out digits","Also III-D/IV-A: define AW-ESR = ESR on A-weighted (511-tap FIR, IEC 61672, 0 dB at 1 kHz) reference and output, same filter as training loss; one sentence reports plain ESR","","GATE: AW.7"),
("AW.11","Decision 9/6","II / IV-A","Writing","Open","Framing: ESR carries a frequency weighting","'Energy-based' now = A-weighted energy; state it once; title unchanged unless Hope decides otherwise","",""),
("AW.12","Decision 9/6","Refs","Decision","Open","Cite the A-weighting source","IEC 61672 (weighting curve) and/or Wright & Valimaki 2020 perceptual-loss paper for the pre-emphasis choice; check whether either is already in the list","",""),
("AW.13","Code review 9/6","III-D / IV-A","Writing","Open","Describe the filter as a 511-tap FIR approximation to IEC 61672 A-weighting, identical to the training pre-emphasis -- not as a conformant implementation","FIR vs analytic A curve: 200 Hz -0.13, 125 Hz +0.25, 100 Hz +0.91, 82.4 Hz +1.90, 63 Hz +4.03, 50 Hz +6.65 dB (reproduced 2026-09-06). Accurate above ~125 Hz; under-attenuates below. Rationale for keeping it = training-loss consistency","a_weighting_fir taps md5 415A9DE2",""),
("AW.14","Code review 9/6","Code","Mechanical","Open","train_spike.py PreEmph docstring says 255-tap; code uses 511 (default)","Fix docstring before any code release; note in training log","train_spike.py 7B7AA588",""),
("AW.15","Code review 9/6","Held-out","Compute","Open","Held-out rescore uses --expect-rows 204","Same script; key set = 6 cells x 2 sources x 17 widths","board_heldout_2026-09-06","GATE: AW.4"),
# --- closed items
("X.1","Ledger","III-B","Verify","Closed","RTX 5070 Laptop GPU stands","Six certified weight sets trained on Lenny (July); Elle runs were Hard* from-scratch arm (scratch_hard_s0/s1, launched 2026-08-11), not in paper","session_summary_2026-08-11/12-13",""),
("X.2","Ledger","III-C","Writing","Closed","'All implementations of ap_fixed... convergent rounding'","Reads as the resolved 'All three' sentence","",""),
("X.3","Ledger","III-B","Verify","Open","PyTorch 2.11.0 / CUDA 12.8 line from training log, not current venv","Only if July runs used an earlier torch build","training log",""),
]

declined = [
("REVCHG","Listening test around the disagreement region","Paper is metric-vs-metric by standing decision (no human audibility claims); not modest in cost; future-work sentence only"),
("REVCHG","Held-out sources as paper prerequisite","Accepted as an arm (item 2), scheduled 9/6; reported separately"),
("REVCHG","Mechanism-led framing (correlated -> noise-like -> less masked -> more bits)","Record supports coincidence, not causation (T1 verdict)"),
("REVCHG","Title 'Energy- vs Perceptual-Metric'","NMR and PEAQ are masking-threshold metrics; 'masking-based' is the deliberate 9/3 choice. See R4.B4 for the ODG-composite clause"),
("REVCHG","Dropping the Cortex-A9 paragraph","Reduced 9/3 to one paragraph; Grover-accepted"),
("REVCHG","'Collapse/improvement/ceiling' regime names","Rename or define; ceiling regime C (W>=22) is a pre-registered T2 window boundary, not a visual knee. R4.C4 would define 'collapse'"),
("RP","'NMR and PEAQ agree on the divergence direction' as the validity defense","Not a banked finding. Use: NMR re-violates inside ESR pass band; NMR divergence structural"),
("R4","Suggested abstract, limitation statement, title text","Pangram rule; facts inside are consistent with record and already in REVCHG 9"),
("R4","Shorten GRU/parallelism exposition","Conflicts with REVCHG 7 only in length; the chain is one sentence. Page effect is Hope's call"),
("R4","Float-model fidelity report vs pedal","Reviewer says not required; consistent with standing scope"),
]

artifacts = [
("Draft docx (uploaded 9/5)","9ca73ce2bd1c1a27d2525089e654166a","91,399"),
("REVCHG-20260905-REV1 change list","(inline document)",""),
("Remaining-pass notes","(inline document)",""),
("ICASSP-style_recommendation_borderl.txt","48e2b816d7aecc4c2e8392f93b97e15e","22,729"),
("span_persource_REV1.py (SPAN-PERSRC-REV1)","AEA212570C0DC6FC3C8765389E6FC60F","5,813"),
("span_persource_REV1.csv","59BB9B4422541BAD78B6E59FDFA801F3","789"),
("HELDOUT_PREREG_REV1.txt","0DCC6B5296C9611B46A494D3D8B3E230","2,686"),
("make_results_figs_REV2.py","90160EA690FEC49A13DBC639C7153F9F","22,715"),
("paper.pdf (9/5 LaTeX build)","ACCF7F93908A57A592DB210C46A92954",""),
("golden_wext_w28_acc40_REV2.f32","4C8CD0F5...","16,384"),
("errspec_T1T3_REV4_510.csv","6DB94D68...","147,109"),
("nmr_metric.py (NMR-REV2)","3098CB25...",""),
("board_nam_metrics.csv","F6368AE6...",""),
("scoring workbook (SPAN-PERSRC input)","5C8F32BE...",""),
("train_spike.py (uploaded 9/6)","7B7AA5887FED6BDB648AD38C627FD3BB","16,182"),
("esr_aw_rescore_REV1.py (ESR-AW-REV1) SUPERSEDED","AA6FBB8714E11611F0B12AFDDE440071","9,577"),
("esr_aw_rescore_REV2.py (ESR-AW-REV2)","D1DFBA28757CE44CC0E5AA92D76367F9","11,784"),
("A-weighting FIR taps (511, float32)","415A9DE2D93C0D2C762AE9CE16E666E5","2,044"),
]

FONT = "Arial"
thin = Side(style="thin", color="BFBFBF")
border = Border(left=thin, right=thin, top=thin, bottom=thin)
hdr_fill = PatternFill("solid", fgColor="1F3864")
hdr_font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
body = Font(name=FONT, size=10)
wrap = Alignment(wrap_text=True, vertical="top")

wb = Workbook()
ws = wb.active
ws.title = "Tracker"
headers = ["ID","Source","Section","Type","Status","Item","Facts / notes (record)","Artifact / source of record","Gate / dependency","Done date","My notes"]
widths  = [8,11,13,11,10,42,70,34,24,11,30]
ws.append(headers)
for c in range(1, len(headers)+1):
    cell = ws.cell(row=1, column=c)
    cell.font = hdr_font; cell.fill = hdr_fill; cell.alignment = wrap; cell.border = border
    ws.column_dimensions[get_column_letter(c)].width = widths[c-1]
for r in rows:
    ws.append([r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], "", ""])
last = ws.max_row
for row in ws.iter_rows(min_row=2, max_row=last, max_col=len(headers)):
    for cell in row:
        cell.font = body; cell.alignment = wrap; cell.border = border
ws.freeze_panes = "F2"
ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{last}"

dv = DataValidation(type="list", formula1='"Open,Partial,Landed,Closed,Declined,Deferred,Superseded"', allow_blank=True)
ws.add_data_validation(dv); dv.add(f"E2:E{last}")
dv2 = DataValidation(type="list", formula1='"Writing,Verify,Compute,Decision,Mechanical,Reference"', allow_blank=True)
ws.add_data_validation(dv2); dv2.add(f"D2:D{last}")

rng = f"A2:{get_column_letter(len(headers))}{last}"
ws.conditional_formatting.add(rng, FormulaRule(formula=['$E2="Landed"'], fill=PatternFill("solid", fgColor="E2EFDA")))
ws.conditional_formatting.add(rng, FormulaRule(formula=['$E2="Closed"'], fill=PatternFill("solid", fgColor="E2EFDA")))
ws.conditional_formatting.add(rng, FormulaRule(formula=['$E2="Partial"'], fill=PatternFill("solid", fgColor="FFF2CC")))
ws.conditional_formatting.add(rng, FormulaRule(formula=['$E2="Open"'], fill=PatternFill("solid", fgColor="FCE4D6")))
ws.conditional_formatting.add(rng, FormulaRule(formula=['$E2="Deferred"'], fill=PatternFill("solid", fgColor="EDEDED")))
ws.conditional_formatting.add(rng, FormulaRule(formula=['$E2="Superseded"'], fill=PatternFill("solid", fgColor="EDEDED")))
ws.conditional_formatting.add(rng, FormulaRule(formula=['LEFT($I2,5)="GATE:"'], font=Font(name=FONT, size=10, bold=True, color="C00000")))

# Summary sheet
ss = wb.create_sheet("Summary")
ss["A1"] = "Status"; ss["B1"] = "Count"
for c in ("A1","B1"):
    ss[c].font = hdr_font; ss[c].fill = hdr_fill; ss[c].border = border
statuses = ["Open","Partial","Landed","Closed","Declined","Deferred","Superseded"]
for i, s in enumerate(statuses, start=2):
    ss.cell(row=i, column=1, value=s).font = body
    ss.cell(row=i, column=2, value=f'=COUNTIF(Tracker!$E$2:$E${last},A{i})').font = body
    ss.cell(row=i, column=1).border = border; ss.cell(row=i, column=2).border = border
tr = len(statuses)+2
ss.cell(row=tr, column=1, value="Total").font = Font(name=FONT, bold=True, size=10)
ss.cell(row=tr, column=2, value=f"=SUM(B2:B{tr-1})").font = Font(name=FONT, bold=True, size=10)
ss.cell(row=tr, column=1).border = border; ss.cell(row=tr, column=2).border = border

ss["D1"] = "Type"; ss["E1"] = "Open + Partial"
for c in ("D1","E1"):
    ss[c].font = hdr_font; ss[c].fill = hdr_fill; ss[c].border = border
types = ["Writing","Verify","Compute","Decision","Mechanical","Reference"]
for i, t in enumerate(types, start=2):
    ss.cell(row=i, column=4, value=t).font = body
    ss.cell(row=i, column=5, value=f'=COUNTIFS(Tracker!$D$2:$D${last},D{i},Tracker!$E$2:$E${last},"Open")+COUNTIFS(Tracker!$D$2:$D${last},D{i},Tracker!$E$2:$E${last},"Partial")').font = body
    ss.cell(row=i, column=4).border = border; ss.cell(row=i, column=5).border = border

ss["G1"] = "Gates (must clear before dependent item is written)"
ss["G1"].font = Font(name=FONT, bold=True, size=10)
gates = [
 ("6.3","WEXT-ACC40-REV2 workbook rows banked","6.1, 6.2"),
 ("RP.3a","Plain-ESR column confirmed in scoring workbook","RP.3"),
 ("R4.B7a","Aggregation order confirmed for Fig. 1 source means","R4.B7"),
 ("RP.4","W=19/W=20 synthesis reports read","5.1 causal clause"),
 ("AW.1","esr_aw_rescore_REV2.py --selftest PASS on Lenny","AW.2"),
 ("AW.2 + AW.3","Manifest (510 unique keys) + workbook plain-ESR export","AW.4"),
 ("AW.4","Reconciliation gate PASS (plain reproduces workbook, all 510)","AW.5, AW.6"),
 ("AW.5","AW column banked; plain sheet annotated superseded","AW.7, AW.8"),
 ("AW.7","SPAN-PERSRC rerun on AW column","AW.9, AW.10"),
]
ss["G2"] = "Gate ID"; ss["H2"] = "Gate"; ss["I2"] = "Blocks"
for c in ("G2","H2","I2"):
    ss[c].font = hdr_font; ss[c].fill = hdr_fill; ss[c].border = border
for i, g in enumerate(gates, start=3):
    for j, v in enumerate(g):
        cell = ss.cell(row=i, column=7+j, value=v); cell.font = body; cell.border = border; cell.alignment = wrap
for col, w in zip("ABCDEFGHI", [12,8,3,12,14,3,10,44,16]):
    ss.column_dimensions[col].width = w

ss["A14"] = "Legend"; ss["A14"].font = Font(name=FONT, bold=True, size=10)
legend = [
 "Source: REVCHG = change list 2026-09-05 (REVCHG-20260905-REV1); RP = Remaining-pass notes; R4 = ICASSP-style review (48e2b816); Ledger = items raised in session",
 "Type: Writing = Hope's prose from a fact list; Verify = check against a named file before writing; Compute = new script/output; Decision = Hope's call (page budget / scope); Mechanical = build-side; Reference = reference-list edit",
 "Status column E is a dropdown; rows color by status. Column J/K (Done date, My notes) are yours to fill.",
 "Gate rows (column I starting with GATE:) show in red bold on the Tracker.",
 "Pangram rule: no reviewer or assistant sentence enters the paper; the Facts column is source material only.",
 "Sentinel: " + SENTINEL,
]
for i, t in enumerate(legend, start=15):
    c = ss.cell(row=i, column=1, value=t); c.font = body; c.alignment = Alignment(wrap_text=False)

# Declined sheet
ds = wb.create_sheet("Declined")
ds.append(["Source","Item","Reason logged"])
for c in range(1,4):
    cell = ds.cell(row=1, column=c); cell.font = hdr_font; cell.fill = hdr_fill; cell.border = border
for d in declined:
    ds.append(list(d))
for row in ds.iter_rows(min_row=2, max_row=ds.max_row, max_col=3):
    for cell in row:
        cell.font = body; cell.alignment = wrap; cell.border = border
for col, w in zip("ABC", [10,52,80]):
    ds.column_dimensions[col].width = w
ds.freeze_panes = "A2"

# Hash record sheet
hs = wb.create_sheet("Hash record")
hs.append(["Artifact","MD5","Bytes"])
for c in range(1,4):
    cell = hs.cell(row=1, column=c); cell.font = hdr_font; cell.fill = hdr_fill; cell.border = border
for a in artifacts:
    hs.append(list(a))
for row in hs.iter_rows(min_row=2, max_row=hs.max_row, max_col=3):
    for cell in row:
        cell.font = body; cell.border = border
for col, w in zip("ABC", [46,38,10]):
    hs.column_dimensions[col].width = w

wb.properties.title = SENTINEL
wb.save(OUT)
b = open(OUT,"rb").read()
print(OUT, len(b), "B", hashlib.md5(b).hexdigest().upper(), "rows:", len(rows))
