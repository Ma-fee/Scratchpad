arena submit pytorch \
    --loglevel debug \
    --name=pytorch-mnist \
    --workers=1 \
    -l alibabacloud.com/acs=true \
    -l alibabacloud.com/compute-class=gpu-hpn \
    -l alibabacloud.com/compute-qos=default \
    -l alibabacloud.com/gpu-model-series=PPU810E \
    -l alibabacloud.com/gpu-driver-version="1.5.0" \
    -l alibabacloud.com/hpn-type=rdma \
    --device alibabacloud.com/ppu=2 \
    --queue \
    --working-dir=/root \
    --image=acs-registry-vpc.cn-shanghai.cr.aliyuncs.com/egslingjun/training-xpu-pytorch:25.05 \
    --config-file ./config/qwen3-30b-a3b-gpt4-int4.yaml:/app/config.yaml \
    --data=cpfs01-root-lmt-pvc:/mnt \
    --logdir=/mnt/pytorch_data/logs \
    "sh -c 'tail -f /dev/null'"
        # -l alibabacloud.com/gpu-driver-version=1.5.1 \
