// gru_va_col_fused_mac3.cpp — single-layer GRU inference kernel (Vitis HLS 2025.2)
//
// Computes one hidden-state update per input sample in the PyTorch GRU form
// (reset gate applied after the recurrent product; z gates the old state),
// then the affine output y = w_out . h + b_out. One audio sample in, one out,
// over AXI-Stream; weights are compiled in as constants (gru_weights.h, generated
// per model by make_weights_header.py from weights_flat.bin).
//
// Fixed-point types are declared in gru_va.h: DT_W for weights/biases/output
// layer, DT_ACT for input/state/activations, DT_ACC <32,12> for accumulators
// and gate arithmetic; convergent rounding and saturation throughout.
// tanh is a 1025-entry table over [0,8) with linear interpolation (tanh_table.h);
// sigmoid uses sigma(v) = 0.5*(tanh(v/2)+1).
//
// Parallelism: the three recurrent dot products for hidden unit i are split
// across P_COLS columns, each with its own accumulator, then reduced. The
// column MAC is outlined into mac3() so its instance count can be capped with
// an ALLOCATION pragma (-DALLOC_MAC3_LIMIT). All reported builds used
// -DP_COLS=40 -DALLOC_MAC3_LIMIT=20 ("L20"); with ALLOC_MAC3_LIMIT undefined,
// mac3 inlines and the numerics are unchanged.
//
// Weight loading (mode == 0) lives in gru_load.cpp.

#include "gru_va.h"
#include "tanh_table.h"
#include "gru_weights.h"
#include <hls_math.h>

// Columns processed per cycle. The default (40 = H) matches every reported
// build; the build scripts also pass it explicitly (-DP_COLS=N).
#ifndef P_COLS
#define P_COLS 40
#endif
#define P P_COLS

// Instance cap for mac3() from cflags (-DALLOC_MAC3_LIMIT=N). The ALLOCATION
// pragma is emitted inside the HIDDEN_LOOP body so that it stays with the
// loop when Vitis extracts it into its own function. With the limit
// undefined, mac3 is inlined; the numerics are the same either way.
#ifdef ALLOC_MAC3_LIMIT
#define DO_PRAGMA_(x) _Pragma(#x)
#define EXPAND_PRAGMA_(x) DO_PRAGMA_(x)
#define MAC3_ALLOC_PRAGMA EXPAND_PRAGMA_(HLS ALLOCATION function instances = mac3 limit = ALLOC_MAC3_LIMIT)
#else
#define MAC3_ALLOC_PRAGMA
#endif

// One column's contribution to the three gate accumulators: three
// multiply-adds in fixed order with explicit widening casts.
static void mac3(DT_ACC &ar, DT_ACC &az, DT_ACC &an,
                 DT_W wr, DT_W wz, DT_W wn, DT_ACT h)
{
#ifdef ALLOC_MAC3_LIMIT
#pragma HLS INLINE OFF
#else
#pragma HLS INLINE
#endif
    ar += (DT_ACC)(wr * h);
    az += (DT_ACC)(wz * h);
    an += (DT_ACC)(wn * h);
}
static_assert(H % P == 0, "H must be divisible by P");

// Hard-activation variants. Not used in any reported build (the deployed
// path is tanh_fx / sigmoid_fx below); retained for the training-side
// hard-activation experiment.
//
// Hardsigmoid:
//   1        for v > 2
//   v/4+1/2  for -2 <= v <= 2
//   0        for v < -2
static DT_ACT hardsigmoid_fx(DT_ACC v)
{
#pragma HLS INLINE
    if (v > (DT_ACC)2)
        return (DT_ACT)1;
    else if (v < (DT_ACC)-2)
        return (DT_ACT)0;
    else
        return (DT_ACT)((v * (DT_ACC)0.25) + (DT_ACC)0.5);
}

// Hardtanh:
//   1   for v > 1
//   v   for -1 <= v <= 1
//  -1   for v < -1
static DT_ACT hardtanh_fx(DT_ACC v)
{
#pragma HLS INLINE
    if (v > (DT_ACC)1)
        return (DT_ACT)1;
    else if (v < (DT_ACC)-1)
        return (DT_ACT)-1;
    else
        return (DT_ACT)v;
}

