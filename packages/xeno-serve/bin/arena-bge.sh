#!/usr/bin/env bash
arena serve kserve \
    --loglevel debug \
    --name=bge-m3-serv \
    --image=acs-registry-vpc.cn-shanghai.cr.aliyuncs.com/egslingjun/inference-xpu-pytorch:25.05-v1.5.1-vllm0.8.5-torch2.6-cu126-20250512 \
    --cpu=10 \
    --memory=80Gi \
    -l alibabacloud.com/acs=true \
    -l alibabacloud.com/compute-class=gpu-hpn \
    -l alibabacloud.com/compute-qos=default \
    -l alibabacloud.com/gpu-model-series=PPU810E \
    -l alibabacloud.com/hpn-type=rdma \
    --device alibabacloud.com/ppu=1 \
    --enable-prometheus=true \
    --scale-metric=DCGM_CUSTOM_PROCESS_SM_UTIL \
    --scale-target=60 \
    --min-replicas=1 \
    --max-replicas=1 \
    --data=yilab-ai-models:/mnt \
    --env OMP_NUM_THREADS=10 \
    "vllm serve /mnt/modelscope/models/BAAI/bge-m3 --port 8080 --served-model-name bge-m3 --trust-remote-code --gpu-memory-utilization 0.95"

