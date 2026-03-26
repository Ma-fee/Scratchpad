#!/usr/bin/env bash

IMAGE="irootechimages-registry-vpc.cn-shanghai.cr.aliyuncs.com/llm/inference-xpu-pytorch:25.05-v1.5.1-vllm0.8.5-torch2.6-cu126-20250604-llama-swap"

./bin/arena-serve.sh /mnt \
    -n arena-multi-serve \
    -c 8 -m 32 -g 1 \
    --config-file ./config/llama-swap.yaml:/app/config.yaml \
    --config-file ./config/qwen3.yaml:/config/qwen3.yaml \
    --env OMP_NUM_THREADS=6 \
    --data pvc-yilab-oss-cache:/mnt/ \
    -i ${IMAGE} \
    -p