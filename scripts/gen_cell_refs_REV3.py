#!/usr/bin/env python
# gen_cell_refs_REV3.py
# GENCELLREFS-REV3 (held-out program-source arm, HELDOUT-HANDOFF-REV1-20260906)
#
# REV3 vs REV2 (57631EFA0CA80D19A654F0AE70EF2EE8):
#   - argparse: --input <dry .f32> --tag <token> [--outdir DIR]; --help works.
#   - Generates ALL SIX cell refs (REV2 generated five; rodent_max's nam ref
#     pre-existed) for the given input: anchor_<tag>_ref32_<cell>.f32
#   - fail-if-exists on every output (REV2 skipped existing files).
#   - Expected byte count = 4 * N(input) (REV2 hard-coded 36,028,800 for nam).
#   - Self-MD5 + input MD5 printed; one append-only manifest row per ref.
#   - Inference path, gates A/B/C, CHUNK, model construction: UNCHANGED from
#     REV2 (op-for-op FREF5-REV2: time-major nn.GRU, (m,1,1) chunks, h0=0,
#     float32 CPU). Gate C still regenerates the nam anchor ref and
#     byte-compares it, so the path is re-certified on every invocation.
#
# Run on LENNY in the gru venv from the GRU working directory:
#   & "<VENV>\Scripts\Activate.ps1"
#   cd "<GRU_DIR>"
#   python gen_cell_refs_REV3.py --input <...>\anchor_bass_in.f32 --tag bass --outdir <...>
#
# GATES (all must pass; script aborts loudly on any failure):
#   GATE 0: no output file for this tag may already exist (fail-if-exists).
#   GATE A: rodent_max_v2 checkpoint flattens to the certified anchor
#           weights bytes (hls_testdata\weights_flat.bin, MD5 18ca9167...).
#   GATE B: full scan - every runs\*\best.pt flattened and compared against
#           every cell bin. Each cell must match EXACTLY ONE checkpoint.
#   GATE C: regenerate the nam anchor ref with this script's inference path
#           and byte-compare against the existing anchor_nam_ref32.f32.
#   Then:   generate anchor_<tag>_ref32_<cell>.f32 for all six cells;
#           verify 4*N bytes each and mutual distinctness; print birth
#           certificates; append manifest rows.

import sys, os, glob, hashlib, argparse, datetime, csv
import numpy as np
import torch

SENTINEL = "GENCELLREFS-REV3"

GRU_DIR = r"<GRU_DIR>"
RUNS    = os.path.join(GRU_DIR, "runs")
HLS_IO  = r"<HLS_IO>"
NAM_IN  = os.path.join(HLS_IO, "anchor_nam_in.f32")
NAM_REF = os.path.join(HLS_IO, "anchor_nam_ref32.f32")
NAM_REF_MD5 = "97e3bb545d3b8ae6e46b6fd89ce0f4e5"   # certified anchor ref (8/13 PM record)

CELL_BINS = {
    "rodent_max": os.path.join(GRU_DIR, "hls_testdata",            "weights_flat.bin"),
    "rodent_mod": os.path.join(GRU_DIR, "hls_testdata_rodent_mod", "weights_flat.bin"),
    "gt_max":     os.path.join(GRU_DIR, "hls_testdata_gt_max",     "weights_flat.bin"),
    "gt_mod":     os.path.join(GRU_DIR, "hls_testdata_gt_mod",     "weights_flat.bin"),
    "fl_max":     os.path.join(GRU_DIR, "hls_testdata_fl_max",     "weights_flat.bin"),
    "fl_mod":     os.path.join(GRU_DIR, "hls_testdata_fl_mod",     "weights_flat.bin"),
}
CELLS = ["rodent_max", "rodent_mod", "gt_max", "gt_mod", "fl_max", "fl_mod"]

# Pre-registered mapping (HIT 6/6 on 2026-08-13 and again on 2026-09-05)
PREDICTED = {
    "rodent_max": "rodent_max_v2",
    "rodent_mod": "rodent_mod_v2c",
    "gt_max":     "greentint_max_v2",
    "gt_mod":     "greentint_low_v2",
    "fl_max":     "fuzzylogic_max_v2",
    "fl_mod":     "fuzzylogic_mod_v2",
}

ANCHOR_WMD5 = "18ca916778ffaca0b0c2d937d3e6f04f"
CHUNK = 1 << 20  # 1M samples per GRU chunk (sequential recurrence: chunking is exact)

MANIFEST_COLS = ["file", "bytes", "md5", "cell", "ckpt_run", "input_file", "input_md5",
                 "input_samples", "script", "script_md5", "sentinel", "timestamp"]

def md5_bytes(b):
    return hashlib.md5(b).hexdigest()

def md5_file(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 22), b""):
            h.update(blk)
    return h.hexdigest()

