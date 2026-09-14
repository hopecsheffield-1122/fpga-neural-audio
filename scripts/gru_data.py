#!/usr/bin/env python3
"""
gru_data.py
===========
Data loading + segmentation for the ToneTwist GRU virtual-analog spike.

Consumes alignment_report.csv (from tonetwist_verify_alignment.py) and
implements the locked preprocessing protocol:

  * SPLIT ENFORCEMENT (hard guard, not convention): load_cell takes a
    `split` parameter (default "trainval") and every resolved file path is
    validated to live under that split folder, judged RELATIVE to the
    search root (so a stray 'test'/'trainval' component elsewhere in the
    project path cannot silently satisfy or defeat the guard). Rows
    resolving outside the split raise immediately with the offending files
    listed. The official ToneTwist test split (idmt-bass, idmt-gtr4-ib) is
    reserved for final evaluation: use split="test" explicitly for that,
    or split=None to disable the guard (deliberate use only).
  * UNSHIFTED alignment: both dry and wet are sliced at the CLEAN trim
    columns (trim_from_clean:trim_to_clean). Content cross-correlation showed
    zero transport delay across all settings; the marker-peak offsets are the
    filter stage's group delay, retained in the target mapping to preserve
    causality for the recurrent model.
  * DC removal per slice (mean subtraction). Loudness normalization is an
    EVALUATION step, not a training step -- do not add it here.
  * Segmentation into fixed-length windows sized as
        seg_len = washout + k * tbptt
    so each segment is a washout chunk (hidden-state warm-up, no loss)
    followed by exactly k TBPTT chunks (loss, hidden detached between chunks).
  * Train/val split by contiguous TAIL per source file (last val_frac of each
    source's segments), so val material is not interleaved with train.

Typical use (PyTorch):

    import gru_data as gd
    cell = gd.load_cell("alignment_report.csv",
                        "ToneTwist/DRY-with-markers",
                        "ToneTwist/HarleyBenton-Rodent",
                        setting="V100_F050_D050_M000",
                        tbptt=1024, washout=1024, k=45)   # ~1 s segments
    # split="trainval" is the default; final test evaluation uses
    # split="test" with a test-only alignment CSV.

    # cell.train_x/train_y/val_x/val_y: float32 [N, seg_len]
    for xb, yb in batches(cell.train_x, cell.train_y, batch=32):
        h = None                                  # zero init per segment
        opt.zero_grad(); loss = 0.0
        for s, e, is_washout in gd.iterate_tbptt(cell.seg_len,
                                                 cell.tbptt, cell.washout):
            with torch.set_grad_enabled(not is_washout):
                yp, h = model(xb[:, s:e, None], h)
            h = h.detach()
            if not is_washout:
                loss = loss + esr_loss(yb[:, s:e], yp[..., 0])
        loss.backward(); clip_grad_norm_(model.parameters(), 1.0); opt.step()
"""

import csv
import os
from dataclasses import dataclass, field
from glob import glob

import numpy as np
import soundfile as sf

VALID_SPLITS = ("trainval", "test")


# ----------------------------------------------------------------------------
# CSV + file resolution
# ----------------------------------------------------------------------------

def read_alignment_csv(csv_path):
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def _path_parts_lower(path):
    return [p.lower() for p in os.path.normpath(os.path.abspath(path))
            .replace("\\", os.sep).split(os.sep) if p]


def _rel_parts_lower(path, root):
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
    return [p.lower() for p in os.path.normpath(rel)
            .replace("\\", os.sep).split(os.sep) if p and p != ".."]


def _in_split(path, split):
    """True if `path` lives under a folder named `split` (case-insensitive).
    ABSOLUTE-path check -- used only to recognize that the caller passed the
    split directory itself as root; per-file validation is done RELATIVE to
    the search root (see _validate_split), because an absolute check is
    fooled by an unrelated 'test'/'trainval' component in the project path."""
    return split.lower() in _path_parts_lower(path)


def _validate_split(path, root, split):
    """Raise unless `path` verifiably belongs to `split`, judged by the path
    RELATIVE to `root`:
      * split component present in the relative path -> OK
      * no split component in the relative path, but `root` itself lives
        under the split folder (caller passed the split dir as root) AND the
        relative path contains no OTHER split component -> OK
      * anything else -> SPLIT VIOLATION
    The 'no other split component' clause closes the loophole where a stray
    absolute component (e.g. a project folder literally named 'trainval')
    would validate files actually living under the opposite split."""
    rel = _rel_parts_lower(path, root)
    if split.lower() in rel:
        return
    if (_in_split(root, split)
            and not any(s in rel for s in VALID_SPLITS)):
        return
    raise ValueError(
        f"SPLIT VIOLATION: {os.path.basename(path)!r} resolved to {path!r}, "
        f"which is not under a {split!r} folder relative to {root!r}. This "
        f"row belongs to the other split; regenerate or filter the "
        f"alignment CSV.")


