#!/usr/bin/env bash

./bin/arena-serve.sh /mnt/modelscope/models/Qwen/Qwen3-30B-A3B \
    -n qwen3-moe-turbo-serv \
    -c 16 -m 64 -g 4 \
    --config ./config/qwen3.yaml \
    --env OMP_NUM_THREADS=10 \
    --env VLLM_ATTENTION_BACKEND=FLASHINFER \
    --data pvc-yilab-oss-cache:/mnt/ \
    -- --served-model-name qwen3-moe
