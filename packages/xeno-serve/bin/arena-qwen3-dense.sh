#!/usr/bin/env bash

arena serve kserve \
    --loglevel debug \
    --name=qwen3-32b-serv \
    --image=acs-registry-vpc.cn-shanghai.cr.aliyuncs.com/egslingjun/inference-xpu-pytorch:25.05-v1.5.1-vllm0.8.5-torch2.6-cu126-20250520 \
    --cpu=16 \
    --memory=128Gi \
    -l alibabacloud.com/acs=true \
    -l alibabacloud.com/compute-class=gpu-hpn \
    -l alibabacloud.com/compute-qos=default \
    -l alibabacloud.com/gpu-model-series=PPU810E \
    -l alibabacloud.com/hpn-type=rdma \
    --device alibabacloud.com/ppu=2 \
    --enable-prometheus=true \
    --scale-metric=DCGM_CUSTOM_PROCESS_SM_UTIL \
    --scale-target=60 \
    --min-replicas=1 \
    --max-replicas=1 \
    --data=yilab-ai-models:/mnt \
    --data=pai-oss-qwen-pvc:/mnt2 \
    --env VLLM_ATTENTION_BACKEND=FLASHINFER \
    --env OMP_NUM_THREADS=10 \
    "python3 -m vllm.entrypoints.openai.api_server --model /mnt/modelscope/models/Qwen/Qwen3-32B-AWQ --port 8080 --served-model-name qwen3-32b --tensor-parallel-size 2 --trust-remote-code --gpu-memory-utilization 0.95 --enable-auto-tool-choice --tool-call-parser hermes --reasoning-parser deepseek_r1 --enable_reasoning"

    # --gpus=1 \
    # "python3 -m vllm.entrypoints.openai.api_server --model /mnt/modelscope/models/Qwen/Qwen2___5-VL-72B-Instruct-AWQ --port 8080 --served-model-name qwen-vl --tensor-parallel-size 2 --trust-remote-code --gpu-memory-utilization 0.95 --enable-auto-tool-choice --tool-call-parser hermes --max_model_len 32768 --mm-processor-kwargs '{\"max_pixels\":4014080,\"min_pixels\":200704}'"
    # --data=cpfs01-data-pvc:/mnt3 \