def _find_file(root, basename, split=None):
    """Resolve `basename` uniquely under `root`. If `split` is given, the
    search is constrained to the split subtree when it exists (this also
    disambiguates basenames that occur in both splits), and the resolved
    path is validated to actually live under that split."""
    search_root = root
    if split:
        sub = os.path.join(root, split)
        if os.path.isdir(sub):
            search_root = sub
        elif _in_split(root, split):
            pass                       # caller already passed the split dir
        # else: root doesn't contain the split folder directly; glob the whole
        # tree and rely on the validation below to catch violations.
    hits = [p for p in glob(os.path.join(search_root, "**", "*"),
                            recursive=True)
            if os.path.basename(p) == basename]
    if len(hits) != 1:
        where = f"{search_root!r}"
        hint = (f" (split={split!r} enforced -- is this file part of the "
                f"other split?)" if split else "")
        raise FileNotFoundError(
            f"{basename!r}: found {len(hits)} matches under {where}{hint}")
    path = hits[0]
    if split:
        _validate_split(path, root, split)
    return path


def setting_of(wet_basename):
    """Control-setting token of a wet filename (first dot-component)."""
    return wet_basename.split(".")[0].upper()


def source_of(clean_basename):
    """Source name of a dry filename (strip role tag/extension)."""
    name = os.path.splitext(clean_basename)[0]
    parts = [p for p in name.split(".") if p and p.lower() != "input"]
    return ".".join(parts)


# ----------------------------------------------------------------------------
# Pair loading (unshifted policy) + DC removal
# ----------------------------------------------------------------------------

def load_pair(row, clean_dir, wet_dir, dtype=np.float32, split=None):
    """One aligned, trimmed, DC-removed (dry, wet) pair from a CSV row.
    Both sides sliced at the CLEAN trim columns per the unshifted policy.
    Reads only the interior from disk. If `split` is given, both resolved
    paths are validated to live under that split folder."""
    lo, hi = int(row["trim_from_clean"]), int(row["trim_to_clean"])
    if lo < 0 or hi <= lo:
        raise ValueError(f"row {row['wet_file']!r} has no usable trim columns")
    cpath = _find_file(clean_dir, row["clean_file"], split=split)
    wpath = _find_file(wet_dir, row["wet_file"], split=split)

    def _read(path):
        x, sr = sf.read(path, start=lo, stop=hi, always_2d=False)
        if x.ndim > 1:
            x = x.mean(axis=1)
        x = x.astype(dtype)
        return x - x.mean(), sr                    # DC removal

    dry, sr_d = _read(cpath)
    wet, sr_w = _read(wpath)
    if sr_d != sr_w or len(dry) != len(wet):
        raise ValueError(f"pair {row['wet_file']!r}: sr/length mismatch")
    return dry, wet, sr_d


# ----------------------------------------------------------------------------
# Segmentation + TBPTT geometry
# ----------------------------------------------------------------------------

def seg_length(tbptt=1024, washout=1024, k=45):
    """Segment length = washout + k TBPTT chunks (~1 s for the defaults)."""
    return washout + k * tbptt


def segment_pair(dry, wet, seg_len):
    """Cut an aligned pair into non-overlapping [N, seg_len] segments
    (remainder dropped)."""
    n = len(dry) // seg_len
    if n == 0:
        return (np.empty((0, seg_len), dry.dtype),
                np.empty((0, seg_len), wet.dtype))
    return (dry[:n * seg_len].reshape(n, seg_len),
            wet[:n * seg_len].reshape(n, seg_len))


def iterate_tbptt(seg_len, tbptt=1024, washout=1024):
    """Yield (start, end, is_washout) covering a segment exactly once:
    one washout chunk (no grad, no loss), then TBPTT chunks (loss; caller
    detaches hidden between chunks)."""
    if washout:
        yield 0, washout, True
    pos = washout
    while pos < seg_len:
        end = min(pos + tbptt, seg_len)
        yield pos, end, False
        pos = end


# ----------------------------------------------------------------------------
# Cell assembly
# ----------------------------------------------------------------------------

@dataclass
class CellData:
    setting: str
    sr: int
    seg_len: int
    tbptt: int
    washout: int
    split: str = "trainval"
    train_x: np.ndarray = None      # [N, seg_len] dry
    train_y: np.ndarray = None      # [N, seg_len] wet
    val_x: np.ndarray = None
    val_y: np.ndarray = None
    sources: dict = field(default_factory=dict)   # source -> (n_train, n_val)


