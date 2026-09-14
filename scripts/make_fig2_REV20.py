#!/usr/bin/env python3
# SENTINEL: FIG2-REV20-2026-09-13
# REV20: height 4.2 -> 3.8 in (page budget, 2026-09-13); top/bottom margin fractions rebalanced so the 2x3 legend and x-label bands keep their absolute size; y-axis labels set on two lines (same text) because the shorter panels no longer clear the single-line labels; left margin widened for them. Per-pedal marker shapes (Rodent o, GreenTint s, FuzzyLogic ^) carried over from REV19 (its script was not available; reconstructed from the REV19 render). Width, fonts (9 pt), data unchanged.
# REV18: x-axis label "bit-width W" -> "word-length W" (advisor terminology note, 2026-09-10); data, panels, layout, fonts unchanged.
# REV17: x tick labels on the bottom panel only, panels drawn close (not touching), height 4.2 in.
# REV16: height 4.7 in (page budget); legend, panels, data unchanged.
# REV15: font list puts Times New Roman first (Lenny); width 3.05 in for width-free \includegraphics.
# REV14: x tick labels shown on every panel (as REV12); hspace widened to carry them.
# Fig. 2 re-export for the ICASSP kit: 9 pt text throughout at the final placed size
# (0.90\columnwidth = 3.05 in), Times-compatible font (TeX Gyre Termes / STIX math) to match
# the body text. Data, panels, palette, line styles, markers and panel letters unchanged from
# FIG2-REV12 (BAD8D3E2). Inputs MD5-gated (warn, not fail) against the artifacts of record.
# Usage: python make_fig2_REV20.py <errspec_T1T3_REV4_510.csv> <errlevel_T5_REV2_510.csv> <out.pdf>
import csv, sys, hashlib, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

SENT = "FIG2-REV20-2026-09-13"
CELLS = ["rodent_max", "rodent_mod", "gt_max", "gt_mod", "fl_max", "fl_mod"]
PAPER = {"rodent_max": "Rodent max", "rodent_mod": "Rodent mod", "gt_max": "GreenTint max",
         "gt_mod": "GreenTint mod", "fl_max": "FuzzyLogic max", "fl_mod": "FuzzyLogic mod"}
COLOR = {"rodent_max": "#D55E00", "rodent_mod": "#E69F00", "fl_max": "#0072B2",
         "fl_mod": "#56B4E9", "gt_max": "#009E73", "gt_mod": "#CC79A7"}
STYLE = {"rodent_mod": "--", "fl_mod": "--", "gt_mod": "--"}
MARKER = {"rodent_max": "o", "rodent_mod": "o", "gt_max": "s", "gt_mod": "s", "fl_max": "^", "fl_mod": "^"}
SRCS = ["nam", "gtr2", "gtr4sg", "prvtgtr", "ytbass"]
W = list(range(8, 25))
MD5_OF_RECORD = {"errspec": "6DB94D689E70019A1DDE971839F7DC93",
                 "errlevel": "5373026B77A759A1D2D332B3DD84FD83"}
FIG_W_IN, FIG_H_IN = 3.05, 3.8   # 0.90 * 3.39 in column; height cut 4.2 -> 3.8 for page budget

def md5(p): return hashlib.md5(open(p, "rb").read()).hexdigest().upper()

def load_errspec(path):
    D = {}
    for r in csv.DictReader(open(path)):
        if r["cell"] == "": sys.exit("FAIL blank cell label - not a REV4 artifact")
        D[(r["cell"], r["src"], int(r["width"]))] = (float(r["coh"]), float(r["sf"]))
    return D

def load_errlevel(path):
    D = {}
    for r in csv.DictReader(open(path)):
        if r["status"] != "OK": sys.exit(f"FAIL non-OK T5 row {r['cell']} {r['src']} {r['width']}")
        D[(r["cell"], r["src"], int(r["width"]))] = float(r["rho_L"])
    return D

