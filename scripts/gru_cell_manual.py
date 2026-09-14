#!/usr/bin/env python3
"""
gru_cell_manual.py
==================
Explicit (non-cuDNN) GRU virtual-analog model, parameter-compatible with
train_spike.GRUVA checkpoints.

Why this exists: nn.GRU fuses sigmoid/tanh inside its kernel, so the
activations cannot be swapped for Hardsigmoid/Hardtanh without rewriting the
recurrence. This module keeps nn.GRU as PARAMETER STORAGE ONLY (identical
state-dict keys: gru.weight_ih_l0, gru.weight_hh_l0, gru.bias_ih_l0,
gru.bias_hh_l0, head.weight, head.bias) and computes the forward pass
manually, so:

  * existing best.pt checkpoints load directly (strict=True),
  * export_gru_weights.py continues to work unchanged,
  * act="exact"  -> true sigmoid/tanh, must match nn.GRU to float precision
                    (validated by test_cell_equivalence.py BEFORE any use),
  * act="hard"   -> Hardsigmoid/Hardtanh per DPD-NeuralEngine
                    (arXiv:2410.11766 eq. 7/8), matching the HLS kernel:
                      hardsigmoid(v) = clamp(0.25*v + 0.5, 0, 1)   [HLS: (v>>2)+0.5]
                      hardtanh(v)    = clamp(v, -1, 1)

CRITICAL: torch.nn.functional.hardsigmoid is clamp(x/6+0.5, 0, 1) -- a
DIFFERENT function (slope 1/6, knees at +/-3). It must NOT be used here;
the custom 0.25 form below is what matches the hardware shift-by-2.

Gate math (PyTorch convention, reset-after-matmul):
  r = sig(W_ir x + b_ir + W_hr h + b_hr)
  z = sig(W_iz x + b_iz + W_hz h + b_hz)
  n = tanh(W_in x + b_in + r * (W_hn h + b_hn))     # b_hn gated, b_in not
  h' = (1 - z) * n + z * h
"""

import torch
import torch.nn as nn


def hard_sigmoid_q4(v):
    """Hardsigmoid, DPD-NeuralEngine eq. 7 / HLS (v>>2)+0.5 form.
    NOT torch.nn.functional.hardsigmoid (which is the /6 variant)."""
    return torch.clamp(0.25 * v + 0.5, 0.0, 1.0)


def hard_tanh_q(v):
    """Hardtanh, DPD-NeuralEngine eq. 8 (== F.hardtanh defaults)."""
    return torch.clamp(v, -1.0, 1.0)


def hard_sigmoid_ste(v):
    """Surrogate-gradient Hardsigmoid: FORWARD is exactly hard_sigmoid_q4
    (bit-identical to the HLS), BACKWARD uses sigmoid's derivative.
    Rationale (measured, gate_saturation_diag): 74% of z pre-activations sit
    in |v|>2 where clamp's gradient is exactly 0 -> 20/40 update gates
    permanently dead under plain hard fine-tuning. sigmoid' is nonzero there
    (revives them) and matches the 0.25 hard slope at v=0 (no bias in the
    linear region)."""
    s = torch.sigmoid(v)
    return s + (hard_sigmoid_q4(v) - s).detach()


def hard_tanh_ste(v):
    """Surrogate-gradient Hardtanh: forward exact hard, backward tanh'.
    tanh' < 1 restores the recurrent contraction that hardtanh's unit slope
    removes -- the mechanism behind the non-finite gradient batches seen in
    plain hard fine-tuning at t2048."""
    s = torch.tanh(v)
    return s + (hard_tanh_q(v) - s).detach()


class GRUVAManual(nn.Module):
    """Drop-in replacement for train_spike.GRUVA with explicit recurrence.

    act: "exact" (sigmoid/tanh) or "hard" (Hardsigmoid/Hardtanh as above).
    """

    def __init__(self, hidden=40, skip=False, act="exact"):
        super().__init__()
        if act not in ("exact", "hard", "hard_ste"):
            raise ValueError(
                f"act must be 'exact', 'hard', or 'hard_ste', got {act!r}")
        self.gru = nn.GRU(1, hidden, batch_first=True)  # parameter storage only
        self.head = nn.Linear(hidden, 1)
        self.skip = skip
        self.act = act

    # -- activations ---------------------------------------------------------
    # "hard_ste": forward identical to "hard" (same numbers, same golden),
    # backward through smooth surrogates. Use for TRAINING only; saved
    # checkpoints should record act="hard" since inference is equivalent.
    def _sig(self, v):
        if self.act == "hard":
            return hard_sigmoid_q4(v)
        if self.act == "hard_ste":
            return hard_sigmoid_ste(v)
        return torch.sigmoid(v)

    def _tanh(self, v):
        if self.act == "hard":
            return hard_tanh_q(v)
        if self.act == "hard_ste":
            return hard_tanh_ste(v)
        return torch.tanh(v)

    # -- forward -------------------------------------------------------------
    def forward(self, x, h=None):
        """x: [B, T, 1] -> y: [B, T], h: [1, B, H]  (same contract as GRUVA)"""
        B, T, _ = x.shape
        H = self.gru.hidden_size

        W_ih = self.gru.weight_ih_l0        # [3H, 1], rows r|z|n
        W_hh = self.gru.weight_hh_l0        # [3H, H], rows r|z|n
        b_ih = self.gru.bias_ih_l0          # [3H]
        b_hh = self.gru.bias_hh_l0          # [3H]

        ht = x.new_zeros(B, H) if h is None else h.squeeze(0)

        # Input-side projections for all timesteps at once: [B, T, 3H]
        xp = torch.matmul(x, W_ih.t()) + b_ih
        xr, xz, xn = xp.split(H, dim=2)

        Wr, Wz, Wn = W_hh.split(H, dim=0)       # each [H, H]
        bhr, bhz, bhn = b_hh.split(H, dim=0)    # each [H]

        outs = []
        for t in range(T):
            hr = torch.matmul(ht, Wr.t()) + bhr
            hz = torch.matmul(ht, Wz.t()) + bhz
            hn = torch.matmul(ht, Wn.t()) + bhn          # b_hn INSIDE the gate
            r = self._sig(xr[:, t] + hr)
            z = self._sig(xz[:, t] + hz)
            n = self._tanh(xn[:, t] + r * hn)            # reset-after-matmul
            ht = (1.0 - z) * n + z * ht
            outs.append(ht)

        zs = torch.stack(outs, dim=1)                    # [B, T, H]
        y = self.head(zs).squeeze(-1)
        if self.skip:
            y = y + x.squeeze(-1)
        return y, ht.unsqueeze(0)
