#!/usr/bin/env bash

./bin/arena-serve.sh /mnt/modelscope/qwen/Qwen3-235B-A22B \
    -n qwen3-moe-plus-serv \
    -c 16 -m 96 -g 8 \
    --share-memory 80Gi \
    --config ./config/qwen3.yaml \
    --env OMP_NUM_THREADS=10 \
    --env VLLM_ATTENTION_BACKEND=FLASHINFER \
    --data pvc-pai-oss-modelscope-lmt:/mnt/modelscope \
    -- --served-model-name qwen3-moe-plus