def gate(path, key):
    h = md5(path); tag = "OK" if h == MD5_OF_RECORD[key] else "WARN not the artifact of record"
    print(f"in[{key}]: {path} bytes {os.path.getsize(path)} MD5 {h} {tag}")

def main():
    if len(sys.argv) != 4: sys.exit("usage: make_fig2_REV20.py <errspec.csv> <errlevel.csv> <out.pdf>")
    espec, elev, out = sys.argv[1:4]
    if os.path.exists(out): sys.exit(f"FAIL-IF-EXISTS {out}")
    gate(espec, "errspec"); gate(elev, "errlevel")
    E = load_errspec(espec); L = load_errlevel(elev)
    assert len(E) == 510 and len(L) == 510, f"expected 510/510 keys, got {len(E)}/{len(L)}"
    plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman", "TeX Gyre Termes", "Nimbus Roman", "Liberation Serif", "DejaVu Serif"],
                         "mathtext.fontset": "stix", "font.size": 9, "axes.labelsize": 9, "xtick.labelsize": 9,
                         "ytick.labelsize": 9, "legend.fontsize": 9, "pdf.fonttype": 42, "axes.linewidth": 0.6})
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(FIG_W_IN, FIG_H_IN), sharex=True)
    for c in CELLS:
        coh = [np.mean([E[(c, s, w)][0] for s in SRCS]) for w in W]
        sf = [np.mean([E[(c, s, w)][1] for s in SRCS]) for w in W]
        rho = [np.mean([L[(c, s, w)] for s in SRCS]) for w in W]
        kw = dict(color=COLOR[c], ls=STYLE.get(c, "-"), marker=MARKER[c], ms=2.6, lw=1.1,
                  markeredgecolor="black", markeredgewidth=0.3)
        ax1.plot(W, coh, **kw); ax2.plot(W, sf, **kw); ax3.plot(W, rho, **kw)
    ax1.set_ylabel("coherence\n$C(e, y_{f32})$", labelpad=2); ax1.set_ylim(-0.03, 1.03); ax1.set_yticks([0, 0.5, 1])
    ax2.set_ylabel("spectral flatness\nof $e$", labelpad=2); ax2.set_ylim(-0.03, 1.03); ax2.set_yticks([0, 0.5, 1])
    ax3.set_ylabel("level correlation\n$\\rho_L$", labelpad=2); ax3.set_ylim(-1.03, 1.03); ax3.set_yticks([-1, 0, 1])
    ax3.axhline(0, color="k", lw=0.6, ls=":")
    ax3.set_xlabel("word-length W", labelpad=2)
    for ax in (ax1, ax2, ax3):
        ax.set_xticks(list(range(8, 25, 2))); ax.set_xlim(7.5, 24.5)
    for ax in (ax1, ax2):
        ax.tick_params(labelbottom=False)
    for ax, lab in ((ax1, "(a)"), (ax2, "(b)"), (ax3, "(c)")):
        ax.grid(alpha=0.25, lw=0.5); ax.tick_params(length=2.5, pad=2)
        ax.text(0.985, 0.95, lab, transform=ax.transAxes, va="top", ha="right")
    handles = [Line2D([], [], color=COLOR[c], ls=STYLE.get(c, "-"), marker=MARKER[c], ms=2.6, lw=1.1,
                      markeredgecolor="black", markeredgewidth=0.3, label=PAPER[c]) for c in CELLS]
    fig.legend(handles=handles, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.56, 1.0),
               handlelength=2.0, columnspacing=1.0, handletextpad=0.5, borderaxespad=0.0)
    fig.subplots_adjust(left=0.235, right=0.985, top=0.845, bottom=0.10, hspace=0.10)
    fig.savefig(out); fig.savefig(os.path.splitext(out)[0] + ".png", dpi=200)
    print(f"{SENT} wrote {out} bytes {os.path.getsize(out)} MD5 {md5(out)} (+ .png)")

if __name__ == "__main__":
    main()
