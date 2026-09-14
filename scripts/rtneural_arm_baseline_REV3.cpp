// SENTINEL: RTNARM-REV3-2026-08-16
// REV2 (external review 2026-08-16, evaluated per protocol):
//   - ESR wiring tripwire added: hard FAIL (rc=2) above -40 dB. This catches
//     gate-order mis-wiring (lands near 0 dB), NOT pre-reg adjudication --
//     the pre-registered band [-140,-90] dB is adjudicated manually per
//     workflow. -40 dB sits decades from both legit results and mis-wires.
//   - n <= SLICE off-by-one fixed (n == SLICE suffices for pass 1)
//   - finite-check extended to input and reference
//   - den > 0 checked before log10
//   - fwrite return value checked
// REV3 (external review round 2, pre-launch): tripwire condition
//   isfinite -> isnan. ESR = -inf (num==0, exact reproduction) is the best
//   possible result and must PASS; NaN is unreachable after the den>0 gate
//   but kept as a belt. -inf > -40 is false, so the threshold clause alone
//   carries the wiring check.
// C9 ARM baseline: RTNeural float32 GRU(1->40)->Dense(40->1) on PYNQ-Z2
// Cortex-A9, rodent_max anchor cell, nam full-length input.
//
// Weight source: the CERTIFIED flat export weights_flat.bin
//   (5201 float32 = 20804 bytes, MD5 18ca916778ffaca0b0c2d937d3e6f04f),
//   PyTorch canonical order:
//     [0..119]      gru.weight_ih_l0  (120x1, gate blocks r,z,n)
//     [120..4919]   gru.weight_hh_l0  (120x40 row-major)
//     [4920..5039]  gru.bias_ih_l0
//     [5040..5159]  gru.bias_hh_l0
//     [5160..5199]  head.weight       (1x40)
//     [5200]        head.bias
// Gate reorder happens HERE (single point of truth):
//   PyTorch blocks r=0,z=1,n=2  ->  RTNeural/TF blocks z,r,c
//   Both use reset_after semantics: n/c = tanh(Wx+b_i + r*(Uh+b_h)).
//
// Passes:
//   1) timed 262144-sample slice (apples-to-apples w/ A9 Python row)
//   2) timed full file, fresh state; ESR-vs-ref gate (skip 1024) in double
//
// Usage:
//   rtneural_arm_baseline <weights_flat.bin> <in.f32> <ref.f32> [out.f32]
//
// Build (on board, Eigen backend):
//   g++ -O3 -std=c++17 -mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard \
//       -DRTNEURAL_USE_EIGEN=1 -I<rtneural_src> -I<rtneural_src>/modules/Eigen \
//       -o rtneural_arm_baseline rtneural_arm_baseline.cpp
//   (STL-backend fallback: drop -DRTNEURAL_USE_EIGEN=1 and the Eigen -I)

#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <RTNeural/RTNeural.h>

static const char* SENTINEL = "RTNARM-REV3-2026-08-16";
static const int H = 40;
static const long SKIP = 1024;
static const long SLICE = 262144;
static const long EXPECT_W_FLOATS = 5201;

static std::vector<float> read_f32(const char* path, long expect_floats /*-1 = any*/)
{
    FILE* f = std::fopen(path, "rb");
    if (!f) { std::fprintf(stderr, "FATAL: cannot open %s\n", path); std::exit(1); }
    std::fseek(f, 0, SEEK_END);
    long bytes = std::ftell(f);
    std::fseek(f, 0, SEEK_SET);
    if (bytes % 4 != 0) { std::fprintf(stderr, "FATAL: %s size %ld not multiple of 4\n", path, bytes); std::exit(1); }
    long n = bytes / 4;
    if (expect_floats >= 0 && n != expect_floats) {
        std::fprintf(stderr, "FATAL: %s has %ld floats, expected %ld\n", path, n, expect_floats);
        std::exit(1);
    }
    std::vector<float> v((size_t)n);
    if (std::fread(v.data(), 4, (size_t)n, f) != (size_t)n) {
        std::fprintf(stderr, "FATAL: short read on %s\n", path); std::exit(1);
    }
    std::fclose(f);
    return v;
}

