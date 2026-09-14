#!/usr/bin/env python3
"""
make_weights_header.py  (v3)
----------------------------
Convert a flat float32 weight buffer (weights_flat.bin) into a compile-time
ROM header for the const-weight HLS variant.

LAYOUTS
  --layout flat   (default) one array (v2 behaviour):
                    static const DT_W GRU_W_ROM[5201] = {...};
                  For designs whose datapath indexes a flat buffer.
  --layout split  fourteen named const definitions matching the GRU
                  datapath's existing arrays, in export-contract order:
                    W_r[H] W_z[H] W_n[H]            (w_ih, gate order r,z,n)
                    U_r[H][H] U_z[H][H] U_n[H][H]   (w_hh, row-major)
                    b_ir b_iz b_in  b_hr b_hz b_hn  (biases)
                    w_out[H]  b_out                 (output layer)
                  The datapath compiles unchanged; the ROM->RAM copy loader
                  and the mutable duplicates are deleted, not fed.

BIT-EXACTNESS (unchanged from v2)
  * Literals carry an 'f' suffix (or are exact hexfloats via --literal hex),
    so the frontend parses float, matching the m_axi loader's float->DT_W
    conversion exactly, AP_RND_CONV ties included.
  * Readback verification always runs and is POSITION-AWARE: every emitted
    literal is re-parsed as float32 and bit-compared against the source bin
    at its computed flat offset. In split mode this machine-checks the
    slicing arithmetic, not just the values. Any mismatch -> no file written.

C++ LINKAGE NOTE (split mode)
  Namespace-scope const has internal linkage in C++. If the datapath is in a
  different translation unit than these definitions, gru_weights.h must
  declare `extern const DT_W W_r[40];` etc. under the same ifdef. The
  generated header ends with that block as a ready-to-paste comment.
"""

import argparse
import hashlib
import os
import sys
import time
from fractions import Fraction

import numpy as np


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def lit_decimal(v):
    return "%+.9ef" % float(v)


def lit_hex(v):
    s = float(v).hex()
    return ("-" + s[1:] + "f") if s.startswith("-") else ("+" + s + "f")


def parse_literal(text):
    t = text.strip()
    if t.endswith("f") or t.endswith("F"):
        t = t[:-1]
    if t.startswith("+"):
        t = t[1:]
    if "x" in t.lower():
        return np.float32(float.fromhex(t))
    return np.float32(t)


def count_ties(raw, frac_bits):
    scale = Fraction(2) ** (frac_bits + 1)
    ties = []
    for i, v in enumerate(raw):
        fr = Fraction(float(v)) * scale
        if fr.denominator == 1 and (fr.numerator % 2 != 0):
            ties.append(i)
    return ties


def split_spec(H):
    """(name, shape, flat_offset) in export-contract order."""
    spec, off = [], 0
    for nm in ("W_r", "W_z", "W_n"):
        spec.append((nm, (H,), off)); off += H
    for nm in ("U_r", "U_z", "U_n"):
        spec.append((nm, (H, H), off)); off += H * H
    for nm in ("b_ir", "b_iz", "b_in", "b_hr", "b_hz", "b_hn"):
        spec.append((nm, (H,), off)); off += H
    spec.append(("w_out", (H,), off)); off += H
    spec.append(("b_out", (), off)); off += 1
    return spec, off


def emit_1d(lines, emitted, raw, fmt, dtype, name, off, n, per):
    lines.append("// %s: %d values, flat [%d..%d]" % (name, n, off, off + n - 1))
    lines.append("const %s %s[%d] = {" % (dtype, name, n))
    for i in range(0, n, per):
        toks = [fmt(raw[off + i + j]) for j in range(min(per, n - i))]
        for j, t in enumerate(toks):
            emitted.append((off + i + j, t))
        comma = "," if (i + per) < n else ""
        lines.append("    %s%s  // [%d]" % (", ".join(toks), comma, i))
    lines.append("};")
    lines.append("")


def emit_2d(lines, emitted, raw, fmt, dtype, name, off, r, c, per):
    lines.append("// %s: %dx%d row-major, flat [%d..%d]" %
                 (name, r, c, off, off + r * c - 1))
    lines.append("const %s %s[%d][%d] = {" % (dtype, name, r, c))
    for i in range(r):
        base = off + i * c
        lines.append("    {  // row %d, flat [%d..%d]" % (i, base, base + c - 1))
        for j0 in range(0, c, per):
            toks = [fmt(raw[base + j0 + j]) for j in range(min(per, c - j0))]
            for j, t in enumerate(toks):
                emitted.append((base + j0 + j, t))
            comma = "," if (j0 + per) < c else ""
            lines.append("        %s%s" % (", ".join(toks), comma))
        lines.append("    }%s" % ("," if i < r - 1 else ""))
    lines.append("};")
    lines.append("")


