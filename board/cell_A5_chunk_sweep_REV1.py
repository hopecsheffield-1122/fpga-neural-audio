# A5. Chunk-size sweep of the hardware window  (CHUNKSWEEP-REV1-2026-09-11)
# Run AFTER cells 1, 2 (config + helpers + stimulus) and A1 (load_bitstream).
# Same bracket as run_throughput; only the chunk size changes. Total samples per point are
# held constant (200 x 65536 = 13,107,200), so every point has the same statistical weight.
# Any fixed per-rep artifact (DMA/stream FIFO lead ending the window early, or the wait()
# poll tail ending it late) shows up as a slope in cyc_hw vs 1/chunk. The intercept at
# 1/chunk -> 0 is the kernel cycles/sample with that artifact removed.
import numpy as np, time
from pynq import allocate

TOTAL = 200 * 65536
SWEEP = [(4096, TOTAL // 4096), (16384, TOTAL // 16384), (65536, TOTAL // 65536)]

def run_throughput_chunk(ip, dma, nam_x, chunk, reps):
    ibc = allocate(shape=(chunk,), dtype=np.float32)
    obc = allocate(shape=(chunk,), dtype=np.float32)
    try:
        rm = ip.register_map
        ibc[:] = nam_x[:chunk]; ibc.flush()
        rm.mode = 1; rm.n_samples = chunk; rm.reset_state = 1
        dma.recvchannel.transfer(obc); start_kernel(ip); dma.sendchannel.transfer(ibc)
        dma.sendchannel.wait(); dma.recvchannel.wait(); wait_done(ip)
        rm.reset_state = 0
        hw = 0.0
        t0 = time.time()
        for _ in range(reps):
            dma.recvchannel.transfer(obc)
            start_kernel(ip)
            dma.sendchannel.transfer(ibc)
            ta = time.perf_counter()
            dma.sendchannel.wait()
            hw += time.perf_counter() - ta
            dma.recvchannel.wait()
            wait_done(ip)
        dt = time.time() - t0
    finally:
        ibc.freebuffer(); obc.freebuffer()
    n = reps * chunk
    return {"chunk": chunk, "reps": reps,
            "cyc_hw": 1e6 * hw / n * FCLK_MHZ,
            "cyc_total": 1e6 * dt / n * FCLK_MHZ}

print("CHUNKSWEEP-REV1  bit:", BIT, " fclk0:", Clocks.fclk0_mhz, "MHz")
rows = []
for chunk, reps in SWEEP:
    r = run_throughput_chunk(ip, dma, nam_x, chunk, reps)
    rows.append(r)
    print("chunk %6d  reps %5d  cyc_hw %8.3f  cyc_total %8.3f" % (chunk, reps, r["cyc_hw"], r["cyc_total"]))

inv = np.array([1.0 / r["chunk"] for r in rows])
y_hw = np.array([r["cyc_hw"] for r in rows])
y_tot = np.array([r["cyc_total"] for r in rows])
m_hw, b_hw = np.polyfit(inv, y_hw, 1)
m_tot, b_tot = np.polyfit(inv, y_tot, 1)
print("fit cyc_hw    = %.3f + %.1f/chunk   (intercept = kernel cyc/sample; slope in cycle-samples)" % (b_hw, m_hw))
print("fit cyc_total = %.3f + %.1f/chunk" % (b_tot, m_tot))
print("per-rep fixed effect in the hw window: %.1f cycles = %.1f us = %.0f samples-equivalent"
      % (m_hw, m_hw / FCLK_MHZ, m_hw / b_hw))
print("CHUNKSWEEP-REV1 done")
