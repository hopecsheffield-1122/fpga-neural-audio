#!/usr/bin/env python3
"""
train_spike.py
==============
One-cell training spike: single-layer GRU virtual-analog model of a ToneTwist
Rodent setting, per the locked recipe.

  model     : nn.GRU(1, H=32, 1 layer) + Linear(H, 1), zero init state
  loss      : pre-emphasized ESR (1 - 0.85 z^-1 high-pass) + DC term
              [A-weighting is the documented upgrade after the spike; the
               first-order HP is per-chunk-safe for TBPTT]
  training  : TBPTT 1024, washout 1024 (no grad/loss), hidden detached
              between chunks, grads accumulated per chunk, one optimizer
              step per batch; Adam 3e-4, batch 32, grad-norm clip 1.0
  schedule  : ReduceLROnPlateau(patience=20, factor=0.5) on val loss,
              early stop patience 50
  metric    : plain ESR in dB on the val tail -- compare against the cell's
              own noise floor (moderate Rodent cell: -31.4 dB; success is
              approaching it from above; the well-trained band is roughly
              -30 to -13 dB)

COLAB USAGE
-----------
    !pip -q install soundfile
    from google.colab import drive; drive.mount('/content/drive')
    %cd "/content/drive/MyDrive/GRU"          # folder w/ this + gru_data.py
    !python train_spike.py \
        --csv rat2_noise_report/alignment_report.csv \
        --clean ToneTwist/DRY-with-markers \
        --wet ToneTwist/HarleyBenton-Rodent \
        --setting V100_F050_D050_M000 \
        --cache cell_cache \
        --out runs/rodent_moderate

--cache saves the assembled cell to an .npz after the first load, so later
runs skip the slow Drive reads. Smoke-test first with:
    ... --epochs 2 --segs-per-epoch 64
"""

import argparse
import os
import time

import numpy as np
import torch
import torch.nn as nn

import gru_data as gd


# ----------------------------------------------------------------------------
# Model
# ----------------------------------------------------------------------------

class GRUVA(nn.Module):
    """Single-layer GRU virtual-analog model: 1 -> H -> 1, with input skip
    OPTIONAL (default off): ToneTwist's dry inputs are level-randomized
    +/-20 dB every 5 s, making the dry->wet gain strongly level-dependent;
    a unit skip was measured harmful on this data. --skip enables it for
    ablation on fixed-drive captures."""

    def __init__(self, hidden=32, skip=False):
        super().__init__()
        self.gru = nn.GRU(1, hidden, batch_first=True)
        self.head = nn.Linear(hidden, 1)
        self.skip = skip

    def forward(self, x, h=None):
        """x: [B, T, 1] -> y: [B, T], h: [1, B, H]"""
        z, h = self.gru(x, h)
        y = self.head(z).squeeze(-1)
        if self.skip:
            y = y + x.squeeze(-1)
        return y, h


# ----------------------------------------------------------------------------
# Loss + metrics
# ----------------------------------------------------------------------------

