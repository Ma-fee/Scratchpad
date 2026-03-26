#!/usr/bin/env bash
    # --gpumemory 32 \ --gpucore 100 \
./bin/arena-serve.sh /mnt/modelscope/models/Qwen/Qwen2___5-VL-72B-Instruct-AWQ \
    -n qwen-vl-serv \
    -c 16 -m 64 \
    -g 4 \
    --share-memory 40Gi \
    --config ./config/qwen25-vl.yaml \
    --env OMP_NUM_THREADS=10 \
    --env VLLM_ATTENTION_BACKEND=FLASH_ATTN \
    --data pvc-yilab-oss-cache:/mnt/