// tanh via 1025-entry table over [0,8], step 1/128. Odd symmetry on |v|.
// Saturation test done in the WIDE type (DT_ACC) before any narrowing, so
// large pre-activations clamp to 1 instead of wrapping. Widening casts
// applied BEFORE scaling, since ap_fixed operations keep the operand type.
static_assert(DT_ACC::width - DT_ACC::iwidth == 20,
              "tanh_fx literals (ap_ufixed<23,3>/<30,10>/<20,0>) assume DT_ACC has exactly 20 frac bits — re-derive before changing ACC");

static DT_ACT tanh_fx(DT_ACC v)
{
#pragma HLS INLINE
    bool neg = (v < 0);
    DT_ACC av = neg ? (DT_ACC)(-v) : v; // |v|, wide (AP_SAT safe)

    DT_ACT mag;
    if (av >= (DT_ACC)8)
    {
        mag = (DT_ACT)TANH_TABLE[1024]; // tanh(>=8) ~ 1  (err 2.3e-7)
    }
    else
    {
        // av proven < 8: narrow losslessly, keep 20 frac bits (all of
        // DT_ACC's fraction at <32,12>)
        ap_ufixed<23, 3> a = av; // [0,8), 20 frac bits
        // widen FIRST, then scale: value*128 in [0,1024), 20 frac kept (exact)
        ap_ufixed<30, 10> scaled = (ap_ufixed<30, 10>)a * (ap_ufixed<30, 10>)128; // exact: *128 keeps all 20 frac bits
        ap_uint<10> idx = scaled;                                                 // integer part, 0..1023
        ap_ufixed<20, 0> frac =
            scaled - (ap_ufixed<30, 10>)idx; // [0,1)

        DT_ACT t0 = TANH_TABLE[idx];
        DT_ACT t1 = TANH_TABLE[idx + 1];
        DT_ACC y = (DT_ACC)t0 + (DT_ACC)frac * ((DT_ACC)t1 - (DT_ACC)t0);
        mag = (DT_ACT)y;
    }
    return neg ? (DT_ACT)(-mag) : mag;
}

// sigmoid via sigma(v) = 0.5 * (tanh(v/2) + 1); both halvings are
// multiplies by 0.5 rather than shifts, so rounding follows the ap_fixed mode.
static DT_ACT sigmoid_fx(DT_ACC v)
{
#pragma HLS INLINE
    DT_ACC half_v = v * (DT_ACC)0.5;
    DT_ACC t = (DT_ACC)tanh_fx(half_v);
    return (DT_ACT)((t + (DT_ACC)1) * (DT_ACC)0.5);
}