def a_weighting_fir(sr, taps=511):
    """Linear-phase FIR approximation of the analytic A-weighting curve
    (IEC 61672), 0 dB at 1 kHz, designed by frequency sampling + Hamming.
    At 511 taps: <0.9 dB error at 100-200 Hz, <0.15 dB above; below 100 Hz
    it keeps attenuating, which is all a training loss needs."""
    n = 4096
    f = np.linspace(0, sr / 2, n)
    f2 = f ** 2
    ra = (12194.0 ** 2 * f2 ** 2) / (
        (f2 + 20.6 ** 2)
        * np.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2))
        * (f2 + 12194.0 ** 2) + 1e-30)
    ra = ra / ra[np.argmin(np.abs(f - 1000.0))]      # 0 dB @ 1 kHz
    h = np.fft.irfft(ra, 2 * (n - 1))
    h = np.roll(h, taps // 2)[:taps] * np.hamming(taps)
    return h.astype(np.float32)


class PreEmph(torch.nn.Module):
    """Pre-emphasis as FIR convolution with cross-chunk context.

    filt(x) expects x to carry (taps-1) CONTEXT samples up front and returns
    exactly len(x) - (taps-1) filtered samples, so chunked filtering with the
    previous chunk's tail as context is sample-identical to filtering the
    whole sequence at once (verified in tests). 'hp' = 1 - 0.85 z^-1 (2 taps);
    'aw' = 255-tap A-weighting."""

    def __init__(self, kind="hp", sr=48000):
        super().__init__()
        if kind == "hp":
            k = np.array([1.0, -0.85], np.float32)
        elif kind == "aw":
            k = a_weighting_fir(sr)
        else:
            raise ValueError(f"unknown preemph {kind!r}")
        self.kind, self.taps = kind, len(k)
        # torch conv1d cross-correlates -> store kernel time-reversed
        self.register_buffer("w", torch.from_numpy(k[::-1].copy())
                             .view(1, 1, -1))

    @property
    def ctx(self):
        return self.taps - 1

    def filt(self, x):
        """x: [B, ctx + T] -> [B, T]"""
        return torch.nn.functional.conv1d(x.unsqueeze(1), self.w).squeeze(1)


def esr_loss(yf, ypf, eps=1e-8):
    """ESR on pre-filtered signals, energies summed over the batch (silent
    elements are diluted rather than dividing by ~zero)."""
    return ((yf - ypf) ** 2).sum() / (yf.pow(2).sum() + eps)


def dc_loss(y, yp, eps=1e-8):
    return (y - yp).mean(dim=1).pow(2).mean() / (y.pow(2).mean() + eps)


@torch.no_grad()
def evaluate(model, pe, x, y, washout, device, batch=32):
    """Plain ESR (dB) + pre-emphasized loss over a segment set. Full-segment
    forward per batch; washout region excluded from all sums; the filter is
    seeded with the washout tail so no edge transient enters the loss."""
    model.eval()
    err2 = sig2 = 0.0
    pe_loss = n_b = 0
    for i in range(0, len(x), batch):
        xb = torch.from_numpy(x[i:i + batch]).to(device)
        yb = torch.from_numpy(y[i:i + batch]).to(device)
        yp, _ = model(xb.unsqueeze(-1))
        yf = pe.filt(yb[:, washout - pe.ctx:])
        ypf = pe.filt(yp[:, washout - pe.ctx:])
        yb, yp = yb[:, washout:], yp[:, washout:]
        err2 += float(((yb - yp) ** 2).sum())
        sig2 += float((yb ** 2).sum())
        pe_loss += float(esr_loss(yf, ypf) + dc_loss(yb, yp))
        n_b += 1
    model.train()
    esr_db = 10.0 * np.log10(err2 / max(sig2, 1e-12) + 1e-12)
    return esr_db, pe_loss / max(n_b, 1)


# ----------------------------------------------------------------------------
# Cell assembly with npz cache
# ----------------------------------------------------------------------------

def get_cell(args):
    cache = None
    if args.cache:
        os.makedirs(args.cache, exist_ok=True)
        suffix = "_nofail" if args.exclude_fail else ""
        cache = os.path.join(
            args.cache,
            f"{args.setting.upper()}{suffix}"
            f"_t{args.tbptt}_w{args.washout}_k{args.k}.npz")
    if cache and os.path.exists(cache):
        print(f"loading cached cell: {cache}")
        z = np.load(cache)
        # verify geometry: a cache may NEVER silently substitute a config
        for name, want in (("tbptt", args.tbptt), ("washout", args.washout)):
            got = int(z[name])
            if got != want:
                raise ValueError(
                    f"cache {cache} has {name}={got}, args say {want}; "
                    "delete the cache or fix the args")
        cell = gd.CellData(setting=args.setting.upper(), sr=int(z["sr"]),
                           seg_len=int(z["seg_len"]), tbptt=int(z["tbptt"]),
                           washout=int(z["washout"]))
        cell.train_x, cell.train_y = z["train_x"], z["train_y"]
        cell.val_x, cell.val_y = z["val_x"], z["val_y"]
        return cell
    cell = gd.load_cell(args.csv, args.clean, args.wet, args.setting,
                        tbptt=args.tbptt, washout=args.washout, k=args.k,
                        include_fail=not args.exclude_fail)
    if cache:
        np.savez(cache, sr=cell.sr, seg_len=cell.seg_len, tbptt=cell.tbptt,
                 washout=cell.washout,
                 train_x=cell.train_x, train_y=cell.train_y,
                 val_x=cell.val_x, val_y=cell.val_y)
        print(f"cached cell -> {cache}")
    return cell


# ----------------------------------------------------------------------------
# Training loop
# ----------------------------------------------------------------------------

def train(args):
    device = torch.device(args.device if args.device else
                          ("cuda" if torch.cuda.is_available() else "cpu"))
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    os.makedirs(args.out, exist_ok=True)

    cell = get_cell(args)
    print(f"device={device}  cell={cell.setting}  "
          f"train={len(cell.train_x)} val={len(cell.val_x)} "
          f"seg_len={cell.seg_len}")

    model = GRUVA(hidden=args.hidden, skip=args.skip).to(device)
    pe = PreEmph(args.preemph, sr=cell.sr).to(device)
    assert cell.washout >= pe.ctx, "washout must cover the filter context"
    print(f"pre-emphasis: {pe.kind} ({pe.taps} taps)")
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(
        opt, factor=0.5, patience=20)

    chunks = list(gd.iterate_tbptt(cell.seg_len, cell.tbptt, cell.washout))
    n_loss_chunks = sum(1 for *_, wo in chunks if not wo)

    best_val, best_epoch = float("inf"), -1
    log_path = os.path.join(args.out, "train_log.csv")
    with open(log_path, "w") as f:
        f.write("epoch,train_loss,val_loss,val_esr_db,lr,seconds\n")

    n_recoveries = 0
    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        nan_batches = 0
        order = np.random.permutation(len(cell.train_x))
        if args.segs_per_epoch:
            order = order[:args.segs_per_epoch]

        tot_loss, n_batches = 0.0, 0
        for i in range(0, len(order), args.batch):
            idx = order[i:i + args.batch]
            xb = torch.from_numpy(cell.train_x[idx]).to(device)
            yb = torch.from_numpy(cell.train_y[idx]).to(device)

            opt.zero_grad()
            h = None
            ctx_y = ctx_p = None        # filter context: prev chunk tails
            batch_loss = 0.0
            bad_batch = False
            for cs, ce, wo in chunks:
                xc = xb[:, cs:ce].unsqueeze(-1)
                if wo:                              # washout: no grad, no loss
                    with torch.no_grad():
                        yp, h = model(xc, h)
                    ctx_y = yb[:, ce - pe.ctx:ce]
                    ctx_p = yp[:, -pe.ctx:]
                    continue
                yp, h = model(xc, h)
                yf = pe.filt(torch.cat([ctx_y, yb[:, cs:ce]], dim=1))
                ypf = pe.filt(torch.cat([ctx_p, yp], dim=1))
                loss = (esr_loss(yf, ypf)
                        + dc_loss(yb[:, cs:ce], yp)) / n_loss_chunks
                if not torch.isfinite(loss):        # NaN guard: drop batch
                    bad_batch = True
                    break
                loss.backward()                     # accumulate grads
                ctx_y = yb[:, ce - pe.ctx:ce]
                ctx_p = yp[:, -pe.ctx:].detach()    # truncate through filter
                h = h.detach()                      # truncate BPTT
                batch_loss += loss.detach().item()
            if not bad_batch:
                gnorm = nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                bad_batch = not torch.isfinite(gnorm)
            if bad_batch:                           # skip poisoned update
                opt.zero_grad()
                nan_batches += 1
                continue
            opt.step()
            tot_loss += batch_loss
            n_batches += 1

        if nan_batches:
            print(f"  [warn] {nan_batches} non-finite batch(es) skipped")
        # weights themselves poisoned, or an epoch badly infested:
        # restore best checkpoint, halve LR, continue (loud recovery)
        params_bad = not all(torch.isfinite(p).all()
                             for p in model.parameters())
        attempted = n_batches + nan_batches
        infested = nan_batches >= 2 and nan_batches * 4 > attempted
        if params_bad or infested:
            n_recoveries += 1
            best_path = os.path.join(args.out, "best.pt")
            if n_recoveries > 3 or not os.path.exists(best_path):
                print("[abort] repeated instability; config is not viable "
                      "at this LR. Best checkpoint (if any) is intact.")
                break
            ck = torch.load(best_path, map_location=device,
                            weights_only=False)
            model.load_state_dict(ck["model"])
            for pg in opt.param_groups:
                pg["lr"] *= 0.5
            opt.state.clear()                       # reset Adam moments
            print(f"[recover {n_recoveries}/3] restored best.pt "
                  f"(epoch {ck['epoch']}), LR halved to "
                  f"{opt.param_groups[0]['lr']:.1e}")
            continue

        val_esr_db, val_loss = evaluate(model, pe, cell.val_x, cell.val_y,
                                        cell.washout, device, args.batch)
        sched.step(val_loss)
        lr_now = opt.param_groups[0]["lr"]
        dt = time.time() - t0
        train_loss = tot_loss / max(n_batches, 1)
        print(f"epoch {epoch:4d}  train {train_loss:.4f}  "
              f"val {val_loss:.4f}  val ESR {val_esr_db:+7.2f} dB  "
              f"lr {lr_now:.1e}  {dt:.0f}s")
        with open(log_path, "a") as f:
            f.write(f"{epoch},{train_loss:.6f},{val_loss:.6f},"
                    f"{val_esr_db:.3f},{lr_now:.2e},{dt:.1f}\n")

        if val_loss < best_val:
            best_val, best_epoch = val_loss, epoch
            torch.save({"model": model.state_dict(), "epoch": epoch,
                        "val_esr_db": val_esr_db, "setting": cell.setting,
                        "hidden": args.hidden, "skip": args.skip,
                        "preemph": args.preemph},
                       os.path.join(args.out, "best.pt"))
        if epoch - best_epoch >= args.early_stop:
            print(f"early stop: no val improvement for {args.early_stop} "
                  f"epochs (best @ {best_epoch})")
            break

    print(f"done. best val loss {best_val:.4f} @ epoch {best_epoch}; "
          f"checkpoint + log in {args.out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="alignment_report.csv")
    ap.add_argument("--clean", required=True, help="dry dir")
    ap.add_argument("--wet", required=True, help="wet dir")
    ap.add_argument("--setting", required=True,
                    help="cell token, e.g. V100_F050_D050_M000")
    ap.add_argument("--out", default="./run", help="checkpoints + log dir")
    ap.add_argument("--cache", default="", help="dir for cell .npz cache")
    ap.add_argument("--hidden", type=int, default=32)
    ap.add_argument("--preemph", choices=["hp", "aw"], default="hp",
                    help="loss pre-emphasis: hp = 1-0.85z^-1 (reference), "
                         "aw = A-weighting (511-tap FIR)")
    ap.add_argument("--skip", action="store_true",
                    help="enable the input skip connection (measured harmful "
                         "on ToneTwist's level-randomized dry inputs)")
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--epochs", type=int, default=500)
    ap.add_argument("--early-stop", type=int, default=50)
    ap.add_argument("--tbptt", type=int, default=1024)
    ap.add_argument("--washout", type=int, default=1024)
    ap.add_argument("--k", type=int, default=45,
                    help="TBPTT chunks per segment (seg = washout + k*tbptt)")
    ap.add_argument("--segs-per-epoch", type=int, default=0,
                    help="random subset of train segments per epoch (0 = all)")
    ap.add_argument("--device", default="", help="cuda / cpu (auto if empty)")
    ap.add_argument("--exclude-fail", action="store_true",
                    help="drop FAIL-verdict pairs from train AND val "
                         "(uses a separate cell cache)")
    ap.add_argument("--seed", type=int, default=0)
    train(ap.parse_args())


if __name__ == "__main__":
    main()
