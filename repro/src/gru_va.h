// gru_va.h
#ifndef _GRU_VA_H
#define _GRU_VA_H

#include <ap_fixed.h>
#include <hls_stream.h>
#include <ap_axi_sdata.h>

const static int H = 40; // hidden size (locked recipe)
const static int IN_DIM = 1;

//#define DTW_W 32
//#define DTW_I 12

//#define DTACT_W 32
//#define DTACT_I 12

#ifndef DTW_W
#define DTW_W 20
#endif
#ifndef DTW_I
#define DTW_I 5
#endif
#ifndef DTACT_W
#define DTACT_W 20
#endif
#ifndef DTACT_I
#define DTACT_I 2
#endif

typedef ap_fixed<DTW_W, DTW_I, AP_RND_CONV, AP_SAT> DT_W;
typedef ap_fixed<DTACT_W, DTACT_I, AP_RND_CONV, AP_SAT> DT_ACT;
typedef ap_fixed<32, 12, AP_RND_CONV, AP_SAT> DT_ACC; // never swept

// -------------------------------------------------------------------

// PyTorch GRU weight layout: W_ih is (3H x 1), W_hh is (3H x H),
// gate order r, z, n  (rows 0..H-1 = r, H..2H-1 = z, 2H..3H-1 = n)
// *3 b/c concatenates the reset, update, and new-gate parameters
const static int N_WIH = 3 * H * IN_DIM; // 120
const static int N_WHH = 3 * H * H;      // 4800
const static int N_BIH = 3 * H;          // 120
const static int N_BHH = 3 * H;          // 120
const static int N_WOUT = H;             // 40  (output linear W)
const static int N_BOUT = 1;
const static int N_WEIGHTS = N_WIH + N_WHH + N_BIH + N_BHH + N_WOUT + N_BOUT; // 5201

typedef ap_axiu<32, 0, 0, 0> axis_sample; // 32-bit float bits per sample beat

void gru_va(hls::stream<axis_sample> &audio_in,
            hls::stream<axis_sample> &audio_out,
            const float *weights,   // m_axi: flat FP32 buffer, quantized on-chip at preload
            const int mode,         // 0 = preload weights, 1 = run inference
            const int n_samples,    // block length when mode==1
            const int reset_state); // 1 = zero hidden state before this block

#endif
