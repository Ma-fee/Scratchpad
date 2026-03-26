#!/usr/bin/env bash
arena serve kserve \
    --loglevel debug \
    --name=qwen3-turbo-serv \
    --image=acs-registry-vpc.cn-shanghai.cr.aliyuncs.com/egslingjun/inference-xpu-pytorch:25.05-v1.5.1-vllm0.8.5-torch2.6-cu126-20250528 \
    --cpu=16 \
    --memory=128Gi \
    --share-memory 64Gi \
    -l alibabacloud.com/acs=true \
    -l alibabacloud.com/compute-class=gpu-hpn \
    -l alibabacloud.com/compute-qos=default \
    -l alibabacloud.com/gpu-model-series=PPU810E \
    -l alibabacloud.com/gpu-driver-version="1.5.0" \
    `# -l alibabacloud.com/hpn-type=rdma` \
    -l alibabacloud.com/fluid-sidecar-target=acs \
    --device alibabacloud.com/ppu=4 \
    --enable-prometheus=true \
    --scale-metric=DCGM_CUSTOM_PROCESS_SM_UTIL \
    --scale-target=60 \
    --min-replicas=1 \
    --max-replicas=2 \
    `# --data=yilab-oss-cache-lmt-pvc:/mnt/cache` \
    --data=pai-oss-qwen-lmt-pvc:/mnt/pai-oss-qwen \
    --config-file ./config/qwen3.yaml:/app/config.yaml \
    `# --data=cpfs01-root-pvc:/mnt/cpfs01` \
    --env OMP_NUM_THREADS=30 \
    --env VLLM_ATTENTION_BACKEND=FLASHINFER \
    "vllm serve /mnt/pai-oss-qwen/Qwen3-32B --served-model-name qwen3-turbo --tensor-parallel-size 4 --config /app/config.yaml"