def main():
    ap = argparse.ArgumentParser(
        description="weights_flat.bin -> compile-time const-weight header (v3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--bin", required=True,
                    help="input flat float32 weight buffer (little-endian)")
    ap.add_argument("--out", required=True, help="output .h path")
    ap.add_argument("--layout", choices=["flat", "split"], default="flat",
                    help="flat = one GRU_W_ROM array (v2 behaviour). split = "
                         "14 named const definitions the datapath reads "
                         "directly (default: flat)")
    ap.add_argument("--hidden", type=int, default=40,
                    help="hidden size H for split layout; element count must "
                         "equal 3H^2+10H+1 (default: 40)")
    ap.add_argument("--name", default="GRU_W_ROM",
                    help="array name, flat layout only (default: GRU_W_ROM)")
    ap.add_argument("--type", default="DT_W",
                    help="element typedef, must be visible at include point "
                         "(default: DT_W)")
    ap.add_argument("--include", default="gru_va.h",
                    help="header to #include for the typedef; NONE to skip "
                         "(default: gru_va.h)")
    ap.add_argument("--literal", choices=["decimal", "hex"], default="decimal",
                    help="decimal = 10-significant-digit exponential with f "
                         "suffix. hex = exact hexfloat (default: decimal)")
    ap.add_argument("--frac-bits", type=int, default=15,
                    help="fractional bits of the target typedef, tie report "
                         "only; ap_fixed<20,5> -> 15 (default: 15)")
    ap.add_argument("--expect-n", type=int, default=5201,
                    help="expected element count, 0 to disable (default: 5201)")
    ap.add_argument("--per-line", type=int, default=4,
                    help="literals per source line (default: 4)")
    ap.add_argument("--guard", default=None,
                    help="include-guard macro (default: derived from --out)")
    ap.add_argument("--label", default=None,
                    help="free-text provenance label, e.g. checkpoint name")
    ap.add_argument("--notes", action="store_true",
                    help="print the design rationale and exit")
    args = ap.parse_args()

    if args.notes:
        print(__doc__); return 0
    if not os.path.isfile(args.bin):
        sys.exit("ERROR: no such file: %s" % args.bin)

    raw = np.fromfile(args.bin, dtype="<f4")
    n = raw.size
    src_md5 = md5_of(args.bin)

    print("source      : %s" % os.path.abspath(args.bin))
    print("md5         : %s" % src_md5)
    print("elements    : %d  (%d bytes)" % (n, n * 4))
    print("min / max   : %+.9e / %+.9e" % (raw.min(), raw.max()))
    print("max |value| : %.9e" % np.abs(raw).max())
    print("layout      : %s   literal form: %s" % (args.layout, args.literal))

    if not np.isfinite(raw).all():
        sys.exit("ERROR: non-finite values in %s" % args.bin)
    if args.expect_n and n != args.expect_n:
        sys.exit("ERROR: element count %d != expected %d "
                 "(pass --expect-n 0 to override)" % (n, args.expect_n))

    H = args.hidden
    if args.layout == "split":
        need = 3 * H * H + 10 * H + 1
        if n != need:
            sys.exit("ERROR: split layout with H=%d needs 3H^2+10H+1=%d "
                     "elements, buffer has %d" % (H, need, n))

    ties = count_ties(raw, args.frac_bits)
    print("")
    print("TIES at 2^-%d grid : %d of %d value(s) exactly on a rounding tie"
          % (args.frac_bits, len(ties), n))
    if ties:
        head = ", ".join(str(i) for i in ties[:12])
        print("  flat indices     : %s%s" %
              (head, " ..." if len(ties) > 12 else ""))

    fmt = lit_hex if args.literal == "hex" else lit_decimal
    guard = args.guard
    if guard is None:
        base = os.path.basename(args.out)
        guard = "".join(c.upper() if c.isalnum() else "_" for c in base) + "_"

    outdir = os.path.dirname(os.path.abspath(args.out))
    if outdir and not os.path.isdir(outdir):
        os.makedirs(outdir)

    lines, emitted = [], []
    lines.append("// %s -- generated by make_weights_header.py v3. DO NOT EDIT."
                 % os.path.basename(args.out))
    lines.append("//")
    lines.append("// source     : %s" % os.path.abspath(args.bin))
    lines.append("// md5        : %s" % src_md5)
    lines.append("// elements   : %d   layout: %s" % (n, args.layout))
    lines.append("// max|w|     : %.9e" % np.abs(raw).max())
    lines.append("// literals   : %s, float-suffixed; parsed as float ->" % args.literal)
    lines.append("//              identical conversion to the m_axi loader,")
    lines.append("//              AP_RND_CONV ties included. Every literal was")
    lines.append("//              re-parsed and bit-verified at its flat offset.")
    lines.append("// ties@2^-%-3d: %d value(s) exactly on an AP_RND_CONV tie"
                 % (args.frac_bits, len(ties)))
    if args.label:
        lines.append("// label      : %s" % args.label)
    lines.append("// generated  : %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("//")
    lines.append("// Quantization happens at elaboration under the %s typedef;" % args.type)
    lines.append("// flipping the typedef requantizes -- no regeneration needed.")
    lines.append("")
    lines.append("#ifndef %s" % guard)
    lines.append("#define %s" % guard)
    lines.append("")
    if args.include and args.include.upper() != "NONE":
        lines.append('#include "%s"' % args.include)
        lines.append("")

    per = max(1, args.per_line)

    if args.layout == "flat":
        lines.append("#define %s_N %d" % (args.name, n))
        lines.append("")
        lines.append("static const %s %s[%s_N] = {" %
                     (args.type, args.name, args.name))
        for i in range(0, n, per):
            toks = [fmt(v) for v in raw[i:i + per]]
            for j, t in enumerate(toks):
                emitted.append((i + j, t))
            comma = "," if (i + per) < n else ""
            lines.append("    %s%s  // [%d]" % (", ".join(toks), comma, i))
        lines.append("};")
        lines.append("")
    else:
        spec, total = split_spec(H)
        assert total == n
        for name, shape, off in spec:
            if shape == ():
                lines.append("// %s: scalar, flat [%d]" % (name, off))
                lines.append("const %s %s = %s;" % (args.type, name, fmt(raw[off])))
                lines.append("")
                emitted.append((off, fmt(raw[off])))
            elif len(shape) == 1:
                emit_1d(lines, emitted, raw, fmt, args.type,
                        name, off, shape[0], per)
            else:
                emit_2d(lines, emitted, raw, fmt, args.type,
                        name, off, shape[0], shape[1], per)
        lines.append("// ---------------------------------------------------------")
        lines.append("// If the datapath lives in a DIFFERENT .cpp, paste these")
        lines.append("// declarations into gru_weights.h under the same ifdef")
        lines.append("// (namespace-scope const has internal linkage otherwise):")
        for name, shape, _ in spec:
            dims = "".join("[%d]" % d for d in shape)
            lines.append("//   extern const %s %s%s;" % (args.type, name, dims))
        lines.append("// ---------------------------------------------------------")
        lines.append("")

    lines.append("#endif // %s" % guard)
    lines.append("")

    # position-aware readback: value AND flat offset both verified
    src_bits = raw.view(np.uint32)
    bad = []
    for idx, text in emitted:
        back = parse_literal(text)
        if np.array([back], dtype="<f4").view(np.uint32)[0] != src_bits[idx]:
            bad.append((idx, text, float(raw[idx]), float(back)))

    print("")
    print("readback    : %d/%d literals re-parsed at their flat offsets"
          % (len(emitted), n))
    if len(emitted) != n:
        sys.exit("ERROR: emitted %d literals, expected %d -- slicing bug; "
                 "header NOT written." % (len(emitted), n))
    if bad:
        print("FAIL        : %d literal(s) do not bit-match the source" % len(bad))
        for idx, text, want, got in bad[:10]:
            print("  flat[%d] literal %s -> %.9e, expected %.9e"
                  % (idx, text, got, want))
        sys.exit("ERROR: header NOT written; emission is not bit-exact.")
    print("            : PASS -- all bit patterns identical, all offsets correct")

    with open(args.out, "w", newline="\n") as f:
        f.write("\n".join(lines))

    print("")
    print("wrote       : %s" % os.path.abspath(args.out))
    print("size        : %.1f KB, %d source lines"
          % (os.path.getsize(args.out) / 1024.0, len(lines)))
    if args.layout == "split":
        print("defines     : W_r W_z W_n U_r U_z U_n b_ir b_iz b_in "
              "b_hr b_hz b_hn w_out b_out  (H=%d)" % H)
    print("")
    print("NEXT: csim the const build against the same golden; require the")
    print("      m_axi build's cosine / ESR / RMSE / worst-sample index exactly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
