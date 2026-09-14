// SENTINEL: TBFM2-REV2-2026-08-10
// gru_va_tb_fm2.cpp - C-simulation testbench, dual mode, cross-platform.
//
// Lineage: golden-mode scoring block copied VERBATIM from gru_va_tanh_0_tb.cpp
// (the TB the ratified 102 grid compiled, hash FC6A9002...); file-mode
// interface reproduces the 7/19-certified transport (chunked streaming,
// h_state persists across kernel calls, reset on chunk 0 only = DMA-block
// deployment semantics). Differences vs the 8/3 TB, all deliberate:
//   1. Paths come from argv (no hardcoded C:/ paths) -> runs on Lenny + Elle.
//   2. Under USE_COMPILED_WEIGHTS, weights_flat.bin is NOT required
//      (loader is a no-op; a dummy buffer satisfies the preload call).
//      Without the define, weights load from <dir>/weights_flat.bin as before.
//   3. Golden mode can optionally WRITE the kernel output to a file
//      (enables the byte-level golden-reproduction leg of the fmcheck gate).
//   4. File mode is transport-only (no scoring, returns 0 on I/O success):
//      metrics come from hls_metrics.py per the one-implementation rule.
//      Golden mode keeps the cosine>=0.999 PASS/FAIL exactly as before.
//
// Usage (csim_design -argv "..."):
//   (no argv)                          golden mode, dir = "testdata" (cwd-relative)
//   golden <testdata_dir> [out.f32]    golden mode, explicit dir, optional output dump
//   file <in.f32> <out.f32> [chunk]    file mode, default chunk 65536
//
// SENTINEL: TBFM2-REV2-2026-08-10

#include "gru_va.h"
#include "gru_weights.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <string>
#include <vector>

static std::vector<float> read_f32(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f)
    {
        printf("FATAL: cannot open %s\n", path);
        exit(1);
    }
    fseek(f, 0, SEEK_END);
    long n = ftell(f) / sizeof(float);
    fseek(f, 0, SEEK_SET);
    std::vector<float> v(n);
    fread(v.data(), sizeof(float), n, f);
    fclose(f);
    return v;
}

// Preload weights once. Compiled-weights build: loader is a no-op, dummy
// buffer only satisfies the signature. m_axi build: real load from file.
static std::vector<float> preload_weights(const std::string &dir)
{
#ifdef USE_COMPILED_WEIGHTS
    (void)dir;
    std::vector<float> w(N_WEIGHTS, 0.0f); // never read by the kernel
    printf("Weights: compiled-in ROM (weights.h); dummy preload buffer\n");
#else
    std::string wp = dir + "/weights_flat.bin";
    std::vector<float> w = read_f32(wp.c_str());
    if ((int)w.size() != N_WEIGHTS)
    {
        printf("FATAL: %s has %zu floats, expected %d\n", wp.c_str(), w.size(), N_WEIGHTS);
        exit(1);
    }
#endif
    hls::stream<axis_sample> s_in, s_out;
    gru_va(s_in, s_out, w.data(), /*mode=*/0, /*n_samples=*/0, /*reset=*/0);
    printf("Preload done\n");
    return w;
}

// Stream one block through the kernel. reset=1 zeroes h_state first;
// reset=0 carries state from the previous call (chunk semantics).
static void run_block(const float *x, float *y, int n, const float *w, int reset)
{
    hls::stream<axis_sample> s_in, s_out;
    for (int i = 0; i < n; i++)
    {
        axis_sample pkt;
        union { unsigned int u; float f; } c;
        c.f = x[i];
        pkt.data = c.u;
        pkt.keep = -1;
        pkt.strb = -1;
        pkt.last = (i == n - 1) ? 1 : 0;
        s_in.write(pkt);
    }
    gru_va(s_in, s_out, const_cast<float *>(w), /*mode=*/1, n, reset);
    for (int i = 0; i < n; i++)
    {
        axis_sample pkt = s_out.read();
        union { unsigned int u; float f; } c;
        c.u = pkt.data;
        y[i] = c.f;
    }
    if (!s_out.empty())
    {
        printf("FATAL: extra samples in output stream\n");
        exit(1);
    }
}