def flatten_ckpt(path):
    """Load checkpoint, flatten to HLS layout (certified via GATE A). UNCHANGED from REV2."""
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    sd = ckpt["model"] if "model" in ckpt else ckpt
    order = ["gru.weight_ih_l0", "gru.weight_hh_l0", "gru.bias_ih_l0",
             "gru.bias_hh_l0", "head.weight", "head.bias"]
    if not all(k in sd for k in order):
        return None, None
    flat = np.concatenate([sd[k].detach().numpy().astype(np.float32).ravel()
                           for k in order])
    if flat.size != 5201:
        return None, None
    return md5_bytes(flat.tobytes()), sd

def build_model(sd):
    """UNCHANGED from REV2."""
    torch.set_grad_enabled(False)
    gru = torch.nn.GRU(1, 40, batch_first=False)
    head = torch.nn.Linear(40, 1)
    gru.weight_ih_l0.copy_(sd["gru.weight_ih_l0"])
    gru.weight_hh_l0.copy_(sd["gru.weight_hh_l0"])
    gru.bias_ih_l0.copy_(sd["gru.bias_ih_l0"])
    gru.bias_hh_l0.copy_(sd["gru.bias_hh_l0"])
    head.weight.copy_(sd["head.weight"])
    head.bias.copy_(sd["head.bias"])
    gru.eval(); head.eval()
    return gru, head

def run_inference(sd, x, out_path):
    """Full-length float32 CPU forward, h0=0, chunked with exact state carry. UNCHANGED from REV2."""
    gru, head = build_model(sd)
    n = x.size
    h = torch.zeros(1, 1, 40)
    with open(out_path, "wb") as f:
        done = 0
        while done < n:
            m = min(CHUNK, n - done)
            xin = torch.from_numpy(x[done:done + m]).reshape(m, 1, 1)
            y, h = gru(xin, h)
            out = head(y).reshape(m).numpy().astype(np.float32)
            f.write(out.tobytes())
            done += m
            print(f"    progress {done}/{n}", flush=True)

def append_manifest(path, row):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
        if new:
            w.writeheader()
        w.writerow(row)

