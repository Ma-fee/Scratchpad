#!/usr/bin/env bash

./bin/arena-serve.sh /mnt/modelscope/models/Qwen/Qwen3-Reranker-4B \
    -n qwen3-rerank-turbo-serv \
    -c 8 -m 32 -g 1 \
    --config ./config/qwen3.yaml \
    --env OMP_NUM_THREADS=6 \
    --data pvc-yilab-oss-cache:/mnt/ \
    -- --served-model-name qwen3-rerank-turbo