int main(int argc, char** argv)
{
    std::printf("== %s ==\n", SENTINEL);
    if (argc < 4) {
        std::fprintf(stderr, "usage: %s <weights_flat.bin> <in.f32> <ref.f32> [out.f32]\n", argv[0]);
        return 1;
    }

    // ---- load + finite-check weights ----
    std::vector<float> flat = read_f32(argv[1], EXPECT_W_FLOATS);
    for (long i = 0; i < EXPECT_W_FLOATS; ++i)
        if (!std::isfinite(flat[(size_t)i])) { std::fprintf(stderr, "FATAL: nonfinite weight at %ld\n", i); return 1; }

    const float* W_ih = flat.data();          // [120] (in=1)
    const float* W_hh = flat.data() + 120;    // [120][40] row-major
    const float* b_ih = flat.data() + 4920;   // [120]
    const float* b_hh = flat.data() + 5040;   // [120]
    const float* hw   = flat.data() + 5160;   // [40]
    const float  hb   = flat[5200];

    // ---- gate reorder: RTNeural block g in {z=0,r=1,c=2} <- PyTorch block py_of_rt[g]
    const int py_of_rt[3] = {1, 0, 2};        // z<-py z(1), r<-py r(0), c<-py n(2)

    std::vector<std::vector<float>> wVals(1, std::vector<float>(3 * H));
    std::vector<std::vector<float>> uVals((size_t)H, std::vector<float>(3 * H));
    std::vector<std::vector<float>> bVals(2, std::vector<float>(3 * H));
    for (int g = 0; g < 3; ++g) {
        const int pb = py_of_rt[g];
        for (int i = 0; i < H; ++i) {
            const int rt = g * H + i;         // RTNeural gate-major index
            const int py = pb * H + i;        // PyTorch row index
            wVals[0][(size_t)rt] = W_ih[py];
            for (int k = 0; k < H; ++k)
                uVals[(size_t)k][(size_t)rt] = W_hh[(size_t)py * H + k]; // transpose
            bVals[0][(size_t)rt] = b_ih[py];
            bVals[1][(size_t)rt] = b_hh[py];
        }
    }
    std::vector<std::vector<float>> dw(1, std::vector<float>((size_t)H));
    for (int i = 0; i < H; ++i) dw[0][(size_t)i] = hw[i];
    float db[1] = { hb };

    RTNeural::ModelT<float, 1, 1,
        RTNeural::GRULayerT<float, 1, H>,
        RTNeural::DenseT<float, H, 1>> model;
    model.get<0>().setWVals(wVals);
    model.get<0>().setUVals(uVals);
    model.get<0>().setBVals(bVals);
    model.get<1>().setWeights(dw);
    model.get<1>().setBias(db);

    // ---- load input + ref ----
    std::vector<float> x   = read_f32(argv[2], -1);
    std::vector<float> ref = read_f32(argv[3], -1);
    for (size_t i = 0; i < x.size(); ++i)
        if (!std::isfinite(x[i])) { std::fprintf(stderr, "FATAL: nonfinite input sample at %zu\n", i); return 1; }
    for (size_t i = 0; i < ref.size(); ++i)
        if (!std::isfinite(ref[i])) { std::fprintf(stderr, "FATAL: nonfinite ref sample at %zu\n", i); return 1; }
    const long n = (long)x.size();
    std::printf("input:  %ld samples (%ld bytes)\n", n, n * 4);
    if ((long)ref.size() != n) {
        std::fprintf(stderr, "FATAL: ref has %ld samples, input has %ld\n", (long)ref.size(), n);
        return 1;
    }
    if (n < SLICE) { std::fprintf(stderr, "FATAL: input shorter than slice %ld\n", SLICE); return 1; }

    std::vector<float> y((size_t)n);

    // ---- pass 1: timed slice, fresh state ----
    model.reset();
    auto t0 = std::chrono::steady_clock::now();
    for (long i = 0; i < SLICE; ++i)
        y[(size_t)i] = model.forward(&x[(size_t)i]);
    auto t1 = std::chrono::steady_clock::now();
    double s1 = std::chrono::duration<double>(t1 - t0).count();
    std::printf("PASS1 slice  : %ld samples in %.3f s -> %.1f samples/s, %.3f us/sample, %.3fx RT@48k\n",
                SLICE, s1, SLICE / s1, 1e6 * s1 / SLICE, (SLICE / s1) / 48000.0);

    // ---- pass 2: timed full file, fresh state ----
    model.reset();
    auto t2 = std::chrono::steady_clock::now();
    for (long i = 0; i < n; ++i)
        y[(size_t)i] = model.forward(&x[(size_t)i]);
    auto t3 = std::chrono::steady_clock::now();
    double s2 = std::chrono::duration<double>(t3 - t2).count();
    std::printf("PASS2 full   : %ld samples in %.3f s -> %.1f samples/s, %.3f us/sample, %.3fx RT@48k\n",
                n, s2, n / s2, 1e6 * s2 / n, (n / s2) / 48000.0);

    // ---- correctness gate: ESR vs float ref, skip washout, double accum ----
    double num = 0.0, den = 0.0;
    long nonfinite = 0;
    for (long i = SKIP; i < n; ++i) {
        const double d = (double)y[(size_t)i] - (double)ref[(size_t)i];
        if (!std::isfinite((double)y[(size_t)i])) ++nonfinite;
        num += d * d;
        den += (double)ref[(size_t)i] * (double)ref[(size_t)i];
    }
    if (nonfinite > 0) { std::fprintf(stderr, "FATAL: %ld nonfinite output samples\n", nonfinite); return 1; }
    if (!(den > 0.0)) { std::fprintf(stderr, "FATAL: zero-energy reference (den=%g)\n", den); return 1; }
    const double esr_db = 10.0 * std::log10(num / den);
    std::printf("ESR-vs-ref (skip %ld): %.2f dB  [pre-reg band adjudicated manually]\n", SKIP, esr_db);
    static const double WIRING_TRIPWIRE_DB = -40.0;
    if (std::isnan(esr_db) || esr_db > WIRING_TRIPWIRE_DB) {
        std::fprintf(stderr, "FAIL WIRING TRIPWIRE: ESR %.2f dB > %.1f dB (gate-order/layout suspect)\n",
                     esr_db, WIRING_TRIPWIRE_DB);
        return 2;
    }

    if (argc >= 5) {
        FILE* f = std::fopen(argv[4], "wb");
        if (!f) { std::fprintf(stderr, "FATAL: cannot write %s\n", argv[4]); return 1; }
        const size_t wr = std::fwrite(y.data(), 4, (size_t)n, f);
        std::fclose(f);
        if (wr != (size_t)n) { std::fprintf(stderr, "FATAL: short write %zu/%ld to %s\n", wr, n, argv[4]); return 1; }
        std::printf("output written: %s (%ld bytes)\n", argv[4], n * 4);
    }
    std::printf("== %s COMPLETE ==\n", SENTINEL);
    return 0;
}
