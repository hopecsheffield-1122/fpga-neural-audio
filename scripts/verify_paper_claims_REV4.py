#!/usr/bin/env python3
# VERIFY-PAPER-CLAIMS-REV4-2026-09-13 (REV4b: block [8] adds the test-segregated spans and the Table 2 throughput figures)
# REV4: adds a hard assertion block [7] that compares the computed values against the SUBMITTED digits below and
#       exits 1 on any mismatch (REV3 only printed values for eyeball comparison). verify_all.py REV3 gates on this.
#       Block [3] (NMR max vs ODG min in W=11..14) is informational only: the manuscript makes no claim about it.
# REV3: reads the repo's public CSVs instead of the (non-public) workbook. Inputs, relative to repo root:
#   results/metrics/matrices/esr_510.csv, nmr_510.csv, odg_510.csv   (cell,source,width,value)
#   results/metrics/raw/peaq_fleet_REV3.csv                         (cell,src,width,odg,total_nmr,...)
#   results/analysis/errspec_T1T3_REV4_510.csv                      (block [6])
#   results/analysis/heldout_srcmean_span_REV1.csv                  (block [8], kind=model_srcmean rows)
#   results/hardware/campaign_results.csv                           (block [8], cyc_hw and fl_x_rt over 102 builds)
# Checks Sec. 3.3 / 4.1 / 4.2 claims of the ICASSP 2027 submission. Read-only.
# Usage: python scripts/verify_paper_claims_REV4.py [repo_root]      exit 0 = every manuscript claim encoded in CLAIM reproduced
# ---- SUBMITTED DIGITS (edit here if the manuscript wording changes) ----
CLAIM = {
  'input_md5': {'esr_510.csv':'7E3AB6F1CF7DE74E4001D713B678F0F4','nmr_510.csv':'81BC7B7865081127301059CA55E7A24C',
                'odg_510.csv':'BA4CD48F3ED848D08002E020C573842F','peaq_fleet_REV3.csv':'D0A7849ECB312C88194FDEC512A1D5BF',
                'errspec_T1T3_REV4_510.csv':'6DB94D689E70019A1DDE971839F7DC93'},
  'nmr_max_W':   {'rodent_max':14,'rodent_mod':12,'fl_max':14,'fl_mod':14},   # Sec. 4.1: source-mean NMR local maximum
  'nmr_flat':    ['gt_max','gt_mod'],                                          # Sec. 4.1: no NMR local maximum / no worsening step
  'span_defined': 29, 'span_min': 2, 'span_max': 6, 'span_undefined': [('fl_max','nam')],   # [4]
  'gaps': {'rodent_max':3,'rodent_mod':4,'gt_max':5,'gt_mod':3,'fl_max':6,'fl_mod':4}, 'gap_mean': 4.2,  # [4b] Table 1
  'r_nmr': 0.997, 'nmr_offset_dB': -1.7,                                       # [5] Sec. 3.3
  'coh_below_at_nmr_max': 0.5, 'esr_at_last_coh_ge': -4.0,                     # [6] Sec. 4.2
  'heldout_gaps': {'rodent_max':2,'rodent_mod':3,'gt_max':4,'gt_mod':3,'fl_max':4,'fl_mod':3}, 'heldout_gap_mean': 3.2,  # [8] Sec. 4.1 test-segregated
  'cyc_hw_range': (140.5, 142.5), 'kernel_xrt_range': (14.6, 14.8), 'e2e_xrt_range': (14.0, 14.2),   # [8] Sec. 4.3 / Table 2; kernel xRT = 100 MHz / cyc_hw / 48 kHz
  'fclk_mhz': 100.0, 'fs_hz': 48000,
}
import sys, os, csv, hashlib, numpy as np
root = sys.argv[1] if len(sys.argv) > 1 else '.'
P = lambda *a: os.path.join(root, *a)
def md5(p): return hashlib.md5(open(p,'rb').read()).hexdigest().upper()
cells = ['rodent_max','rodent_mod','gt_max','gt_mod','fl_max','fl_mod']
srcs  = ['gtr2','gtr4sg','prvtgtr','ytbass','nam']
W = list(range(8,25))
def load510(name):
    p = P('results','metrics','matrices',name); d = {}
    for r in csv.DictReader(open(p)): d[(r['cell'], r['source'], int(r['width']))] = float(r['value'])
    print(f'  {name}: {len(d)} rows, MD5 {md5(p)}'); return d
