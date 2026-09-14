#!/usr/bin/env python3
# VERIFY-ALL-REV3-2026-09-13 (REV3b: git check-attr fed via --stdin; argument list exceeded the Windows command-line limit)
# REV3: (a) step 5 runs scripts/verify_paper_claims_REV4.py and its exit code is part of the overall verdict
#       (REV2 treated it as informational); (b) MANIFEST MD5s are computed on line-ending-normalised bytes
#       (CRLF -> LF) for files git treats as text, and on raw bytes for files marked -text (reports/, results/,
#       repro/, *.rpt, *.csv), so the check gives the same answer on Windows and Linux checkouts.
# REV2: step 6 runs scripts/verify_resources_REV2.py against reports/impl and counts it as a pass/fail check.
# One-command check of the repository against its own records. Run from the repo root:
#   python verify_all.py
# Steps (each prints PASS/FAIL and the script continues):
#   1. MANIFEST.csv — every listed file exists and its MD5 matches; every tracked file is listed.
#   2. Report counts — csynth 510, impl 204, impl_nondeployed 36, csim 102, csim_filemode 85; one placed-utilization
#      and one timing report per deployed build named in results/hardware/resources_by_width_REV1.csv.
#   3. Artifacts of record — MD5 of the figure inputs and the two DSP-binding csynth reports (scrubbed copies).
#   4. Bitstream zip — MD5 and entry count against results/hardware/records/campaign102_bitstreams_zip_md5.txt.
#   5. Paper claims — runs scripts/verify_paper_claims_REV4.py; its block [7] asserts every manuscript claim encoded in its CLAIM table.
#   6. Table 2 — runs scripts/verify_resources_REV2.py: every row of resources_by_width_REV1.csv vs reports/impl.
# Exit code 0 only if all six steps pass.
import os, sys, csv, hashlib, subprocess, zipfile, re
root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else '.')
os.chdir(root)
def md5(p): return hashlib.md5(open(p, 'rb').read()).hexdigest().upper()
def is_text(files):
    out = subprocess.run(['git', 'check-attr', '--stdin', 'text'], input='\n'.join(files), capture_output=True, text=True, check=True).stdout
    return {l.split(': text: ')[0]: l.split(': text: ')[1] != 'unset' for l in out.strip().split('\n') if ': text: ' in l}
def md5_norm(p, text):
    b = open(p, 'rb').read()
    return hashlib.md5(b.replace(b'\r\n', b'\n') if text else b).hexdigest().upper()
ok_all = True
def report(name, ok, detail=''):
    global ok_all; ok_all &= ok
    print(f'[{"PASS" if ok else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))

# 1. MANIFEST
tracked = [f for f in subprocess.check_output(['git', 'ls-files'], text=True).split('\n') if f and f != 'MANIFEST.csv']
man = {r['path']: (int(r['bytes']), r['md5'].upper()) for r in csv.DictReader(open('MANIFEST.csv'))}
missing = [f for f in man if not os.path.exists(f)]
txt = is_text([f for f in man if f not in missing])
bad = [f for f in man if f not in missing and md5_norm(f, txt.get(f, True)) != man[f][1]]
unlisted = [f for f in tracked if f not in man]
report('MANIFEST: listed files exist', not missing, f'{len(missing)} missing' + (': ' + ', '.join(missing[:3]) if missing else ''))
report('MANIFEST: MD5s match (CRLF->LF normalised for text files)', not bad, f'{len(bad)} mismatched' + (': ' + ', '.join(bad[:3]) if bad else ''))
report('MANIFEST: all tracked files listed', not unlisted, f'{len(unlisted)} unlisted' + (': ' + ', '.join(unlisted[:3]) if unlisted else ''))

# 2. Report counts and per-build completeness
def count(d, pat): return sum(1 for f in os.listdir(d) if re.search(pat, f)) if os.path.isdir(d) else 0
expect = {('reports/csynth', r'\.rpt$'): 510, ('reports/impl', r'\.rpt$'): 204, ('reports/impl_nondeployed', r'\.rpt$'): 36,
          ('reports/csim', r'\.log$'): 102, ('reports/csim_filemode', r'\.log$'): 85}
for (d, pat), n in expect.items():
    c = count(d, pat); report(f'{d}: {n} files', c == n, f'found {c}')
deployed = [r['report_dir'] for r in csv.DictReader(open('results/hardware/resources_by_width_REV1.csv'))]
miss = [b for b in deployed for t in ('utilization_placed', 'timing_summary_routed') if not os.path.exists(f'reports/impl/{b}_{t}.rpt')]
report('reports/impl: both reports for every deployed build', len(deployed) == 102 and not miss, f'{len(deployed)} builds, {len(miss)} missing')

# 3. Artifacts of record
record = {'results/analysis/errspec_T1T3_REV4_510.csv': '6DB94D689E70019A1DDE971839F7DC93',
          'results/analysis/errlevel_T5_REV2_510.csv': '5373026B77A759A1D2D332B3DD84FD83',
          'reports/csynth/fl_max_w19_csynth.rpt': '2265BFD7', 'reports/csynth/fl_max_w20_csynth.rpt': 'AEB2A589'}
for p, h in record.items():
    ok = os.path.exists(p) and md5(p).startswith(h); report(f'record MD5: {p}', ok, md5(p)[:8] if os.path.exists(p) else 'missing')

# 4. Bitstream zip
zp = 'results/hardware/bitstreams/campaign102_bitstreams.zip'
rec = open('results/hardware/records/campaign102_bitstreams_zip_md5.txt').read().split()[0].upper()
zok = os.path.exists(zp) and md5(zp) == rec
n = len(zipfile.ZipFile(zp).namelist()) if os.path.exists(zp) else 0
report('bitstreams zip MD5 matches record', zok, md5(zp)[:8] if os.path.exists(zp) else 'missing')
report('bitstreams zip has 204 entries (102 .bit + 102 .hwh)', n == 204, f'{n} entries')

# 5. Paper claims — gated
print('\n=== scripts/verify_paper_claims_REV4.py ===')
r = subprocess.run([sys.executable, 'scripts/verify_paper_claims_REV4.py', '.'])
report('paper claims: every claim encoded in verify_paper_claims_REV4 CLAIM table reproduced (block [7])', r.returncode == 0, f'exit {r.returncode}')

# 6. Table 2 resources vs reports
print('\n=== scripts/verify_resources_REV2.py ===')
r = subprocess.run([sys.executable, 'scripts/verify_resources_REV2.py'], capture_output=True, text=True)
print(r.stdout.strip()[:1500])
report('resources_by_width_REV1.csv re-derived from reports/impl (102 MATCH)', r.returncode == 0 and 'MATCH=102' in r.stdout)

print('\nVERIFY-ALL-REV3:', 'ALL CHECKS PASSED' if ok_all else 'SOME CHECKS FAILED')
sys.exit(0 if ok_all else 1)
