#ifndef _GRU_WEIGHTS_H
#define _GRU_WEIGHTS_H
#include "gru_va.h"

// Defined once in gru_load.cpp

// --- weight-storage switch: single point of control for ALL .cpp files ---
#define USE_COMPILED_WEIGHTS // comment out for the m_axi runtime-load build

#ifdef USE_COMPILED_WEIGHTS
// compiled-in ROM: const definitions live in weights.h (generated)
extern const DT_W W_r[H], W_z[H], W_n[H];
extern const DT_W U_r[H][H], U_z[H][H], U_n[H][H];
extern const DT_W b_ir[H], b_iz[H], b_in[H];
extern const DT_W b_hr[H], b_hz[H], b_hn[H];
extern const DT_W w_out[H];
extern const DT_W b_out;
#else
// runtime m_axi preload: mutable definitions live in gru_load.cpp
extern DT_W W_r[H], W_z[H], W_n[H];
extern DT_W U_r[H][H], U_z[H][H], U_n[H][H];
extern DT_W b_ir[H], b_iz[H], b_in[H];
extern DT_W b_hr[H], b_hz[H], b_hn[H];
extern DT_W w_out[H];
extern DT_W b_out;
#endif

extern DT_ACT h_state[H];

void gru_load_weights(const float *weights);
#endif
