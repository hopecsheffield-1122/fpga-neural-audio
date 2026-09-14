#!/usr/bin/env python
# gen_cell_refs_REV2.py
# REV2: inference path aligned op-for-op with FREF5-REV2 (gen_float_refs.py):
#       time-major GRU (batch_first=False), (m,1,1) sequence chunks.
# GENCELLREFS-REV2
# B2 support: verify cell->checkpoint mapping by byte comparison, then
# generate per-cell float32 references on the nam anchor input.
#
# Run on LENNY in the gru venv from the GRU working directory:
#   & "<VENV>\Scripts\Activate.ps1"
#   cd "<GRU_DIR>"
#   python gen_cell_refs_REV1.py
#
# GATES (all must pass; script aborts loudly on any failure):
#   GATE A: rodent_max_v2 checkpoint flattens to the certified anchor
#           weights bytes (hls_testdata\weights_flat.bin, MD5 18ca9167...).
#           Certifies the HLS flattening layout.
#   GATE B: full scan - every runs\*\best.pt flattened and compared against
#           every cell bin. Each cell must match EXACTLY ONE checkpoint.
#           Predicted mapping (pre-registered) is graded HIT/MISS.
#   GATE C: regenerate the nam anchor ref with this script's inference path
#           and byte-compare against the existing anchor_nam_ref32.f32.
#           Certifies the inference path == FREF5-REV2 path.
#   Then:   generate anchor_nam_ref32_<cell>.f32 for the five non-anchor
#           cells; verify 36,028,800 bytes each and mutual distinctness;
#           print birth certificates.

import sys, os, glob, hashlib
import numpy as np
import torch

SENTINEL = "GENCELLREFS-REV2"
print(f"== {SENTINEL} ==", flush=True)

GRU_DIR = r"<GRU_DIR>"
RUNS    = os.path.join(GRU_DIR, "runs")
HLS_IO  = r"<HLS_IO>"
NAM_IN  = os.path.join(HLS_IO, "anchor_nam_in.f32")
NAM_REF = os.path.join(HLS_IO, "anchor_nam_ref32.f32")

CELL_BINS = {
    "rodent_max": os.path.join(GRU_DIR, "hls_testdata",            "weights_flat.bin"),
    "rodent_mod": os.path.join(GRU_DIR, "hls_testdata_rodent_mod", "weights_flat.bin"),
    "gt_max":     os.path.join(GRU_DIR, "hls_testdata_gt_max",     "weights_flat.bin"),
    "gt_mod":     os.path.join(GRU_DIR, "hls_testdata_gt_mod",     "weights_flat.bin"),
    "fl_max":     os.path.join(GRU_DIR, "hls_testdata_fl_max",     "weights_flat.bin"),
    "fl_mod":     os.path.join(GRU_DIR, "hls_testdata_fl_mod",     "weights_flat.bin"),
}

# Pre-registered prediction (from sweep workbook, 2026-08-13)
PREDICTED = {
    "rodent_max": "rodent_max_v2",
    "rodent_mod": "rodent_mod_v2c",
    "gt_max":     "greentint_max_v2",
    "gt_mod":     "greentint_low_v2",
    "fl_max":     "fuzzylogic_max_v2",
    "fl_mod":     "fuzzylogic_mod_v2",
}

ANCHOR_WMD5 = "18ca916778ffaca0b0c2d937d3e6f04f"
EXPECT_REF_BYTES = 36028800
CHUNK = 1 << 20  # 1M samples per GRU chunk (sequential recurrence: chunking is exact)

def md5_bytes(b):
    return hashlib.md5(b).hexdigest()

def md5_file(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 22), b""):
            h.update(blk)
    return h.hexdigest()

def flatten_ckpt(path):
    """Load checkpoint, flatten to HLS layout (certified via GATE A)."""
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
    """Full-length float32 CPU forward, h0=0, chunked with exact state carry."""
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

def main():
    torch.set_num_threads(os.cpu_count() or 4)

    # ---- preflight ----
    for p in [RUNS, HLS_IO, NAM_IN, NAM_REF] + list(CELL_BINS.values()):
        if not os.path.exists(p):
            print(f"FATAL: missing required path: {p}")
            sys.exit(1)

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
    ckpt_md5 = {}   # run_name -> flat md5
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

    # GATE A
    a = ckpt_md5.get("rodent_max_v2")
    if a != ANCHOR_WMD5 or bins["rodent_max"] != ANCHOR_WMD5:
        print(f"FATAL GATE A: rodent_max_v2 flat={a}, anchor bin={bins['rodent_max']}, expected {ANCHOR_WMD5}")
        sys.exit(1)
    print("GATE A PASS: flattening layout certified against anchor bytes", flush=True)

    # GATE B: exactly-one match per cell
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

    # ---- GATE C: inference-path certification on the anchor ----
    x = np.fromfile(NAM_IN, dtype=np.float32)
    print(f"nam input: {x.size} samples ({x.size*4} bytes)", flush=True)
    tmp = os.path.join(HLS_IO, "gencellrefs_selfcert_nam.f32.tmp")
    print("GATE C: regenerating nam anchor ref for byte comparison ...", flush=True)
    run_inference(ckpt_sd[mapping["rodent_max"]], x, tmp)
    got, want = md5_file(tmp), md5_file(NAM_REF)
    if got != want:
        print(f"FATAL GATE C: regenerated {got} != existing anchor_nam_ref32 {want}")
        print("  inference path is NOT equivalent to FREF5-REV2; locate the")
        print("  original generator script before per-cell refs can be made.")
        sys.exit(1)
    os.remove(tmp)
    print(f"GATE C PASS: inference path reproduces anchor_nam_ref32.f32 byte-exactly ({got})", flush=True)

    # ---- generate the five per-cell refs ----
    certs = {"rodent_max": want}
    for cell in ["rodent_mod", "gt_max", "gt_mod", "fl_max", "fl_mod"]:
        out = os.path.join(HLS_IO, f"anchor_nam_ref32_{cell}.f32")
        if os.path.exists(out):
            print(f"{cell}: {out} already exists - SKIP (delete manually to regenerate)")
            certs[cell] = md5_file(out)
            continue
        print(f"{cell}: generating from {mapping[cell]} ...", flush=True)
        run_inference(ckpt_sd[mapping[cell]], x, out)
        nbytes = os.path.getsize(out)
        h = md5_file(out)
        certs[cell] = h
        status = "OK" if nbytes == EXPECT_REF_BYTES else f"LENGTH FAIL ({nbytes})"
        print(f"{cell}: {os.path.basename(out)}  {nbytes} bytes  MD5 {h}  [{status}]", flush=True)
        if nbytes != EXPECT_REF_BYTES:
            sys.exit(1)

    # mutual distinctness
    if len(set(certs.values())) != len(certs):
        print("FATAL: two refs share an MD5 - wiring error, do not use")
        sys.exit(1)
    print("distinctness PASS: all six refs mutually distinct", flush=True)

    print(f"== {SENTINEL} COMPLETE ==")
    print("birth certificates:")
    for cell, h in certs.items():
        print(f"  {cell}: {h}")

if __name__ == "__main__":
    main()
