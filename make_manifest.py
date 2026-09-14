#!/usr/bin/env python3
# MAKE-MANIFEST-REV2-2026-09-13 (REV2b: git check-attr fed via --stdin; argument list exceeded the Windows command-line limit)
# REV2: MD5 is computed on CRLF->LF normalised bytes for files git treats as text, and on raw bytes for files
#       marked -text in .gitattributes (reports/, results/, repro/, *.rpt, *.csv). Hashes are therefore identical
#       on Windows and Linux checkouts; verify_all.py REV3 checks them the same way. `bytes` is the on-disk size.
# Regenerates MANIFEST.csv at the repo root: one row per git-tracked file with size and MD5.
# Run from the repo root:  python make_manifest.py
# Excludes MANIFEST.csv itself. Output columns: path, bytes, md5. Paths are repo-relative, forward slashes.
import subprocess, hashlib, os, csv, sys
root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else '.')
files = subprocess.check_output(['git', 'ls-files'], cwd=root, text=True).split('\n')
files = [f for f in files if f and f != 'MANIFEST.csv']
attr = subprocess.run(['git', 'check-attr', '--stdin', 'text'], input='\n'.join(files), cwd=root, capture_output=True, text=True, check=True).stdout
text = {l.split(': text: ')[0]: l.split(': text: ')[1] != 'unset' for l in attr.strip().split('\n') if ': text: ' in l}
rows = []
for f in sorted(files):
    p = os.path.join(root, f)
    b = open(p, 'rb').read()
    h = hashlib.md5(b.replace(b'\r\n', b'\n') if text.get(f, True) else b).hexdigest().upper()
    rows.append((f, os.path.getsize(p), h))
out = os.path.join(root, 'MANIFEST.csv')
with open(out, 'w', newline='') as fh:
    w = csv.writer(fh); w.writerow(['path', 'bytes', 'md5']); w.writerows(rows)
print(f'MAKE-MANIFEST-REV2 wrote {out}: {len(rows)} files')