print('[inputs]')
ESR, NMR, ODG = load510('esr_510.csv'), load510('nmr_510.csv'), load510('odg_510.csv')
TNMR = {}
pq = P('results','metrics','raw','peaq_fleet_REV3.csv')
for r in csv.DictReader(open(pq)): TNMR[(r['cell'], r['src'], int(r['width']))] = float(r['total_nmr'])
print(f'  peaq_fleet_REV3.csv: {len(TNMR)} rows, MD5 {md5(pq)}')
assert len(ESR) == len(NMR) == len(ODG) == len(TNMR) == 510, (len(ESR), len(NMR), len(ODG), len(TNMR))

print('\n[1] ESR step-ups per (cell,source): (W, dB rise from W to W+1)')
for c in cells:
    for s in srcs:
        v = [ESR[(c,s,w)] for w in W]
        print(f'  {c:11s} {s:8s}', [(W[i], round(v[i+1]-v[i],2)) for i in range(16) if v[i+1] > v[i]])
NMRMAX = {}; NMRUPS = {}
print('\n[2] source-mean ESR/NMR per cell (paper: source-mean ESR does not rise inside W=11..14; NMR maxima 14/12/14/14)')
for c in cells:
    e = [np.mean([ESR[(c,s,w)] for s in srcs]) for w in W]
    n = [np.mean([NMR[(c,s,w)] for s in srcs]) for w in W]
    NMRMAX[c] = [W[i] for i in range(1,16) if n[i] > n[i-1] and n[i] >= n[i+1]]; NMRUPS[c] = [W[i] for i in range(16) if n[i+1] > n[i]]
    print(f'  {c}: ESR ups at', [W[i] for i in range(16) if e[i+1] > e[i]],
          '| first W mean ESR<=-20:', next(w for w,x in zip(W,e) if x <= -20),
          '| NMR local maxima:', [W[i] for i in range(1,16) if n[i] > n[i-1] and n[i] >= n[i+1]],
          '| NMR worsening steps W->W+1:', [W[i] for i in range(16) if n[i+1] > n[i]])
print('\n[3] per (cell,source): NMR local max in 11-14 vs ODG local min in 11-14  (informational; not a paper claim)')
agree_presence = agree_same = agree_within1 = 0; n_have = same_have = 0
for c in cells:
    for s in srcs:
        n = [NMR[(c,s,w)] for w in W]; o = [ODG[(c,s,w)] for w in W]
        nm = [W[i] for i in range(1,16) if n[i] > n[i-1] and n[i] >= n[i+1] and 11 <= W[i] <= 14]
        om = [W[i] for i in range(1,16) if o[i] < o[i-1] and o[i] <= o[i+1] and 11 <= W[i] <= 14]
        pres = bool(nm) == bool(om); same = (not nm and not om) or bool(set(nm) & set(om))
        near = (not nm and not om) or any(abs(a-b) <= 1 for a in nm for b in om)
        agree_presence += pres; agree_same += same; agree_within1 += near
        if nm or om: n_have += 1; same_have += bool(set(nm) & set(om))
        print(f'  {c:11s} {s:8s} NMR max {nm}  ODG min {om}  presence={pres} sameW={same} within1={near}')
print(f'  presence/absence agreement: {agree_presence} / 30   same-W agreement: {agree_same} / 30 ({same_have} of {n_have} pairs with an extremum)   within +-1 W: {agree_within1} / 30')
print('\n[4] per-source span at (ESR<=-20 dB, ODG>=-0.5) (paper: 29 defined, all positive, +2..+6; fl_max/nam undefined)')
spans = []; undefined = []
for c in cells:
    for s in srcs:
        we = next((w for w in W if ESR[(c,s,w)] <= -20), None); wo = next((w for w in W if ODG[(c,s,w)] >= -0.5), None)
        sp = None if we is None or wo is None else wo - we; spans.append(sp)
        if sp is None: undefined.append((c,s))
        print(f'  {c:11s} {s:8s} w_esr={we} w_odg={wo} span={sp}')
