#include "gru_weights.h"

// h_state stays mutable in both configurations
DT_ACT h_state[H];

// #define USE_COMPILED_WEIGHTS

#ifdef USE_COMPILED_WEIGHTS

#include "weights.h" // const definitions of W_r..b_out (generated)

void gru_load_weights(const float *weights)
{
    (void)weights; // nothing to do; weights are compiled-in ROM
}

#else // runtime m_axi preload (deployment configuration)

DT_W W_r[H], W_z[H], W_n[H];
DT_W U_r[H][H], U_z[H][H], U_n[H][H];
DT_W b_ir[H], b_iz[H], b_in[H];
DT_W b_hr[H], b_hz[H], b_hn[H];
DT_W w_out[H];
DT_W b_out;

// Flat buffer contract (matches export_gru_weights.py):
// w_ih[3H] -> w_hh[3H][H] row-major -> b_ih[3H] -> b_hh[3H] -> w_out[H] -> b_out
// Gate row order within each block: r (0..H-1), z (H..2H-1), n (2H..3H-1)
void gru_load_weights(const float *weights)
{
    int idx = 0;
    for (int i = 0; i < H; i++)
        W_r[i] = (DT_W)weights[idx++];
    for (int i = 0; i < H; i++)
        W_z[i] = (DT_W)weights[idx++];
    for (int i = 0; i < H; i++)
        W_n[i] = (DT_W)weights[idx++];

    for (int i = 0; i < H; i++)
        for (int j = 0; j < H; j++)
        {
            // #pragma HLS PIPELINE II=1 off
            U_r[i][j] = (DT_W)weights[idx++];
        }
    for (int i = 0; i < H; i++)
        for (int j = 0; j < H; j++)
        {
            // #pragma HLS PIPELINE II=1 off
            U_z[i][j] = (DT_W)weights[idx++];
        }
    for (int i = 0; i < H; i++)
        for (int j = 0; j < H; j++)
        {
            // #pragma HLS PIPELINE II=1 off
            U_n[i][j] = (DT_W)weights[idx++];
        }

    for (int i = 0; i < H; i++)
        b_ir[i] = (DT_W)weights[idx++];
    for (int i = 0; i < H; i++)
        b_iz[i] = (DT_W)weights[idx++];
    for (int i = 0; i < H; i++)
        b_in[i] = (DT_W)weights[idx++];

    for (int i = 0; i < H; i++)
        b_hr[i] = (DT_W)weights[idx++];
    for (int i = 0; i < H; i++)
        b_hz[i] = (DT_W)weights[idx++];
    for (int i = 0; i < H; i++)
        b_hn[i] = (DT_W)weights[idx++];

    for (int i = 0; i < H; i++)
        w_out[i] = (DT_W)weights[idx++];
    b_out = (DT_W)weights[idx++];
}

#endif