def load_cell(csv_path, clean_dir, wet_dir, setting,
              tbptt=1024, washout=1024, k=45, val_frac=0.1,
              include_fail=True, verbose=True, split="trainval"):
    """Assemble one cell (= one control setting) across all sources.

    split: which official ToneTwist split this cell may draw from
        ("trainval" default, "test" for final evaluation, None to disable
        the guard -- deliberate use only). Every resolved file path is
        validated; any CSV row resolving to the other split raises with the
        offending file named. A stale alignment CSV containing both splits
        therefore fails LOUDLY instead of silently leaking test material
        into training.

    include_fail: FAIL-verdict rows (prefix match, so annotated verdicts
    like 'FAIL~...' count) are included by default ONLY so diagnostic and
    evaluation tooling can report them per source (eval_diag's table needs
    the gtr2 row). The locked TRAINING protocol excludes them
    (include_fail=False / --exclude-fail). Do NOT trust an older note here
    claiming cross-correlation "cleared" the FAIL pairs -- it did not:
    gtr2 D050 is a confirmed +5-sample time-base splice (~236 s) imposing
    an ESR floor of ~-10 dB by itself (characterization + injection
    experiment). Frozen exclusion criterion: marker start/end disagreement
    beyond +/-2 jitter AND differential/dense-probe confirmation ->
    excluded from training; eval reports it as its own row.
    """
    if split is not None and split not in VALID_SPLITS:
        raise ValueError(f"split must be one of {VALID_SPLITS} or None, "
                         f"got {split!r}")
    rows = [r for r in read_alignment_csv(csv_path)
            if setting_of(r["wet_file"]) == setting.upper()]
    if not rows:
        raise ValueError(f"no CSV rows for setting {setting!r}")
    if not include_fail:
        rows = [r for r in rows
                if not r["verdict"].strip().upper().startswith("FAIL")]
        if not rows:
            raise ValueError(f"all rows for {setting!r} are FAIL-verdict; "
                             "nothing left to load")

    seg_len = seg_length(tbptt, washout, k)
    cell = CellData(setting=setting.upper(), sr=None,
                    seg_len=seg_len, tbptt=tbptt, washout=washout,
                    split=split if split else "ANY")
    tr_x, tr_y, va_x, va_y = [], [], [], []

    for row in sorted(rows, key=lambda r: r["clean_file"]):
        dry, wet, sr = load_pair(row, clean_dir, wet_dir, split=split)
        if cell.sr is None:
            cell.sr = sr
        elif sr != cell.sr:
            raise ValueError("mixed sample rates across sources")
        sx, sy = segment_pair(dry, wet, seg_len)
        n_val = max(1, int(round(len(sx) * val_frac))) if len(sx) > 1 else 0
        n_tr = len(sx) - n_val
        tr_x.append(sx[:n_tr]); tr_y.append(sy[:n_tr])
        va_x.append(sx[n_tr:]); va_y.append(sy[n_tr:])
        src = source_of(row["clean_file"])
        cell.sources[src] = (n_tr, n_val)
        if verbose:
            print(f"  {src:16s} {row['verdict']:16s} "
                  f"{len(dry)/sr:7.1f} s -> {n_tr} train + {n_val} val segs")

    cell.train_x = np.concatenate(tr_x); cell.train_y = np.concatenate(tr_y)
    cell.val_x = np.concatenate(va_x);   cell.val_y = np.concatenate(va_y)
    if verbose:
        tot = (cell.train_x.shape[0] + cell.val_x.shape[0]) * seg_len
        print(f"cell {cell.setting} [split={cell.split}]: "
              f"{cell.train_x.shape[0]} train / "
              f"{cell.val_x.shape[0]} val segments of {seg_len} samples "
              f"({tot / cell.sr / 60:.1f} min total)")
    return cell


# ----------------------------------------------------------------------------
# Self-test on synthetic data (run: python3 gru_data.py <csv> <clean> <wet>)
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) not in (5, 6):
        sys.exit("usage: gru_data.py <alignment_csv> <clean_dir> <wet_dir> "
                 "<setting> [split]")
    split_arg = sys.argv[5] if len(sys.argv) == 6 else "trainval"
    if split_arg.lower() == "none":
        split_arg = None
    cell = load_cell(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4],
                     k=45, split=split_arg)

    # coverage check: TBPTT chunks tile the segment exactly once
    covered = np.zeros(cell.seg_len, bool)
    n_loss = 0
    for s, e, wo in iterate_tbptt(cell.seg_len, cell.tbptt, cell.washout):
        assert not covered[s:e].any(), "overlapping chunks"
        covered[s:e] = True
        n_loss += 0 if wo else (e - s)
    assert covered.all(), "gap in chunk coverage"
    print(f"TBPTT coverage OK: washout {cell.washout} + "
          f"{n_loss} loss samples = {cell.seg_len}")

    # alignment sanity: dry/wet correlation at lag 0 on the LOUDEST training
    # segment (segment 0 is often leading silence -> zero variance -> NaN)
    idx = int(np.argmax(cell.train_x.var(axis=1)))
    x, y = cell.train_x[idx], cell.train_y[idx]
    c = float(np.corrcoef(x, y)[0, 1])
    print(f"segment {idx} (loudest) dry/wet correlation at lag 0: {c:+.3f} "
          f"(strongly nonzero = aligned)")
    print(f"DC check: dry mean {cell.train_x.mean():+.2e}, "
          f"wet mean {cell.train_y.mean():+.2e}")