d = [x for x in spans if x is not None]
print('  defined', len(d), 'positive', sum(x > 0 for x in d), 'min', min(d), 'max', max(d))
print('\n[4b] per-model spans on source means (paper: {+3,+4,+5,+3,+6,+4}, mean 4.2)')
gaps = []; GAP = {}
for c in cells:
    e = [np.mean([ESR[(c,s,w)] for s in srcs]) for w in W]; o = [np.mean([ODG[(c,s,w)] for s in srcs]) for w in W]
    we = next(w for w,x in zip(W,e) if x <= -20); wo = next(w for w,x in zip(W,o) if x >= -0.5); gaps.append(wo-we); GAP[c] = wo-we
    print(f'  {c:11s} w_esr={we} w_odg={wo} gap=+{wo-we}')
print('  mean gap', round(sum(gaps)/6, 2))
print('\n[5] Pearson NMR (repo nmr_510) vs GstPEAQ total_nmr (n=510) (paper: r=0.997, offset -1.7 dB)')
k = sorted(ODG); a = np.array([NMR[x] for x in k]); b = np.array([TNMR[x] for x in k])
R_NMR = float(np.corrcoef(a,b)[0,1]); OFF_NMR = float((a-b).mean())
print('  r =', round(R_NMR, 4), ' mean(NMR - Gst total_nmr) =', round(OFF_NMR, 2), 'dB')

es = P('results','analysis','errspec_T1T3_REV4_510.csv')
ES_MD5 = md5(es); COH6 = {}
if True:
    print('\n[6] Sec. 4.2 coherence / flatness, source mean per model; errspec MD5', md5(es), '(record 6DB94D68...)')
    E = {}
    for r in csv.DictReader(open(es)): E[(r['cell'], r['src'], int(r['width']))] = (float(r['coh']), float(r['sf']))
    assert len(E) == 510
    nmrmax = CLAIM['nmr_max_W']
    for c in cells:
        coh = [np.mean([E[(c,s,w)][0] for s in srcs]) for w in W]; sf = [np.mean([E[(c,s,w)][1] for s in srcs]) for w in W]
        e = [np.mean([ESR[(c,s,w)] for s in srcs]) for w in W]
        hi = [w for w,x in zip(W,coh) if x >= 0.5]
        if c in nmrmax: COH6[c] = (coh[W.index(nmrmax[c])], e[W.index(max(hi))] if hi else None)
        print(f'  {c}')
        print('    coh :', ' '.join(f'{x:5.2f}' for x in coh))
        print('    sf  :', ' '.join(f'{x:5.2f}' for x in sf))
        print('    last W coh>=0.5:', max(hi, default=None),
              '| first W coh<0.5 after that:', next((w for w,x in zip(W,coh) if w > max(hi, default=7) and x < 0.5), None),
              '| NMR max:', nmrmax.get(c), '| mean ESR at last coh>=0.5 W:', round(e[W.index(max(hi))],1) if hi else None,
              '(paper: coherence falls below 0.5 at the NMR max; high coherence co-occurs with ESR >= -4 dB)')

print('\n[8] test-segregated spans (source mean over bass+gtr4ib) and Table 2 throughput')
hs = P('results','analysis','heldout_srcmean_span_REV1.csv')
HGAP = {}
for r in csv.reader(open(hs)):
    if r and r[0] == 'model_srcmean': HGAP[r[1]] = int(r[5])