// gru
void gru_va(hls::stream<axis_sample> &audio_in,
            hls::stream<axis_sample> &audio_out,
            const float *weights,
            const int mode,
            const int n_samples,
            const int reset_state)
{
// AXI IF
#pragma HLS INTERFACE axis port = audio_in
#pragma HLS INTERFACE axis port = audio_out
#pragma HLS INTERFACE m_axi port = weights depth = N_WEIGHTS offset = slave bundle = gmem0
#pragma HLS INTERFACE s_axilite port = weights bundle = CTRL
#pragma HLS INTERFACE s_axilite port = mode bundle = CTRL
#pragma HLS INTERFACE s_axilite port = n_samples bundle = CTRL
#pragma HLS INTERFACE s_axilite port = reset_state bundle = CTRL
#pragma HLS INTERFACE s_axilite port = return bundle = CTRL

// Partitioning for update weights for r, z, n and array partition for h_state
#pragma HLS ARRAY_PARTITION variable = U_r type = cyclic factor = P dim = 2
#pragma HLS ARRAY_PARTITION variable = U_z type = cyclic factor = P dim = 2
#pragma HLS ARRAY_PARTITION variable = U_n type = cyclic factor = P dim = 2
#pragma HLS ARRAY_PARTITION variable = h_state type = complete

    // see gru_load.cpp
    if (mode == 0)
    {
        gru_load_weights(weights);
        return;
    }

    // initial  reset of GRU
    if (reset_state)
    {
    RESET:
        for (int i = 0; i < H; i++)
        {
#pragma HLS UNROLL
            h_state[i] = 0;
        }
    }

SAMPLE_LOOP:
    for (int n = 0; n < n_samples; n++)
    {
        axis_sample in_pkt = audio_in.read();
        union
        {
            unsigned int u;
            float f;
        } conv_in;                    // union lets the same 32 bits be viewed as either uint or float
        conv_in.u = in_pkt.data;      // assigns data payload from incoming packet into a converter struct in a shared mem buffer
        DT_ACT x = (DT_ACT)conv_in.f; //.f reads the incoming bits as the float they encode. Cast based on DT_ACT

        DT_ACT h_new[H];
#pragma HLS ARRAY_PARTITION variable = h_new type = complete
        DT_ACC y_acc = 0; // output accumulation, carried across HIDDEN_LOOP

    HIDDEN_LOOP:
        for (int i = 0; i < H; i++)
        {
            // mac3 instance cap; must be in the scope containing the calls.
            MAC3_ALLOC_PRAGMA

            DT_ACC acc_r[P] = {};
            DT_ACC acc_z[P] = {};
            DT_ACC acc_n[P] = {};

#pragma HLS ARRAY_PARTITION variable = acc_r complete
#pragma HLS ARRAY_PARTITION variable = acc_z complete
#pragma HLS ARRAY_PARTITION variable = acc_n complete

        // Compute the recurrent matrix-vector products:
        // acc_r -> U_r[i] dot h_state
        // acc_z -> U_z[i] dot h_state
        // acc_n -> U_n[i] dot h_state
        MATVEC_BLOCK:
            for (int jb = 0; jb < H; jb += P)
            {
#pragma HLS PIPELINE II = 1

            MATVEC_COL:
                for (int col = 0; col < P; col++)
                {
#pragma HLS UNROLL
                    const int j = jb + col;

                    mac3(acc_r[col], acc_z[col], acc_n[col],
                         U_r[i][j], U_z[i][j], U_n[i][j],
                         h_state[j]);
                }
            }

            // Input-side portions of the three gate equations
            DT_ACC val_r = (DT_ACC)(b_ir[i] + b_hr[i] + W_r[i] * x);

            DT_ACC val_z = (DT_ACC)(b_iz[i] + b_hz[i] + W_z[i] * x);

            // Candidate input term is not reset-gated.
            DT_ACC val_n_in = (DT_ACC)(b_in[i] + W_n[i] * x);

            // Candidate recurrent term is reset-gated after the matvec
            DT_ACC val_n_rec = (DT_ACC)b_hn[i];

        // Combine the P column accumulators.
        REDUCE:
            for (int col = 0; col < P; col++)
            {
#pragma HLS UNROLL
                val_r += acc_r[col];
                val_z += acc_z[col];
                val_n_rec += acc_n[col];
            }

            // Reset and update gates.
            DT_ACT r = sigmoid_fx(val_r);
            DT_ACT z = sigmoid_fx(val_z);

            // DT_ACT r = hardsigmoid_fx(val_r);
            // DT_ACT z = hardsigmoid_fx(val_z);

            // PyTorch reset-after-matmul candidate:
            // n = tanh(W_n*x + b_in + r*(U_n*h + b_hn))
            DT_ACC candidate_pre = (DT_ACC)(val_n_in + (r * val_n_rec));

            DT_ACT nn = tanh_fx(candidate_pre);
            // DT_ACT nn = hardtanh_fx(candidate_pre);   // was tanh_fx

            // PyTorch hidden-state update:
            // h_new = (1-z)*n + z*h_old
            //
            // Algebraically equivalent form uses one multiplication:
            // h_new = n + z*(h_old-n)
            DT_ACC state_update = (DT_ACC)nn + (DT_ACC)z * ((DT_ACC)h_state[i] - (DT_ACC)nn);

            h_new[i] = (DT_ACT)state_update;

            // Output accumulation in the same loop (depth-1 carried add).
            y_acc += (DT_ACC)(w_out[i] * h_new[i]);
        }

        DT_ACC y = (DT_ACC)b_out;

    // State commit, fully unrolled: H parallel register copies
    // (h_state and h_new are both complete-partitioned). Cannot merge into
    // HIDDEN_LOOP because later hidden units read the old h_state.
    COMMIT:
        for (int i = 0; i < H; i++)
        {
#pragma HLS UNROLL
            h_state[i] = h_new[i];
        }
        y += y_acc; // bias already in y

        // same as above where it is a shared mem
        union
        {
            unsigned int u;
            float f;
        } conv_out;
        conv_out.f = (float)y;
        axis_sample out_pkt;

        // outpacket settings
        out_pkt.data = conv_out.u;
        out_pkt.keep = -1;
        out_pkt.strb = -1;
        out_pkt.last = (n == n_samples - 1) ? 1 : 0;

        // audio out
        audio_out.write(out_pkt);
    }
}