// ---------------- golden mode ----------------
static int run_golden(const std::string &dir, const char *dump_path)
{
    std::vector<float> weights = preload_weights(dir);
    std::vector<float> x = read_f32((dir + "/golden_input.bin").c_str());
    std::vector<float> golden = read_f32((dir + "/golden_output.bin").c_str());

    if (x.size() != golden.size())
    {
        printf("FATAL: input/golden length mismatch (%zu vs %zu)\n", x.size(), golden.size());
        return 1;
    }
    const int N = (int)x.size();
    printf("Loaded: %d weights, %d samples\n", N_WEIGHTS, N);

    std::vector<float> y(N);
    run_block(x.data(), y.data(), N, weights.data(), /*reset=*/1);

    if (dump_path)
    {
        FILE *f = fopen(dump_path, "wb");
        if (!f)
        {
            printf("FATAL: cannot open %s for write\n", dump_path);
            return 1;
        }
        fwrite(y.data(), sizeof(float), N, f);
        fclose(f);
        printf("Golden-mode output dumped: %s (%d samples)\n", dump_path, N);
    }

    // ---- scoring block: VERBATIM from gru_va_tanh_0_tb.cpp (FC6A9002) ----
    const int SKIP = 0;
    double dot = 0, na = 0, nb = 0, max_err = 0, sum_sq_err = 0, sum_sq_ref = 0, sum_err = 0.0, sum_abs_err = 0.0;
    int max_err_idx = -1;

    for (int n = SKIP; n < N; n++)
    {
        double a = golden[n], b = y[n];
        dot += a * b;
        na += a * a;
        nb += b * b;
        double e = fabs(a - b);
        sum_err += (b - a);
        sum_abs_err += e;
        sum_sq_err += (a - b) * (a - b);
        sum_sq_ref += a * a;
        if (e > max_err)
        {
            max_err = e;
            max_err_idx = n;
        }
    }

    const int scored = N - SKIP;
    double cosine = dot / (sqrt(na) * sqrt(nb) + 1e-30);
    double esr_db = 10.0 * log10(sum_sq_err / (sum_sq_ref + 1e-30) + 1e-30);
    double mse = sum_sq_err / scored;
    double rmse = std::sqrt(mse);
    double ref_rms = std::sqrt(sum_sq_ref / scored);
    double nrmse = rmse / (ref_rms + 1e-30);
    double mean_err = sum_err / scored;

    printf("FORMAT: DT_W=ap_fixed<%d,%d> DT_ACT=ap_fixed<%d,%d> ACC=ap_fixed<32,12>\n",
           DTW_W, DTW_I, DTACT_W, DTACT_I);
    printf("---- C-sim vs PyTorch FP32 golden ----\n");
    printf("cosine similarity : %.6f\n", cosine);
    printf("ESR vs golden     : %.2f dB\n", esr_db);
    printf("max abs error     : %.6e at sample %d\n", max_err, max_err_idx);
    printf("RMSE              : %.6e\n", rmse);
    printf("normalized RMSE   : %.6e\n", nrmse);
    printf("mean error        : %.6e\n", mean_err);

    printf("first 5 pairs (golden, hls): ");
    for (int n = SKIP; n < SKIP + 5; n++)
        printf("(%.5f, %.5f) ", golden[n], y[n]);
    printf("\n");

    const double COSINE_MIN = 0.999;
    if (cosine < COSINE_MIN)
    {
        printf("FAIL: cosine %.6f < %.3f\n", cosine, COSINE_MIN);
        return 1;
    }
    printf("PASS\n");
    return 0;
    // ---- end verbatim scoring block ----
}

// ---------------- file mode (transport only) ----------------
static int run_file(const char *in_path, const char *out_path, int chunk)
{
    std::vector<float> weights = preload_weights("testdata");
    std::vector<float> x = read_f32(in_path);
    const long N = (long)x.size();
    printf("File mode: %ld samples, chunk %d\n", N, chunk);

    FILE *fo = fopen(out_path, "wb");
    if (!fo)
    {
        printf("FATAL: cannot open %s for write\n", out_path);
        return 1;
    }

    std::vector<float> y(chunk);
    long done = 0;
    int ci = 0;
    while (done < N)
    {
        int len = (int)((N - done < (long)chunk) ? (N - done) : chunk);
        run_block(x.data() + done, y.data(), len, weights.data(),
                  /*reset=*/(ci == 0) ? 1 : 0);
        fwrite(y.data(), sizeof(float), len, fo); // per-chunk write = liveness
        fflush(fo);
        done += len;
        ci++;
    }
    fclose(fo);
    printf("FORMAT: DT_W=ap_fixed<%d,%d> DT_ACT=ap_fixed<%d,%d> ACC=ap_fixed<32,12>\n",
           DTW_W, DTW_I, DTACT_W, DTACT_I);
    printf("File mode complete: %ld samples, %d chunks -> %s\n", N, ci, out_path);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc >= 2 && strcmp(argv[1], "file") == 0)
    {
        if (argc < 4)
        {
            printf("usage: file <in.f32> <out.f32> [chunk]\n");
            return 1;
        }
        int chunk = (argc >= 5) ? atoi(argv[4]) : 65536;
        if (chunk <= 0)
        {
            printf("FATAL: bad chunk %d\n", chunk);
            return 1;
        }
        return run_file(argv[2], argv[3], chunk);
    }
    if (argc >= 2 && strcmp(argv[1], "golden") == 0)
    {
        std::string dir = (argc >= 3) ? argv[2] : "testdata";
        const char *dump = (argc >= 4) ? argv[3] : nullptr;
        return run_golden(dir, dump);
    }
    // no argv: golden mode, cwd-relative testdata (mirrors deployment layout)
    return run_golden("testdata", nullptr);
}
// SENTINEL-END: TBFM2-REV2-2026-08-10