print('  held-out gaps', HGAP, 'mean', round(sum(HGAP.values())/6, 2))
cr = P('results','hardware','campaign_results.csv'); crows = list(csv.DictReader(open(cr)))
CYC = [float(r['cyc_hw']) for r in crows]; FLX = [float(r['fl_x_rt']) for r in crows]; FCLK = {float(r['fclk_mhz']) for r in crows}
KX = [CLAIM['fclk_mhz']*1e6/c/CLAIM['fs_hz'] for c in CYC]
print(f'  campaign rows {len(crows)}  fclk {sorted(FCLK)}  cyc_hw {min(CYC)}..{max(CYC)}  kernel xRT {min(KX):.2f}..{max(KX):.2f}  end-to-end fl_x_rt {min(FLX)}..{max(FLX)}')

print('\n[7] ASSERTIONS against the manuscript claims encoded in CLAIM')
fails = []
def chk(name, ok, got): 
    fails.append(name) if not ok else None; print(f'  [{"PASS" if ok else "FAIL"}] {name}: {got}')
for k, h in CLAIM['input_md5'].items():
    p = P('results','metrics','matrices',k) if k.endswith('_510.csv') and 'errspec' not in k else (pq if 'peaq' in k else es)
    chk(f'input MD5 {k}', md5(p) == h, md5(p)[:8])
for c, w in CLAIM['nmr_max_W'].items(): chk(f'[2] {c} source-mean NMR local max at W={w}', w in NMRMAX[c], NMRMAX[c])
for c in CLAIM['nmr_flat']: chk(f'[2] {c} no NMR worsening step', not NMRUPS[c] and not NMRMAX[c], NMRUPS[c])
chk('[4] spans defined', len(d) == CLAIM['span_defined'], len(d)); chk('[4] spans all positive', all(x > 0 for x in d), min(d))
chk('[4] span range', (min(d), max(d)) == (CLAIM['span_min'], CLAIM['span_max']), (min(d), max(d)))
chk('[4] undefined pairs', undefined == CLAIM['span_undefined'], undefined)
chk('[4b] per-model gaps', GAP == CLAIM['gaps'], GAP); chk('[4b] mean gap', round(sum(gaps)/6, 1) == CLAIM['gap_mean'], round(sum(gaps)/6, 2))
chk('[5] r', round(R_NMR, 3) == CLAIM['r_nmr'], round(R_NMR, 4)); chk('[5] offset dB', round(OFF_NMR, 1) == CLAIM['nmr_offset_dB'], round(OFF_NMR, 2))
for c, (coh_at, esr_at) in COH6.items():
    chk(f'[6] {c} coherence < {CLAIM["coh_below_at_nmr_max"]} at NMR max', coh_at < CLAIM['coh_below_at_nmr_max'], round(coh_at, 3))
    chk(f'[6] {c} mean ESR >= {CLAIM["esr_at_last_coh_ge"]} dB at last coh>=0.5 W', esr_at is not None and esr_at >= CLAIM['esr_at_last_coh_ge'], round(esr_at, 1) if esr_at is not None else None)
chk('[8] held-out per-model gaps', HGAP == CLAIM['heldout_gaps'], HGAP); chk('[8] held-out mean gap', round(sum(HGAP.values())/6, 1) == CLAIM['heldout_gap_mean'], round(sum(HGAP.values())/6, 2))
chk('[8] 102 campaign rows at 100 MHz', len(crows) == 102 and FCLK == {CLAIM['fclk_mhz']}, (len(crows), sorted(FCLK)))
chk('[8] cyc_hw range', (round(min(CYC),1), round(max(CYC),1)) == CLAIM['cyc_hw_range'], (min(CYC), max(CYC)))
chk('[8] kernel xRT range', (round(min(KX),1), round(max(KX),1)) == CLAIM['kernel_xrt_range'], (round(min(KX),2), round(max(KX),2)))
chk('[8] end-to-end xRT range', (round(min(FLX),1), round(max(FLX),1)) == CLAIM['e2e_xrt_range'], (min(FLX), max(FLX)))
print('VERIFY-PAPER-CLAIMS-REV4:', 'ALL ENCODED CLAIMS REPRODUCED' if not fails else f'{len(fails)} MISMATCH: ' + ', '.join(fails))
sys.exit(0 if not fails else 1)
