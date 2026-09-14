#!/usr/bin/env python3
# SENTINEL: B1CMP-REV1-2026-08-10
# b1_compare.py -- the B1 gate: byte-compare the 102 csim golden exports
# against the board's golden captures, via MD5.
#   csim side : C:\hb\golden_exports\csim_gold_<cell>_w<W>.f32 (hashed here)
#   board side: verified_manifest.csv rows board_gold_<cell>_w<W>.f32
#               (board-side md5, already NAS-verified by VMOVE-REV2)
# PRE-REGISTERED PREDICTION: 102/102 identical.
#
# Machine: LENNY. Usage:
#   python b1_compare.py --exports C:\hb\golden_exports --manifest "<NAS>\board_campaign_2026-08-10\verified_manifest.csv" --out "<GRU_DIR>\b1_gate_results.csv"

import argparse
import csv
import hashlib
import sys
from pathlib import Path

SENTINEL = "B1CMP-REV1-2026-08-10"


def md5f(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest().lower()


def main():
    ap = argparse.ArgumentParser(description=f"B1 byte-identity gate ({SENTINEL})")
    ap.add_argument("--exports", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    board = {}
    with open(args.manifest, newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0].startswith("board_gold_"):
                # board_gold_<cell>_w<W>.f32 -> key <cell>_w<W>
                key = row[0][len("board_gold_"):-len(".f32")]
                board[key] = row[1].lower()
    print(f"{SENTINEL}: {len(board)} board_gold rows in manifest")

    exports = sorted(Path(args.exports).glob("csim_gold_*.f32"))
    print(f"{len(exports)} csim exports found")

    rows, match, mism, orphan = [], 0, [], []
    for p in exports:
        key = p.name[len("csim_gold_"):-len(".f32")]
        cm = md5f(p)
        bm = board.get(key)
        if bm is None:
            orphan.append(key)
            rows.append((key, cm, "", "NO_BOARD_ROW"))
        elif cm == bm:
            match += 1
            rows.append((key, cm, bm, "IDENTICAL"))
        else:
            mism.append(key)
            rows.append((key, cm, bm, "MISMATCH"))

    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"# {SENTINEL}"])
        w.writerow(["point", "csim_md5", "board_md5", "verdict"])
        w.writerows(rows)
    print(f"wrote {args.out}")

    print(f"\nB1 GATE: {match} identical / {len(exports)} exports")
    if mism:
        print("MISMATCHES:")
        for k in mism:
            print(f"   {k}")
    if orphan:
        print("NO BOARD ROW:")
        for k in orphan:
            print(f"   {k}")
    if match == 102 and not mism and not orphan:
        print("B1 GATE: PASS -- csim and silicon byte-identical at all 102 points")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
# SENTINEL-END: B1CMP-REV1-2026-08-10
