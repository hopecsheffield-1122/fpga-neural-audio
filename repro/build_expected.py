# SENTINEL: REPRO-EXPECTED-REV1
# Builds expected_golden.csv for the reproduction pack (run ONCE on Lenny).
# Joins, for cell=rodent_max, widths 8..24:
#   digits  <- cell_grid_102.csv  (cosine, ESR_dB_vs_golden, RMSE, gate, typedef_note)
#   silicon <- campaign_results.csv golden_md5 (board capture hash; by gate B1
#             2026-08-10, csim golden export == board capture 102/102, so this
#             single hash certifies BOTH the simulation and the silicon)
# Hard-fails unless all 17 widths resolve with exactly one row from each source.
import csv, os, sys
GRID = r"<GRU_DIR>\cell_grid_102.csv"
BOARD = r"<NAS>\board_campaign_2026-08-10\campaign_results.csv"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "expected_golden.csv")
CELL = "rodent_max"
print("REPRO-EXPECTED-REV1")
if os.path.exists(OUT):
    sys.exit("FATAL: %s exists (fail-if-exists)" % OUT)
grid = {}
with open(GRID, newline="") as f:
    for r in csv.DictReader(f):
        if r["cell"].strip() == CELL:
            w = int(r["width"])
            if w in grid:
                sys.exit("FATAL: duplicate grid row width %d" % w)
            grid[w] = r
board = {}
with open(BOARD, newline="") as f:
    for r in csv.DictReader(f):
        if r["cell"].strip() == CELL and r["golden_md5"].strip():
            w = int(r["width"])
            m = r["golden_md5"].strip().lower()
            if w in board and board[w] != m:
                sys.exit("FATAL: conflicting golden_md5 width %d" % w)
            board[w] = m
rows = []
for w in range(8, 25):
    if w not in grid:
        sys.exit("FATAL: width %d missing from cell_grid_102" % w)
    if w not in board:
        sys.exit("FATAL: width %d missing golden_md5 in campaign_results" % w)
    g = grid[w]
    rows.append([w, g["cosine"], g["ESR_dB_vs_golden"], g["RMSE"], g["gate"],
                 board[w], g["typedef_note"]])
with open(OUT, "w", newline="") as f:
    wtr = csv.writer(f)
    wtr.writerow(["width", "cosine", "esr_db", "rmse", "gate", "golden_md5", "typedef_note"])
    wtr.writerows(rows)
print("wrote %s (17 widths, cell=%s)" % (OUT, CELL))
for r in rows:
    print("  w%-3s cosine %-9s ESR %-8s dB  gate %-10s md5 %s" % (r[0], r[1], r[2], r[4], r[5]))
print("NOTE: golden_md5 is doubly certified (csim==silicon, gate B1 102/102, 2026-08-10)")