def main():
    ap = argparse.ArgumentParser(description=f"{SENTINEL}: per-cell float32 refs for one dry input")
    ap.add_argument("--input", required=True, help="dry input .f32 (e.g. ...\\anchor_bass_in.f32)")
    ap.add_argument("--tag", required=True, help="source token used in output names, e.g. bass, gtr4ib")
    ap.add_argument("--outdir", default=HLS_IO, help="output dir for anchor_<tag>_ref32_<cell>.f32")
    ap.add_argument("--manifest", default=None,
                    help="append-only manifest CSV (default <outdir>\\heldout_refs_manifest.csv)")
    args = ap.parse_args()

    script_path = os.path.abspath(__file__)
    script_md5 = md5_file(script_path)
    print(f"== {SENTINEL} ==", flush=True)
    print(f"script {os.path.basename(script_path)}  {os.path.getsize(script_path)} bytes  MD5 {script_md5}")
    print(f"torch {torch.__version__}  numpy {np.__version__}")

    torch.set_num_threads(os.cpu_count() or 4)
    manifest = args.manifest or os.path.join(args.outdir, "heldout_refs_manifest.csv")

    # ---- preflight ----
    for p in [RUNS, HLS_IO, NAM_IN, NAM_REF, args.input] + list(CELL_BINS.values()):
        if not os.path.exists(p):
            print(f"FATAL: missing required path: {p}")
            sys.exit(1)
    os.makedirs(args.outdir, exist_ok=True)

    # GATE 0: fail-if-exists on every output for this tag
    outs = {cell: os.path.join(args.outdir, f"anchor_{args.tag}_ref32_{cell}.f32") for cell in CELLS}
    existing = [p for p in outs.values() if os.path.exists(p)]
    if existing:
        print("FATAL GATE 0: output already exists (fail-if-exists; annotate, never delete):")
        for p in existing:
            print(f"  {p}")
        sys.exit(1)
    print("GATE 0 PASS: no output for this tag exists yet", flush=True)

    in_md5 = md5_file(args.input)
    in_bytes = os.path.getsize(args.input)
    if in_bytes % 4 != 0:
        print(f"FATAL: input byte count {in_bytes} is not a multiple of 4")
        sys.exit(1)
    n_in = in_bytes // 4
    expect_ref_bytes = 4 * n_in
    print(f"input {args.input}: {n_in} samples ({in_bytes} bytes)  MD5 {in_md5}", flush=True)

    bins = {}
    for cell, p in CELL_BINS.items():
        b = open(p, "rb").read()
        if len(b) != 20804:
            print(f"FATAL: {p} is {len(b)} bytes, expected 20804")
            sys.exit(1)
        bins[cell] = md5_bytes(b)
    print("cell bins loaded:", flush=True)
    for cell, h in bins.items():
        print(f"  {cell}: {h}")

    # ---- GATE B scan (includes GATE A) ----
    print("scanning checkpoints under runs\\ ...", flush=True)
    ckpt_md5 = {}
    ckpt_sd  = {}
    for path in sorted(glob.glob(os.path.join(RUNS, "*", "best.pt"))):
        run = os.path.basename(os.path.dirname(path))
        try:
            h, sd = flatten_ckpt(path)
        except Exception as e:
            print(f"  {run}: LOAD ERROR ({e})")
            continue
        if h is None:
            print(f"  {run}: SKIP (unexpected structure)")
            continue
        ckpt_md5[run] = h
        ckpt_sd[run] = sd
        print(f"  {run}: {h}", flush=True)

    a = ckpt_md5.get("rodent_max_v2")
    if a != ANCHOR_WMD5 or bins["rodent_max"] != ANCHOR_WMD5:
        print(f"FATAL GATE A: rodent_max_v2 flat={a}, anchor bin={bins['rodent_max']}, expected {ANCHOR_WMD5}")
        sys.exit(1)
    print("GATE A PASS: flattening layout certified against anchor bytes", flush=True)

    mapping = {}
    fail = False
    for cell, bh in bins.items():
        matches = [run for run, h in ckpt_md5.items() if h == bh]
        pred = PREDICTED[cell]
        if len(matches) == 1:
            mapping[cell] = matches[0]
            grade = "HIT" if matches[0] == pred else f"MISS (predicted {pred})"
            print(f"GATE B {cell}: matched {matches[0]}  [{grade}]")
        elif len(matches) == 0:
            print(f"GATE B {cell}: NO MATCH among {len(ckpt_md5)} checkpoints  [predicted {pred}]")
            fail = True
        else:
            print(f"GATE B {cell}: MULTIPLE MATCHES {matches} - identical weights in several runs")
            fail = True
    if fail:
        print("FATAL GATE B: mapping unresolved; refs NOT generated")
        sys.exit(1)
    print("GATE B PASS: all six cells mapped uniquely", flush=True)

    # ---- GATE C: inference-path certification on the nam anchor ----
    xn = np.fromfile(NAM_IN, dtype=np.float32)
    print(f"nam input: {xn.size} samples ({xn.size*4} bytes)", flush=True)
    tmp = os.path.join(args.outdir, f"gencellrefs_rev3_selfcert_nam_{args.tag}.f32.tmp")
    if os.path.exists(tmp):
        print(f"FATAL: stale temp exists: {tmp}")
        sys.exit(1)
    print("GATE C: regenerating nam anchor ref for byte comparison ...", flush=True)
    run_inference(ckpt_sd[mapping["rodent_max"]], xn, tmp)
    got, want = md5_file(tmp), md5_file(NAM_REF)
    os.remove(tmp)
    if want != NAM_REF_MD5:
        print(f"FATAL GATE C: on-disk anchor_nam_ref32.f32 {want} != certified {NAM_REF_MD5}")
        sys.exit(1)
    if got != want:
        print(f"FATAL GATE C: regenerated {got} != existing anchor_nam_ref32 {want}")
        print("  inference path is NOT equivalent to FREF5-REV2; do not generate refs.")
        sys.exit(1)
    print(f"GATE C PASS: inference path reproduces anchor_nam_ref32.f32 byte-exactly ({got})", flush=True)
    del xn

    # ---- generate the six per-cell refs on the held-out input ----
    x = np.fromfile(args.input, dtype=np.float32)
    if x.size != n_in:
        print(f"FATAL: input reread size {x.size} != {n_in}")
        sys.exit(1)
    certs = {}
    for cell in CELLS:
        out = outs[cell]
        print(f"{cell}: generating from {mapping[cell]} ...", flush=True)
        run_inference(ckpt_sd[mapping[cell]], x, out)
        nbytes = os.path.getsize(out)
        h = md5_file(out)
        certs[cell] = h
        status = "OK" if nbytes == expect_ref_bytes else f"LENGTH FAIL ({nbytes} != {expect_ref_bytes})"
        print(f"{cell}: {os.path.basename(out)}  {nbytes} bytes  MD5 {h}  [{status}]", flush=True)
        if nbytes != expect_ref_bytes:
            sys.exit(1)
        append_manifest(manifest, {
            "file": os.path.basename(out), "bytes": nbytes, "md5": h, "cell": cell,
            "ckpt_run": mapping[cell], "input_file": os.path.basename(args.input),
            "input_md5": in_md5, "input_samples": n_in,
            "script": os.path.basename(script_path), "script_md5": script_md5,
            "sentinel": SENTINEL,
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        })

    if len(set(certs.values())) != len(certs):
        print("FATAL: two refs share an MD5 - wiring error, do not use")
        sys.exit(1)
    print("distinctness PASS: all six refs mutually distinct", flush=True)

    print(f"== {SENTINEL} COMPLETE ==  tag={args.tag}  input_md5={in_md5}  samples={n_in}")
    print(f"manifest: {manifest}")
    print("birth certificates:")
    for cell, h in certs.items():
        print(f"  {cell}: anchor_{args.tag}_ref32_{cell}.f32  {expect_ref_bytes} B  {h}")

if __name__ == "__main__":
    main()
