#!/bin/sh
# SENTINEL: PACK-REV1-2026-08-09
# board_cleanup_pack.sh -- run ON THE BOARD. Packs two archives with MD5s.
# Deletes NOTHING. Explicit file lists only -- no wildcards.
set -e
cd /home/xilinx/jupyter_notebooks
echo "SENTINEL: PACK-REV1-2026-08-09"

mkdir -p campaign102

tar czf old_labs_2026.tar.gz \
  "Lab 3 Burst 32.ipynb" \
  "Lab 3 Prob 2 64 concat.ipynb" \
  "Lab 3 Prob 2 64.ipynb" \
  "Lab 3 Problem 1 100.ipynb" \
  "Lab 3 Problem 2 Burst.ipynb" \
  "Lab 3 Problem 2.ipynb" \
  "Lab 4 Batch.ipynb" \
  "Lab 4 DMA Batch.ipynb" \
  "Lab 4 DMA.ipynb" \
  "Lab 4 Part D.ipynb" \
  "Lab 4.ipynb" \
  "Log Reg Final 2.ipynb" \
  "Log Reg Final 3.ipynb" \
  "Logistic Regression Final Project.ipynb" \
  "Welcome to Pynq.ipynb" \
  "Example2.ipynb" \
  "Example3.ipynb" \
  "prelab_3.ipynb" \
  "log_reg_1.bit" "log_reg_1.hwh" \
  "log_reg_2.bit" "log_reg_2.hwh" \
  "X_train.csv" "X_test.csv" "y_train.csv" "y_test.csv" \
  "loaded.xclbin"
md5sum old_labs_2026.tar.gz > old_labs_2026.tar.gz.md5

tar czf gru_history_pre102.tar.gz \
  "gru_va_P40.bit" "gru_va_P40.hwh" \
  "gru_va_100_20_5.bit" "gru_va_100_20_5.hwh" \
  "gru_va_fused_L20.bit" "gru_va_fused_L20.hwh" \
  "gru_bin_version_64.bit" "gru_bin_version_64.hwh" \
  "board_nam_out_w20_p40.f32" \
  "board_nam_out_w20.f32" \
  "board_nam_out_p40_ch65536.f32" \
  "board_nam_out_p40_ch262144.f32" \
  "board_nam_out_p40_ch1048576.f32" \
  "board_nam_out_fused_L20.f32" \
  "board_golden_out_p40.f32" \
  "board_golden_out_fused_L20.f32" \
  "board_golden_out.f32" \
  "cpu_golden_out.f32" \
  "gru_board_bringup_p40.ipynb" \
  "gru_board_bringup.ipynb" \
  "weights_flat.bin"
md5sum gru_history_pre102.tar.gz > gru_history_pre102.tar.gz.md5

echo "---- archives ----"
ls -lh old_labs_2026.tar.gz gru_history_pre102.tar.gz
cat old_labs_2026.tar.gz.md5 gru_history_pre102.tar.gz.md5
echo "pack complete -- nothing deleted"
